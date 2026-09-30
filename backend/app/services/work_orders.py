import secrets
from datetime import date

from sqlalchemy.orm import Session

from app.core.exceptions import NotFoundException
from app.core.work_order_status import WorkOrderStatus
from app.models import User, WorkOrder, WorkOrderStatusHistory
from app.repositories.operation_logs import OperationLogRepository
from app.repositories.work_orders import WorkOrderRepository
from app.schemas.common import CursorMeta
from app.schemas.work_orders import (
    WorkOrderCreateRequest,
    WorkOrderDetail,
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
        source_notes=work_order.source_notes,
        duration=work_order.duration,
        job_type=work_order.job_type,
        source_update_count=work_order.source_update_count,
        created_at=work_order.created_at,
        updated_at=work_order.updated_at,
    )


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


class WorkOrderService:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.work_orders = WorkOrderRepository(db)
        self.logs = OperationLogRepository(db)

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

        现在没带，原因是那两张表实测都是 0 行 —— 官方导入的数据里
        一条流转记录都没有（那是平台自己流转时才写的）。
        给一个永远是空的数组留个字段位，没意义。
        第 18 步做完状态机，这两张表才有数据，到那时候再加。
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

        另外这一版故意没做 sla_deadline（优先级对应的处理时限）。
        它是纯计算，跟状态机没关系，塞在这儿只会让这个方法变胖。
        等那几条流转都做完，再单独收拾它。
        """
        work_order = WorkOrder(
            source_record_id=generate_source_record_id(),
            # 双数据源隔离的落点。官方导入的那些是 REAL_PUBLIC（只读，不许动），
            # 平台自己录的走 SYNTHETIC_PLATFORM。这一列决定了后面分派、流转、
            # 加处理记录时第一道闸门放不放行 —— 写错了后面全被挡
            data_source="SYNTHETIC_PLATFORM",
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
