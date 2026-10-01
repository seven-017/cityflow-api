import secrets
from datetime import date, datetime

from sqlalchemy.orm import Session

from app.core.exceptions import (
    BusinessException,
    ConcurrentUpdateException,
    NotFoundException,
    PermissionDeniedException,
)
from app.core.permissions import RoleCode
from app.core.work_order_sla import SLA_SOURCE_PLATFORM, compute_sla_deadline
from app.core.work_order_status import (
    ENGINEER_ALLOWED_ACTIONS,
    WorkOrderAction,
    WorkOrderStatus,
    resolve_transition,
)
from app.models import User, WorkOrder, WorkOrderProcessingRecord, WorkOrderStatusHistory
from app.repositories.operation_logs import OperationLogRepository
from app.repositories.users import UserRepository
from app.repositories.work_orders import WorkOrderRepository
from app.schemas.common import CursorMeta
from app.schemas.work_orders import (
    WorkOrderAssignRequest,
    WorkOrderCreateRequest,
    WorkOrderDetail,
    WorkOrderRecordItem,
    WorkOrderSummary,
)


def work_order_summary(work_order: WorkOrder) -> WorkOrderSummary:
    """把一条 WorkOrder 搬成 WorkOrderSummary。

    跟 assets 那边一模一样的代价：ORM 对象不能直接往外扔，得手动一个个搬。
    这边字段名跟模型同名，看着像废话，但这是故意的 ——
    不这么写的话，哪天想改个对外名字（比如把 source_record_id 叫成 work_order_no）
    就得连着模型一起动，那就不是"挑字段"而是"改数据库"了。
    """
    return WorkOrderSummary(
        id=work_order.id,
        source_record_id=work_order.source_record_id,
        data_source=work_order.data_source,
        description=work_order.description,
        work_type=work_order.work_type,
        status=work_order.status,
        request_date=work_order.request_date,
        completion_date=work_order.completion_date,
    )


def work_order_detail(work_order: WorkOrder) -> WorkOrderDetail:
    """把一条 WorkOrder 搬成 WorkOrderDetail。

    这已经是第三个这种搬运函数了（asset_summary / asset_detail / 这个）。
    三份长得几乎一样的东西摆在这儿，说好听点叫"每个视图互不干扰"，
    说难听点就是啰嗦。暂时不动 —— 真要收拾，应该是等第 19、20 步都做完，
    看看总共有几个视图，再决定是抽个基类还是干脆别抽。
    现在三个还看不出规律，提前抽反而抽错。
    """
    return WorkOrderDetail(
        id=work_order.id,
        source_record_id=work_order.source_record_id,
        data_source=work_order.data_source,
        asset_id=work_order.asset_id,
        asset_source_record_id=work_order.asset_source_record_id,
        description=work_order.description,
        work_type=work_order.work_type,
        work_class=work_order.work_class,
        status=work_order.status,
        status_origin=work_order.status_origin,
        source_status=work_order.source_status,
        request_date=work_order.request_date,
        created_source_at=work_order.created_source_at,
        completion_date=work_order.completion_date,
        scheduled_end_date=work_order.scheduled_end_date,
        assigned_title=work_order.assigned_title,
        assigned_to_id=work_order.assigned_to_id,
        source_notes=work_order.source_notes,
        duration=work_order.duration,
        job_type=work_order.job_type,
        source_update_count=work_order.source_update_count,
        priority=work_order.priority,
        sla_deadline=work_order.sla_deadline,
        sla_source=work_order.sla_source,
        created_at=work_order.created_at,
        updated_at=work_order.updated_at,
    )


# 双数据源的两面旗子。官方导进来的那批是 REAL_PUBLIC（只读，谁都不许改），
# 平台自己录的走 SYNTHETIC_PLATFORM。
# 每个写操作的第一道闸门都要拿这个值比，所以起两个名字放这儿，别到处写字符串 ——
# 手写字符串敲错了不会报错，只会让闸门的结果跟你以为的不一样，那种错最难查。
DATA_SOURCE_PUBLIC = "REAL_PUBLIC"
DATA_SOURCE_PLATFORM = "SYNTHETIC_PLATFORM"


# 平台自己录的工单用它自己的一套编号：PF- 后面跟 12 位十六进制。
#
# 为什么不用"查一下现在有多少条、然后加一"这种序号：两个人同时创建会算出同一个号，
# 其中一个撞上 (data_source, source_record_id) 那个唯一约束，直接 500 ——
# 而且这种错还不好复现，只有真并发的时候才冒出来。
# 随机串不用读库、不会撞、并发安全。代价是号不连续、不好看；
# 拿"不好看"换"不用加锁也不会错"，这笔买卖划算。
#
# 12 位十六进制 = 16 的 12 次方 ≈ 2.8e14 种。真撞上了会是个 500，
# 但那概率小到不值得为它写重试逻辑。这是故意留的瑕疵，不是没想到。
#
# PF 就是 platform 的意思，跟 data_source 那个 SYNTHETIC_PLATFORM 对得上。
SOURCE_RECORD_ID_PREFIX = "PF-"


def generate_source_record_id() -> str:
    """生成一个平台工单号，长这样：PF-3f9a2c81b7d4。"""
    return SOURCE_RECORD_ID_PREFIX + secrets.token_hex(6)


def is_manager(user: User) -> bool:
    """这个人是管理型角色吗（ADMIN / DISPATCHER）。

    文档里说"Admin 和 Dispatcher 可以执行管理型转换"，所以这两类人不吃
    "只能碰自己的单"和"只能开始/完成"那两条限制 —— 调度本来就是替别人排活的。

    user.roles 在模型上是 lazy="selectin"，取用户的时候已经用一条 IN 语句
    把角色一起捞回来了（顺便还带了权限），所以这儿循环一遍不会再打查询。
    """
    return any(
        role.code in (RoleCode.ADMIN, RoleCode.DISPATCHER) for role in user.roles
    )


class WorkOrderService:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.work_orders = WorkOrderRepository(db)
        self.logs = OperationLogRepository(db)
        # 分派得把单派到人身上，所以这儿也要一个用户仓储。
        # repository 是按表切的，service 组合几个都行 —— system 那边就同时用了三个
        self.users = UserRepository(db)

    def list_work_orders(
        self, *, after_id: int | None, limit: int
    ) -> tuple[list[WorkOrderSummary], CursorMeta]:
        # 这里原来第一句是 total = self.work_orders.count_work_orders()，2026-09-29 删了。
        # 那一下是 322~358 ms，占整个请求的 75% —— 接口慢就慢在这一句上。
        # 为什么干脆不报总数，理由写在 schemas/common.py 的 CursorMeta 上。
        rows = self.work_orders.list_work_orders(after_id=after_id, limit=limit)
        has_more = len(rows) > limit
        # 多要的那条只是探路的，不能发出去
        page_rows = rows[:limit]
        next_cursor = page_rows[-1].id if has_more and page_rows else None
        items = [work_order_summary(w) for w in page_rows]
        return items, CursorMeta(
            limit=limit,
            next_cursor=next_cursor,
            has_more=has_more,
        )

    def get_work_order(self, work_order_id: int) -> WorkOrderDetail:
        """查单条，查不到就 404。

        这里比 assets 那边多啰嗦一句：工单是有状态流转的东西，
        按理说详情页该把流转记录（work_order_status_history）和
        处理记录（work_order_processing_records）一起带出来。

        现在还是没带。原来不带的理由是"那两张表实测都是 0 行 —— 官方导入的数据里
        一条流转记录都没有，给一个永远是空的数组留个字段位没意义"。
        这个理由现在已经不成立了：从 18b 起建单就会写流水，18e 之后还能一直往里加备注。

        没顺手补上的原因是那是另一件事，不是一个体量的活：
        读两张子表要挑字段、要防 N+1、还得决定要不要分页。
        留到做详情页那块的时候一起弄，那时候连前端要什么形状都清楚了。
        """
        work_order = self.work_orders.get_by_id(work_order_id)
        if work_order is None:
            raise NotFoundException(f"Work order {work_order_id} not found.")
        return work_order_detail(work_order)

    def create_work_order(
        self,
        *,
        payload: WorkOrderCreateRequest,
        operator: User,
        request_path: str,
        ip_address: str | None,
    ) -> WorkOrderDetail:
        """平台自己录一条工单。

        这一步有三样东西要一起落库：工单本身、一条状态流水、一条操作日志。
        后两样少写一个，工单就成了"凭空出现"的 ——
        详情页上说不清它怎么来的，审计也查不到是谁录的。

        另外顺手把 SLA 也算出来（优先级 -> 目标完成时间）。这个不算"多做了一步"：
        deadline 是从"建单那一刻"往后加的，只有在这儿才拿得到那个时刻 ——
        放到别处（比如做成定时任务去补）反而得费劲地问"这张单是什么时候建的"。

        注意 sla_deadline 这一列官方导入的单全是 NULL，我们也不去补它们 ——
        文档里说过，不给历史数据伪造 SLA。
        """
        # deadline 是从"建单这一刻"往后加的，所以这个时刻得在这儿取。
        # 用 Python 的本地时间，跟库里 created_at 那个 func.now() 是同一个基准
        # （都跑在这台机器上）；将来要是应用和数据库拆到两台机器、时区还不一样，
        # 这儿就得改成拿数据库的时间来算
        started_at = datetime.now()

        work_order = WorkOrder(
            source_record_id=generate_source_record_id(),
            # 双数据源隔离的落点。官方导入的那些是 REAL_PUBLIC（只读，不许动），
            # 平台自己录的走 SYNTHETIC_PLATFORM。这一列决定了后面分派、流转、
            # 加处理记录时第一道闸门放不放行 —— 写错了后面全被挡
            data_source=DATA_SOURCE_PLATFORM,
            description=payload.description,
            work_type=payload.work_type,
            asset_source_record_id=payload.asset_source_record_id,
            scheduled_end_date=payload.scheduled_end_date,
            # 新单从"待处理"开始，这是状态机的入口
            status=WorkOrderStatus.PENDING.value,
            # 状态来源记 PLATFORM。官方数据那边是 DERIVED_FROM_SOURCE，
            # 详情页靠这个值告诉前端"这状态是人改的还是导入时推出来的"
            status_origin="PLATFORM",
            # 申请日期就是今天。官方数据里这一列有 15% 是空的，
            # 我们自己的单自己填，不跟着空
            request_date=date.today(),
            # SLA 三件套。优先级是录单时选的；deadline 拿它算出来；
            # source 标明这是平台自己算的，不是从哪份数据里抄来的 ——
            # 这三个字段是配套的，只写前两个的话，将来分不清
            # 一个 deadline 到底是平台算的，还是从别处导进来的
            priority=payload.priority.value,
            sla_deadline=compute_sla_deadline(payload.priority, started_at),
            sla_source=SLA_SOURCE_PLATFORM,
            created_by_id=operator.id,
        )
        self.work_orders.add(work_order)

        # 得先 flush 才拿得到自增主键 —— 下面两条记录都要用这个 id。
        # flush 只是把 SQL 发出去，还没提交，出错照样能一起回滚
        self.db.flush()

        # 从无到有也算一次流转，只不过 from_status 是 None：
        # 它不是从哪个状态过来的，是被造出来的
        self.work_orders.add_status_history(
            WorkOrderStatusHistory(
                work_order_id=work_order.id,
                from_status=None,
                to_status=WorkOrderStatus.PENDING.value,
                operator_id=operator.id,
            )
        )

        self.logs.add(
            user_id=operator.id,
            operation="CREATE_WORK_ORDER",
            module="work_order",
            target_type="work_order",
            target_id=str(work_order.id),
            request_method="POST",
            request_path=request_path,
            result="SUCCESS",
            detail=f"source_record_id={work_order.source_record_id}",
            ip_address=ip_address,
        )

        # 三张表在这儿一起提交。上面任何一步抛异常，这些 add 都还留在 session 里
        # 没落库，异常冒上去之后 session 会被关掉，等于整批回滚 ——
        # 不会出现"工单建好了但流水没写"这种半截数据
        self.db.commit()

        # created_at / updated_at 是数据库 server_default 生成的，
        # 提交之后 ORM 里那份还是旧的，刷一下再搬给 schema
        self.db.refresh(work_order)
        return work_order_detail(work_order)

    def assign_work_order(
        self,
        *,
        work_order_id: int,
        assignee_id: int,
        operator: User,
        request_path: str,
        ip_address: str | None,
    ) -> WorkOrderDetail:
        """把一张待处理的单派给某个工程师。

        这个接口前后有四个闸门，按顺序过，哪道没过就停在哪道。报错要能分清是哪一种 ——
        调度员看到光秃秃一句"操作失败"，是不知道该改什么的。
        权限那道在路由层就被 require_permissions 挡掉了，所以这儿只剩三道。

        注意这里是"先查、再判、最后改"。并发下那段空隙跟下面 _transition 一模一样
        （2026-09-30 在那边复现过，现象和数字记在那个方法的注释里），
        修的时候两处一起改的，都是同一句带条件的 UPDATE。
        """
        work_order = self.work_orders.get_by_id(work_order_id)
        if work_order is None:
            raise NotFoundException(f"Work order {work_order_id} not found.")

        # 闸门一：数据源。官方导进来那批是只读的 ——
        # 这不是我们定的规矩，是业务文档写死的：那批数据代表"已经发生过的事"，
        # 谁改了就说不清了。只有平台自己录的单才允许流转
        if work_order.data_source != DATA_SOURCE_PLATFORM:
            raise PermissionDeniedException(
                f"Work order {work_order_id} is imported public data, cannot be assigned."
            )

        # 闸门二：状态。拿 18a 那张允许表来判断，别在这儿再写一遍 if ——
        # 规则只有一份，在 core/work_order_status.py 里
        current_status = WorkOrderStatus(work_order.status)
        target_status = resolve_transition(current_status, WorkOrderAction.ASSIGN)

        # 闸门三：被派的人得真的能干活。这三件事一次查出来
        # （get_by_id 顺手把 roles 也捞回来了），不是循环里一条条查
        assignee = self.users.get_by_id(assignee_id)
        if assignee is None:
            raise NotFoundException(f"User {assignee_id} not found.")
        if not assignee.enabled:
            raise BusinessException(
                f"User {assignee_id} is disabled, cannot take work orders."
            )
        if not any(role.code == RoleCode.ENGINEER for role in assignee.roles):
            raise BusinessException(
                f"User {assignee_id} is not an engineer, cannot be assigned."
            )

        # 三道全过了。要改的是两列：状态往后走一格，同时记下派给了谁。
        # 跟 _transition 一样走带条件的 UPDATE —— 两个人同时点分派，
        # 后到的那个匹配不到行、拿到 0，然后老实报"有人先动手了"
        affected = self.work_orders.apply_transition(
            work_order_id=work_order.id,
            from_status=current_status.value,
            to_status=target_status.value,
            extra_values={"assigned_to_id": assignee.id},
        )
        if affected == 0:
            raise ConcurrentUpdateException(
                f"Work order {work_order_id} was changed by someone else, "
                f"reload and try again."
            )

        # 同上：绕过 ORM 改的，刷新一下再往下走
        self.db.refresh(work_order)

        # 流水里的 from_status 用的是改之前那个状态，所以上面特意先存成 current_status ——
        # 要是直接读 work_order.status，那会儿它已经被改成 ASSIGNED 了，
        # 流水就会写成"ASSIGNED -> ASSIGNED"这种自己到自己的鬼话
        self.work_orders.add_status_history(
            WorkOrderStatusHistory(
                work_order_id=work_order.id,
                from_status=current_status.value,
                to_status=target_status.value,
                operator_id=operator.id,
            )
        )

        self.logs.add(
            user_id=operator.id,
            operation="ASSIGN_WORK_ORDER",
            module="work_order",
            target_type="work_order",
            target_id=str(work_order.id),
            request_method="POST",
            request_path=request_path,
            result="SUCCESS",
            detail=f"assigned_to={assignee.username}",
            ip_address=ip_address,
        )

        # 四件事一起提交：改状态、写派单人、落流水、落日志。
        # 少任何一样这单都说不清楚 —— 状态变了却没流水，就是"它凭空跳过了一步"
        self.db.commit()
        self.db.refresh(work_order)
        return work_order_detail(work_order)

    def _transition(
        self,
        *,
        work_order_id: int,
        action: WorkOrderAction,
        operator: User,
        request_path: str,
        ip_address: str | None,
        reason: str | None = None,
        completion_date: date | None = None,
    ) -> WorkOrderDetail:
        """四个流转动作共用的那段，单独抽出来。

        开始 / 完成 / 关闭 / 驳回这四件事，除了「动作不一样」和「要不要额外写一列」，
        别的几步一模一样：查单 -> 挡官方只读数据 -> 过状态机 -> 改状态 ->
        落流水 -> 落日志 -> 一起提交。抄四遍的话，哪天要加一道闸门就得改四处，
        漏掉一处的表现是"那个动作漏了一道校验"，不会有任何报错提醒你。

        跟分派那条比，这儿少一道闸门（被派的人存不存在）——
        那几个动作不需要指定人，谁点的就是谁。

        注意这里是"先查、再判、最后改"。判完到写库之间那段空隙，原来是敞着的，
        两个请求前后脚进来就会双双通过。2026-09-30 复现过，修法也写在下面那段注释里。
        """

        # ================= 并发：先说清楚原来错在哪 =================
        #
        # 这个方法是"先查、再判、最后改"。最早那版判完就直接改对象属性，
        # 判完到写库之间没有任何东西拦着别人。2026-09-30 用两个连接加一道栅栏
        # 把交错手工摆出来（探针是一次性的，不进仓库），回回都能复现：
        #
        #     T1 点开始：动手前读到 ASSIGNED -> 成功，返回 IN_PROGRESS
        #     T2 点驳回：动手前读到 ASSIGNED -> 成功，返回 REJECTED
        #     最终状态：REJECTED
        #     流水 4 行：None->PENDING / PENDING->ASSIGNED
        #                / ASSIGNED->IN_PROGRESS / ASSIGNED->REJECTED
        #
        # 麻烦的是最后两行：两个从 ASSIGNED 出发、方向相反的流转，都写进去了，
        # 而工单只有一个最终状态。事后翻流水，说不清它是被开工了还是被驳回了。
        # 更烦的是 T1 拿到的是 200 加一个 IN_PROGRESS —— 界面上写着"已开工"，
        # 库里其实是 REJECTED，一直要到有人拿着流水来对账才发现。
        #
        # 根子在哪儿：两个事务都读到 ASSIGNED，两边都觉得自己这个动作合法。
        # 这跟"加锁"不是一回事 —— 行锁挡的是"同时写"，挡不住"基于一个已经过期的
        # 状态做判断"：后到的人照样能拿到锁、照样能写，他只是不该写。
        #
        # 修法就是下面那句带条件的 UPDATE。同一个交错再跑一遍：
        #
        #     T1 点开始：成功，返回 IN_PROGRESS
        #     T2 点驳回：40901，流水里没有它那一行
        #     最终状态：IN_PROGRESS，流水 3 行
        #
        # 顺便记一个教训。这个修法第一次跑，探针里 T2 报的是
        #     TypeError: ConflictException.__init__() got an unexpected keyword argument 'code'
        # —— 我图省事想给 ConflictException 传个自定义码，可那个子类压根不收这个参数。
        # 要命的是：46 项验收里没有并发场景，全绿；这个错只有探针撞得出来。
        # 所以"改完再跑一遍探针"不是走形式。
        # ============================================================

        work_order = self.work_orders.get_by_id(work_order_id)
        if work_order is None:
            raise NotFoundException(f"Work order {work_order_id} not found.")

        # 闸门一：数据源。跟分派那边同一句话 —— 官方导进来的是只读的，
        # 它代表"已经发生过的事"，谁改了都说不清
        if work_order.data_source != DATA_SOURCE_PLATFORM:
            raise PermissionDeniedException(
                f"Work order {work_order_id} is imported public data, "
                f"cannot run {action.value}."
            )

        # 闸门二：这个动作归不归你。文档里关于工单的三条规则，这儿落两条
        # （第三条"ASSIGNED 必须通过分派接口设置工程师"在 assign_work_order 那边）：
        #
        #     "Engineer 只能更新分配给自己的工单。"
        #     "Engineer 只能执行 ASSIGNED -> IN_PROGRESS 和 IN_PROGRESS -> COMPLETED。"
        #
        # 这两句是分开的两件事，都得判：第一句管"哪张单"，第二句管"哪个动作"。
        # 少判第一句，工程师能把别人手上的单点成已完成；
        # 少判第二句，工程师能自己驳回自己接不了的活，或者干脆把单关掉。
        #
        # 2026-10-01 补的。18d 刚做出来的时候这儿是空的，四个动作全挂在
        # work_order:update 那个权限点上，等于上面那两个洞都敞着 ——
        # 而"谁能调这个接口"在路由层就过掉了，service 里一行判断都没有。
        # 当时是照 business-rules.md 做了个"取宽"的决定（那份文档的权限表和
        # 正文自相矛盾：表格说 ENGINEER 只有 update，正文说工程师可以驳回），
        # 后来在 architecture.md 里看到上面那两句原话，才知道挑错了。
        if not is_manager(operator):
            if action not in ENGINEER_ALLOWED_ACTIONS:
                raise PermissionDeniedException(
                    f"Role cannot run {action.value} on a work order."
                )
            if work_order.assigned_to_id != operator.id:
                raise PermissionDeniedException(
                    f"Work order {work_order_id} is not assigned to you."
                )

        # 闸门三：状态。还是 18a 那张允许表说了算，这里不重复写规则
        current_status = WorkOrderStatus(work_order.status)
        target_status = resolve_transition(current_status, action)

        # 只有"完成"要额外写一列完工日期，别的动作这是个空 dict
        extra_values: dict[str, object] = {}
        if completion_date is not None:
            extra_values["completion_date"] = completion_date

        # 带条件的 UPDATE：只有当前状态还是我刚才读到的那一格时才生效。
        # 返回的是"真改了几行"，0 就说明有人在我判完之后先动手了
        affected = self.work_orders.apply_transition(
            work_order_id=work_order.id,
            from_status=current_status.value,
            to_status=target_status.value,
            extra_values=extra_values,
        )
        if affected == 0:
            # 走到这儿说明白忙一场：判断做得没错，但那份判断已经过期了。
            # 好在流水和日志都还没写，直接抛出去，事务回滚，不留半截数据
            raise ConcurrentUpdateException(
                f"Work order {work_order_id} was changed by someone else, "
                f"reload and try again."
            )

        # UPDATE 是绕过 ORM 发的（synchronize_session=False），session 里那份对象
        # 还停在旧状态。下面的流水要用 work_order.id，最后 work_order_detail
        # 还要读它一堆列，所以先刷新一次，别让后面的人拿到过期数据
        self.db.refresh(work_order)

        # 流水里存 reason（驳回原因）。别的动作没这个值，就存 NULL。
        #
        # reason 只写流水、不写操作日志，这是故意的：
        # 操作日志管的是"谁在什么时候做了什么"，驳回原因是工单自己的业务数据。
        # 两处都存的话，将来只改一处就会不一致 —— 而这两张表的一致性没人会去查
        self.work_orders.add_status_history(
            WorkOrderStatusHistory(
                work_order_id=work_order.id,
                from_status=current_status.value,
                to_status=target_status.value,
                operator_id=operator.id,
                reason=reason,
            )
        )

        self.logs.add(
            user_id=operator.id,
            operation=f"{action.value}_WORK_ORDER",
            module="work_order",
            target_type="work_order",
            target_id=str(work_order.id),
            request_method="POST",
            request_path=request_path,
            result="SUCCESS",
            detail=f"status={current_status.value}->{target_status.value}",
            ip_address=ip_address,
        )

        # 跟前面几个接口一样，改数据 + 流水 + 日志一次性提交，不留半截
        self.db.commit()
        self.db.refresh(work_order)
        return work_order_detail(work_order)

    # ---------------------------------------------------------------
    # 下面四个是外面真正调的接口，各自只负责"传哪个动作进去"。
    # 之所以不合成一个 POST /transition 让前端传 action：那样前端就得多知道一件事
    # （动作名怎么写），而且权限点也没法按动作分开了。
    # 拆成四条路径，前端调用的时候意图是明的。
    # ---------------------------------------------------------------

    def start_work_order(
        self,
        *,
        work_order_id: int,
        operator: User,
        request_path: str,
        ip_address: str | None,
    ) -> WorkOrderDetail:
        """ASSIGNED -> IN_PROGRESS。工程师接了活，开干。"""
        return self._transition(
            work_order_id=work_order_id,
            action=WorkOrderAction.START,
            operator=operator,
            request_path=request_path,
            ip_address=ip_address,
        )

    def complete_work_order(
        self,
        *,
        work_order_id: int,
        operator: User,
        request_path: str,
        ip_address: str | None,
    ) -> WorkOrderDetail:
        """IN_PROGRESS -> COMPLETED。干完了，顺手把完工日期填上。

        用 date.today() 而不是让前端传：完工日期该是服务器这边记的"记录时间"，
        前端传的话，用户手机上日期不对就会写进去一个错的日期。
        """
        return self._transition(
            work_order_id=work_order_id,
            action=WorkOrderAction.COMPLETE,
            operator=operator,
            request_path=request_path,
            ip_address=ip_address,
            completion_date=date.today(),
        )

    def close_work_order(
        self,
        *,
        work_order_id: int,
        operator: User,
        request_path: str,
        ip_address: str | None,
    ) -> WorkOrderDetail:
        """COMPLETED -> CLOSED。收尾归档。到这儿这单就彻底结束了。"""
        return self._transition(
            work_order_id=work_order_id,
            action=WorkOrderAction.CLOSE,
            operator=operator,
            request_path=request_path,
            ip_address=ip_address,
        )

    def reject_work_order(
        self,
        *,
        work_order_id: int,
        reason: str,
        operator: User,
        request_path: str,
        ip_address: str | None,
    ) -> WorkOrderDetail:
        """PENDING / ASSIGNED -> REJECTED。这单做不了，退回去。

        reason 必填，在 schema 那一层就挡了（空串直接 422）。

        注意这里不清 assigned_to_id：单子被驳回的时候，它还留着"曾经派给过谁"——
        那是历史事实，抹掉就查不出是谁退回的了。要查是谁驳回的看流水，
        要查原本派给谁看这一列。
        """
        return self._transition(
            work_order_id=work_order_id,
            action=WorkOrderAction.REJECT,
            operator=operator,
            request_path=request_path,
            ip_address=ip_address,
            reason=reason,
        )

    def add_processing_record(
        self,
        *,
        work_order_id: int,
        content: str,
        operator: User,
        request_path: str,
        ip_address: str | None,
    ) -> WorkOrderRecordItem:
        """在工单下面留一条处理记录，说白了就是写句备注。

        两道闸门：单子得在，而且得是平台自己的单。跟前面几个写操作一个口径 ——
        "双数据源隔离"这条线是所有写操作的入口检查，不在这儿破例。

        刻意没做的是三件事，都不是漏了：

        1. 没判状态。处理记录不是流转，它不改状态。已经关闭的单再写一条
           "客户又打电话来问"，这是合理的；拿状态卡它，只会让人在真需要的时候
           反倒记不下来。
        2. 没写状态流水。流水记的是"状态怎么变的"，这条备注没让状态动。
           往里塞一行 from_status 和 to_status 一样的，那才是把那张表搞脏了。
        3. 没动 work_orders 那一行，所以 updated_at 不会因为写备注而变。
           这是对的：备注不是对工单本身的修改。哪天要拿 updated_at 排序
           "最近有动静的单"，得想清楚要不要算上备注 —— 到时候再说。
        """
        work_order = self.work_orders.get_by_id(work_order_id)
        if work_order is None:
            raise NotFoundException(f"Work order {work_order_id} not found.")

        if work_order.data_source != DATA_SOURCE_PLATFORM:
            raise PermissionDeniedException(
                f"Work order {work_order_id} is imported public data, "
                f"cannot add records."
            )

        record = WorkOrderProcessingRecord(
            work_order_id=work_order.id,
            user_id=operator.id,
            content=content,
        )
        self.work_orders.add_processing_record(record)

        # flush 一下自增主键才拿得到 —— 下面那条操作日志要拿它写清"加的是哪一条"
        self.db.flush()

        self.logs.add(
            user_id=operator.id,
            operation="ADD_WORK_ORDER_RECORD",
            module="work_order",
            target_type="work_order",
            target_id=str(work_order.id),
            request_method="POST",
            request_path=request_path,
            result="SUCCESS",
            # 日志的 detail 写的是"加了哪一条"，不是状态。备注的内容不往这儿抄 ——
            # 想看成什么内容直接查记录表，抄一份到日志里早晚两边不一致
            detail=f"record_id={record.id}",
            ip_address=ip_address,
        )

        # 记录 + 日志一起提交，跟前面几个写接口一个规矩
        self.db.commit()

        # created_at 是数据库 server_default 生成的，提交之后 ORM 里那份还是旧的
        self.db.refresh(record)
        return WorkOrderRecordItem(
            id=record.id,
            work_order_id=record.work_order_id,
            user_id=record.user_id,
            content=record.content,
            created_at=record.created_at,
        )
