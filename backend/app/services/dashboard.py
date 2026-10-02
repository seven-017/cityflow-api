from sqlalchemy.orm import Session

from app.core.cache import get_dashboard_cache
from app.repositories.assets import AssetRepository
from app.repositories.labor import LaborRepository
from app.repositories.transactions import TransactionRepository
from app.repositories.work_orders import WorkOrderRepository
from app.schemas.dashboard import DashboardMetrics, DashboardOverview

# 缓存的 key。
#
# /dashboard/overview 不带任何参数，所以一个固定的 key 就够，不用像别处那样
# 把查询条件拼进 key 里。20b 加图表数据也是往同一个响应里加，
# 它们一起算、一起失效、TTL 也一样，共用一个 key 正合适。
DASHBOARD_OVERVIEW_KEY = "dashboard:overview"


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

        下面每个数都是当场搬成 int / Decimal 的，谁都没把 ORM 对象塞进去 ——
        这一点是必须的，不是顺手写的：
        缓存的命比请求的 session 长得多（5 分钟 vs 一个请求）。要是缓存里装着
        ORM 对象，下一个请求取出来的时候它绑的 session 早关了，
        读属性直接 DetachedInstanceError；更阴的一种是它绑的还是同一个 session、
        读出来是 identity map 里那份陈旧数据 —— 不报错，但数是旧的。
        所以这个函数"出了门就跟数据库没关系"，这一点得守住。

        还有：返回的这个对象是缓存里那一份，会同时发给好几个请求。
        谁都别去改它。真有人需要拿它改了再返回，自己 copy 一份。
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
        return DashboardOverview(metrics=metrics)
