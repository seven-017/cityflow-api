from sqlalchemy.orm import Session

from app.core.cache import get_dashboard_cache
from app.core.config import get_settings
from app.core.work_order_status import WorkOrderStatus
from app.repositories.assets import AssetRepository
from app.repositories.labor import LaborRepository
from app.repositories.transactions import TransactionRepository
from app.repositories.work_orders import WorkOrderRepository
from app.schemas.dashboard import (
    AssetTypeDistribution,
    DashboardCharts,
    DashboardMetrics,
    DashboardOverview,
    HighMaintenanceAsset,
    LaborTrendPoint,
    RecentWorkOrder,
    ResolutionSummary,
    StatusDistribution,
    TransactionTrendPoint,
    WorkOrderTrendPoint,
    WorkTypeDistribution,
)

# 缓存的 key。
#
# /dashboard/overview 不带任何参数，所以一个固定的 key 就够，不用像别处那样
# 把查询条件拼进 key 里。图表和指标汇总一起算、一起失效、TTL 也一样，
# 共用一个 key 正合适 —— 它们本来就是同一个响应的两半。
DASHBOARD_OVERVIEW_KEY = "dashboard:overview"

# 高维护资产榜取前几名。
#
# 10 这个数没有性能含义：第一步（按 asset_id 分组）353 ms 跟 limit 无关，
# 第二步（按主键查名字）10 条是 0.4 ms，取 20 条也差不到哪去。
# 它纯粹是"页面上一个榜放得下几条"。写在这儿而不是当字面量用，
# 是为了跟探针量性能时用的那个数保持一致 ——
# 这样注释里引用的那些数字，前提条件是明确的。
HIGH_MAINTENANCE_LIMIT = 10

# 最近工单列表取几条。理由同上：0.5 ms 的查询，条数不影响性能，
# 就是个页面容量问题。
RECENT_WORK_ORDER_LIMIT = 10


class DashboardService:
    """Dashboard 的聚合。这是整个项目里唯一一个"跑一次要好几秒"的读接口。

    它跟别的 service 有两处不一样，都说一声免得看着像破例：

    1. 它同时用四个仓储（资产 / 工单 / 工时 / 交易），不是"一个 service 对一张表"。
       这不算破规矩 —— 仓储是按表切的，service 的职责就是把几张表的数据拼成
       页面要的形状。前面 labor service 也同时用了 labor 和 work_orders 两个仓储，
       同一回事，只是这儿要拼的表多一些。

    2. 它是唯一走缓存的读接口。为什么是它、为什么不上 Redis，
       整段论证写在 core/cache.py 的「为什么不上 Redis」里，这儿不重复。
    """

    def __init__(self, db: Session) -> None:
        self.db = db
        self.assets = AssetRepository(db)
        self.work_orders = WorkOrderRepository(db)
        self.labor = LaborRepository(db)
        self.transactions = TransactionRepository(db)

    def get_overview(self) -> DashboardOverview:
        """拿 Dashboard 首页要的数据。缓存命中就直接返回，一下数据库都不碰。

        缓存的是整个 DashboardOverview，不是把十个指标一个个分别缓存。
        理由是这几个数"同生共死"：一次请求里一起算出来、写操作一来一起失效、
        TTL 也是同一个。拆成十个 key 只会多十次加解锁，换不来任何东西。

        get_or_compute 的第二个参数传的是 self._compute_overview 这个方法本身 ——
        注意它只有在缓存没命中时才会被调用。所以"缓存命中不查库"这件事，
        是靠这个传参方式保证的，不是靠哪句 if。
        验收脚本里验的就是这一点：第二次请求期间捕获到的 SQL 应该是 0 条。
        """
        cache = get_dashboard_cache()
        return cache.get_or_compute(DASHBOARD_OVERVIEW_KEY, self._compute_overview)

    def _compute_overview(self) -> DashboardOverview:
        """真去查库的那一份。只有缓存没命中时才会跑到这儿。

        下面每个数都是当场搬成 int / Decimal / date 的，谁都没把 ORM 对象塞进去
        —— 这一点是必须的，不是顺手写的：
        缓存的命比请求的 session 长得多（5 分钟 vs 一个请求）。要是缓存里装着
        ORM 对象，下一个请求取出来的时候它绑的 session 早关了，
        读属性直接 DetachedInstanceError；更阴的一种是它绑的还是同一个 session、
        读出来是 identity map 里那份陈旧数据 —— 不报错，但数是旧的。
        所以这个函数"出了门就跟数据库没关系"，这一点得守住。

        还有：返回的这个对象是缓存里那一份，会同时发给好几个请求。
        谁都别去改它。真有人需要拿它改了再返回，自己 copy 一份。

        冷启动要多久：指标汇总那五个聚合约 5.96 秒
        （分项表在 schemas/dashboard.py 的 DashboardMetrics 里），
        九个图表约 5.0 秒（最贵的是 Labor 趋势 3.08 秒），
        加起来 11 秒这个量级。这就是为什么这个接口必须缓存 ——
        11 秒的首页，没人会等第二次。
        （两个数不是同一批量的，所以只能说量级。真实感受是"第一次点开
        要等十多秒，之后五分钟内都是 30 毫秒"。）

        两个半部分合在一个函数里算、一起返回，不拆成两个缓存项：
        它们本来就是同一个响应的两半，拆开只会多一次缓存查找、
        多一次"一半新一半旧"的可能。
        """
        counts = self.work_orders.count_by_status_group()
        totals = self.labor.totals()
        metrics = DashboardMetrics(
            asset_count=self.assets.count_assets(),
            work_order_count=counts.total,
            unfinished_work_order_count=counts.unfinished,
            finished_work_order_count=counts.finished,
            rejected_work_order_count=counts.rejected,
            labor_record_count=totals.record_count,
            labor_total_hours=totals.total_hours,
            labor_total_cost=totals.total_cost,
            transaction_count=self.transactions.count_transactions(),
            transaction_detail_count=self.transactions.count_transaction_details(),
        )
        return DashboardOverview(metrics=metrics, charts=self._compute_charts())

    def _compute_charts(self) -> DashboardCharts:
        """九个图表的数据。跟 _compute_overview 一样，只有缓存没命中才跑到这儿。

        九个查询是「顺序」跑的，没有开线程。想过要不要并发，最后没做，
        三条理由：
        1. 这套东西是缓存住的，5 分钟才算一次。并发省下的那几秒
           摊不到 5 分钟里，看不出区别。
        2. 一开线程池，出问题的时候要分辨"是哪个查询挂了"就更费劲，
           而不开的话报错栈直接指到出问题那一行。
        3. 架构文档里那句"最多 2 个并发聚合"说的是「多个请求之间」的限制
           （缓存刚过期时十个请求一起涌进来那种），不是"单个请求内部要开线程"。
           别把这两件事读成一件事。

        关于"补零"这个动作，九个图里只有状态分布做了，理由写在下面第一节。
        """
        settings = get_settings()
        # 三个趋势图 + 平均处理周期共用一个窗口，来源只有 config 一个
        months = settings.dashboard_trend_window_months

        # ---- 1. 状态分布 ----
        # 按状态机的定义顺序把六个状态全列出来，库里没有的填 0。
        #
        # 为什么要补：库里现在只有三个状态有数据（COMPLETED 2065995 /
        # REJECTED 129662 / PENDING 25196），另外三个 ASSIGNED / IN_PROGRESS /
        # CLOSED 一条都没有 —— 它们是平台自己流转才会产生的状态，
        # 官方导入的老数据里不存在。不补零的话图上只有三根柱子，
        # 看的人会以为"这个系统只有三个状态"，把"暂时没有数据"
        # 读成了"没有这个概念"。
        #
        # 顺序用枚举定义顺序（也就是状态机主干往前走的那条线），不是按条数排。
        # 按条数排看着热闹，但等哪天有人流转出一张 ASSIGNED，
        # 那根新柱子会插到中间去，把其他柱子的位置全挤乱 ——
        # 同一张图两天长得不一样，看着像数据出问题了。
        counted_by_status = {
            row.status: row.work_order_count
            for row in self.work_orders.count_by_status()
        }
        status_distribution = [
            StatusDistribution(
                status=status.value,
                work_order_count=counted_by_status.get(status.value, 0),
            )
            for status in WorkOrderStatus
        ]

        # ---- 2. 工单类型分布 ----
        # 这个不补零：work_type 是自由文本列，没有权威清单。
        # 完整的理由写在 schemas/dashboard.py 的 AssetTypeDistribution 上。
        work_type_distribution = [
            WorkTypeDistribution(
                work_type=row.work_type,
                work_order_count=row.work_order_count,
            )
            for row in self.work_orders.count_by_work_type()
        ]

        # ---- 3. 资产类型分布 ----
        # 也不补零，理由同上。含一个值是 '*' 的脏数据（1 条），照发。
        asset_type_distribution = [
            AssetTypeDistribution(
                asset_type=row.asset_type,
                asset_count=row.asset_count,
            )
            for row in self.assets.count_by_type()
        ]

        # ---- 4. 高维护资产（两步）----
        # 第一步拿 top10 的 asset_id + 工单数，第二步拿这 10 个 id 查资产名。
        # 为什么不一条 JOIN 写完，省在哪里 —— 写在仓储方法的注释里（省 15.9 倍）。
        ranking = self.work_orders.list_high_maintenance_assets(HIGH_MAINTENANCE_LIMIT)
        assets_by_id = {
            asset.id: asset
            for asset in self.assets.list_by_ids([row.asset_id for row in ranking])
        }
        # 这里按 ranking 的顺序拼，不遍历 assets_by_id ——
        # 那个字典的顺序是数据库给的（IN 查询不保证按传入顺序返回），
        # 而榜单的名次是重要信息，不能让它取决于数据库今天心情好不好。
        # 所以这一步不是"顺手写成列表推导"，是必须的重排。
        high_maintenance_assets = [
            HighMaintenanceAsset(
                asset_id=row.asset_id,
                # asset_type 在模型上可空，直接透传 null，不兜成空字符串 ——
                # 空字符串和"没有类型"是两件事，兜一下就把它们混成一件了。
                # （这里原来写的是 `or ""`，改掉了：那是在替前端做决定。）
                asset_type=assets_by_id[row.asset_id].asset_type,
                description=assets_by_id[row.asset_id].description,
                work_order_count=row.work_order_count,
            )
            for row in ranking
        ]

        # ---- 5. 平均处理周期 ----
        # 窗口那个数字必须跟着返回，不然 22.04 天这个数没有意义
        # （全历史是 50.72 天，同一个指标差一倍多）——
        # 理由写在 schemas/dashboard.py 的 ResolutionSummary 上。
        resolution = self.work_orders.resolution_stats(months)
        resolution_summary = ResolutionSummary(
            average_days=resolution.average_days,
            sample_count=resolution.sample_count,
            window_months=months,
        )

        # ---- 6 / 7 / 8. 三个趋势图 ----
        # 共用同一个窗口。三张图挨着摆在页面上，窗口不一致的话
        # 看的人会拿它们互相对比 —— 那比的是三个不同时间段的数，得出的结论是错的。
        work_order_trend = [
            WorkOrderTrendPoint(
                month=row.month,
                work_order_count=row.work_order_count,
            )
            for row in self.work_orders.trend_by_month(months)
        ]
        labor_trend = [
            LaborTrendPoint(
                month=row.month,
                record_count=row.record_count,
                total_hours=row.total_hours,
                total_cost=row.total_cost,
            )
            for row in self.labor.trend_by_month(months)
        ]
        transaction_trend = [
            TransactionTrendPoint(
                month=row.month,
                transaction_count=row.transaction_count,
            )
            for row in self.transactions.trend_by_month(months)
        ]

        # ---- 9. 最近工单 ----
        # 这里没有 import work_orders 那个 service 来复用它的映射逻辑。
        # 不是嫌麻烦，是 service 之间不许互引（README 里有一节专门说这个）——
        # 那个映射是为"分页列表"设计的（带游标、带一堆字段），
        # 这里只要 7 个字段，自己写三行比跨 service 调一次清楚得多。
        recent_work_orders = [
            RecentWorkOrder(
                id=work_order.id,
                status=work_order.status,
                description=work_order.description,
                work_type=work_order.work_type,
                request_date=work_order.request_date,
                completion_date=work_order.completion_date,
                asset_id=work_order.asset_id,
            )
            for work_order in self.work_orders.list_recent(RECENT_WORK_ORDER_LIMIT)
        ]

        return DashboardCharts(
            status_distribution=status_distribution,
            work_type_distribution=work_type_distribution,
            asset_type_distribution=asset_type_distribution,
            high_maintenance_assets=high_maintenance_assets,
            resolution_summary=resolution_summary,
            work_order_trend=work_order_trend,
            labor_trend=labor_trend,
            transaction_trend=transaction_trend,
            recent_work_orders=recent_work_orders,
        )
