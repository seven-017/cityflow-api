import secrets
from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy.orm import Session

from app.core.data_sources import DataSource
from app.core.exceptions import NotFoundException
from app.models import User, WorkOrderLabor
from app.repositories.labor import LaborRepository
from app.repositories.operation_logs import OperationLogRepository
from app.repositories.work_orders import WorkOrderRepository
from app.schemas.common import CursorMeta
from app.schemas.labor import LaborCreateRequest, LaborSummary


# 平台自己录的工时编号：PL- 后面跟 12 位十六进制。
#
# 为什么不复用 work_orders 那边那个 PF- 的开头：因为 labor 表里会同时出现两个号 ——
# 它自己的 source_record_id，和它挂的那张工单的 source_work_order_record_id。
# 两个都是 PF- 开头的话，排障时看到一行两个 PF- 号，得靠列名区分是哪一个，
# 一个看错列就查错了方向。前缀分开，一眼能看出"这个号是工单还是工时"。
#
# 为什么不把"生成平台编号"抽成一个公共函数：两个调用方要的前缀不一样，
# 抽出来共用部分只剩 secrets.token_hex(6) 这一句，代价却是要动
# services/work_orders.py 那个已经验收过好几轮的模块。为一句代码不值当。
# 真出现第三个调用方再抽，那时候三个前缀摆一起才看得出该怎么抽。
LABOR_SOURCE_RECORD_ID_PREFIX = "PL-"


def generate_labor_source_record_id() -> str:
    """生成一个平台工时号，长这样：PL-8c1d0f7a24be。

    为什么用随机串不用自增序号，完整论证在 services/work_orders.py 的
    generate_source_record_id 上面（大意：自增要"先查再算"，两个人同时创建
    会算出同一个号、撞唯一约束报 500，而且只有真并发才复现）。
    同一个道理不写第二遍。
    """
    return LABOR_SOURCE_RECORD_ID_PREFIX + secrets.token_hex(6)


def labor_summary(row: WorkOrderLabor) -> LaborSummary:
    """把一条 WorkOrderLabor 搬成 LaborSummary。

    第四个搬运函数了（asset_summary / asset_detail / work_order_summary /
    work_order_detail / 这个）。规矩跟前几个一样：ORM 对象不能直接往外扔，
    得把要发的字段一个个搬过来。
    """
    return LaborSummary(
        id=row.id,
        source_record_id=row.source_record_id,
        data_source=row.data_source,
        work_order_id=row.work_order_id,
        source_work_order_record_id=row.source_work_order_record_id,
        action=row.action,
        work_date=row.work_date,
        trade=row.trade,
        operation_type=row.operation_type,
        hours=row.hours,
        rate=row.rate,
        cost=row.cost,
    )


class LaborService:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.labor = LaborRepository(db)
        # 录工时得先确认那张工单真存在，所以这儿要一个工单仓储。
        # repository 是按表切的，一个 service 组合几个都行 ——
        # system / work_orders 那边也是这么用的
        self.work_orders = WorkOrderRepository(db)
        self.logs = OperationLogRepository(db)

    def list_labor(
        self,
        *,
        after_id: int | None,
        limit: int,
        work_order_id: int | None = None,
    ) -> tuple[list[LaborSummary], CursorMeta]:
        """翻页查工时。

        跟 assets / work_orders 两个列表一个套路：仓库层多要一行探路，
        这儿看它到底有没有多给，多出来那行裁掉。

        没做的事，明说，免得以后有人以为是漏了：

        1. 没有 total。理由跟另两个列表完全一样，写在 schemas/common.py 的
           CursorMeta 上 —— 320 万行上算一次 COUNT 是纯浪费，而且游标分页
           本来也跳不了页，那个数字没人会用。

        2. 工单不存在时不报 404。传个不存在的 work_order_id 就是查到空列表 ——
           这是列表接口该有的行为，不是详情接口。前端拿空列表显示"暂无记录"，
           比甩个 404 让它单独处理一条分支要简单。而且"这单有没有工时"
           和"这单存不存在"是两回事，列表接口不该替详情接口回答第二个问题。

        3. 没做 keyword / trade / operation_type / asset_id / date_from / date_to
           这几个文档列出来的过滤条件。分两种说：

           没索引撑着的（keyword、date_from/date_to）——
           320 万行上做 LIKE '%xx%' 或者日期范围全扫，快不了。
           真要做，得先把索引加上、量过分页代价再说，不能先写接口后想性能。

           结构上就做不了的（asset_id）——
           文档 api.md 里 GET /labor 的参数列了 asset_id，但 work_order_labor
           这张表上压根没有 asset_id 这一列（表结构是从 AMPS 原始字段映射过来的，
           那些字段里就没有资产）。要按资产过滤只能 JOIN work_orders（222 万行）
           再拿 w.asset_id 比，那是一次跨 320 万和 222 万行的连接。
           而且资产那边要的是"统计"不是"明细"（api.md 里资产详情返回的是
           Labor 统计），统计该怎么算属于聚合接口的事，不该硬塞进列表。

           这就能看出一件事：文档和表结构不是永远对得上的。
           文档写参数的时候想的是"用户可能想按什么筛"，表结构说的是"手上有什么"。
           两边打架的时候，先看能不能做（asset_id 不能），再看值不值得做（keyword 不值），
           而不是照着文档把参数名抄一遍然后留个空实现。
        """
        # 仓库层故意多要了一行，这里看它到底有没有多给
        rows = self.labor.list_labor(
            after_id=after_id, limit=limit, work_order_id=work_order_id
        )
        has_more = len(rows) > limit
        # 多出来那一条只是用来探测"还有没有下一页"的，不能发给前端
        page_rows = rows[:limit]
        # 下一页从哪开始？就是这一页最后那条的 id。
        # has_more 为假的时候给 None，让前端一眼看出到底了
        next_cursor = page_rows[-1].id if has_more and page_rows else None
        items = [labor_summary(r) for r in page_rows]
        return items, CursorMeta(
            limit=limit,
            next_cursor=next_cursor,
            has_more=has_more,
        )

    def create_labor(
        self,
        *,
        payload: LaborCreateRequest,
        operator: User,
        request_path: str,
        ip_address: str | None,
    ) -> LaborSummary:
        """平台自己录一条工时。

        落库的有两样东西：工时本身 + 一条操作日志。
        日志不能省 —— 工单那边"至少记录"那张表里虽然没有"创建工时"这一项，
        但那是下限不是上限，而且写操作留痕是这个项目从头到尾的做法：
        分派、流转、加处理记录都记了。ENGINEER 是能自己建工时的角色，
        没日志的话"这条工时是谁记的"事后就查不到了。

        有意的两处放松，写清楚免得以后有人以为是漏了：

        1. 不检查工单的 data_source，也就是允许往 REAL_PUBLIC（官方导入）
           的工单上挂工时。这不是放松 —— 文档里"真实历史工单可以用于"那一节
           明确列了「Labor 和 Transactions 关联」，也就是说给历史单记工时
           正是它允许的用法。真正不许动的是"改历史单本身"（状态、描述、分派）。
           而且现实里主要场景就是这个：我修了一张历史单，把花的时间记上去。

        2. 不检查"这张单是不是派给我的"。文档里那句「Engineer 只能操作
           分配给自己的工单」说的是工单操作（分派、流转、处理记录），
           录工时是另一件事。而且加了这道闸门会直接让功能不可用 ——
           REAL_PUBLIC 的工单根本没有归属信息（AMPS 数据里没有这一列，
           导入时也没映射），ENGINEER 就永远给历史单记不了工时了。
           ⇒ 判断是：这一版不做归属检查。如果将来真出现"跨人记工时"的滥用，
             该加；但加的前提是先解决"真实工单没有归属"这个问题。

        没做的事，也说清楚：

        3. 不校验 trade / operation_type / action 的取值是不是那 97 / 2 / 19 种之一。
           它们是 AMPS 的编码，文档里没给码表（不知道 '10' 代表什么），
           我们手上也没有一份可信的白名单 —— 凭库里现有的值现攒一份，
           等于把"碰巧出现过"当成"合法"，那是伪校验。所以这一版只卡长度。
           真要做，得先有码表。这跟 sla_status 阈值是同一类悬案。

        4. 不写状态流水。工时不是状态机的输入，改不了工单的状态，
           所以没有 from_status / to_status 可言。
        """
        # 工单不存在就 404。数据库层面 work_order_id 那一列有外键，
        # 但外键管的是"工单被删了怎么办"（ondelete=SET NULL），
        # 不是"传了个不存在的工单号怎么办" —— 后者该在业务层挡，
        # 挡在这里才能给出人看得懂的错误，而不是一个 IntegrityError
        work_order = self.work_orders.get_by_id(payload.work_order_id)
        if work_order is None:
            raise NotFoundException(f"Work order {payload.work_order_id} not found.")

        # cost 由服务端算出来，不收调用方的值。理由写在 LaborCreateRequest 上。
        # 两处细节要说：
        #   hours 是 Numeric(12,2)、rate 是 Numeric(18,4)，
        #   两个 Decimal 相乘标度会变成 6 位小数，而 cost 那一列是 Numeric(18,2) ——
        #   不 quantize 的话由数据库去截，截多少它说了算。
        #   舍入模式显式写 HALF_UP：Python 的默认是 HALF_EVEN（银行家舍入），
        #   0.125 会舍成 0.12 而不是 0.13，跟大多数人对"四舍五入"的预期不一样。
        #   钱这种东西，宁可写明白。
        cost = (payload.hours * payload.rate).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )

        labor = WorkOrderLabor(
            source_record_id=generate_labor_source_record_id(),
            # 必须显式写。这一列在模型上有默认值 REAL_PUBLIC，
            # 忘了写的话数据库会默默把平台自己录的工时标成"官方数据"，
            # 然后就变成一条谁都不许改的记录 —— 而且不报错。理由见 DataSource
            data_source=DataSource.SYNTHETIC_PLATFORM,
            work_order_id=work_order.id,
            # 不填就是今天。允许补录过去的日期
            work_date=payload.work_date or date.today(),
            trade=payload.trade,
            operation_type=payload.operation_type,
            action=payload.action,
            hours=payload.hours,
            rate=payload.rate,
            cost=cost,
            # 录入时刻。跟工单那边 created_at 的基准对齐，都用这台机器的本地时间；
            # 将来应用和数据库拆到两台机器、时区还不一样的话，这儿得改成取库的时间
            entered_at=datetime.now(),
        )
        self.labor.add(labor)

        # flush 才拿得到自增主键 —— 下面那条日志的 target_id 要用
        # （flush 只是把 SQL 发出去，还没提交，出错照样一起回滚）
        self.db.flush()

        self.logs.add(
            user_id=operator.id,
            operation="CREATE_LABOR",
            module="labor",
            target_type="labor",
            target_id=str(labor.id),
            request_method="POST",
            request_path=request_path,
            result="SUCCESS",
            # 日志里带上工时和金额，审计时能直接看出"记了多少、多少钱"，
            # 不用再回表查那条工时的 id
            detail=(
                f"source_record_id={labor.source_record_id}, "
                f"work_order_id={labor.work_order_id}, "
                f"hours={labor.hours}, cost={labor.cost}"
            ),
            ip_address=ip_address,
        )

        # 两件事一起提交。上面任何一步抛异常，add 过的都还在 session 里没落库，
        # 异常冒上去之后 session 会被关掉，等于整批回滚 ——
        # 不会出现"工时建好了但日志没写"这种半截数据
        self.db.commit()

        # created_at / updated_at 是数据库 server_default 生成的，
        # 提交之后 ORM 手里那份还是旧的，刷一下再搬给 schema
        self.db.refresh(labor)
        return labor_summary(labor)
