from decimal import Decimal
from typing import NamedTuple

from sqlalchemy import case, func, select, text, update
from sqlalchemy.orm import Session

from app.core.work_order_status import (
    FINISHED_STATUSES,
    REJECTED_STATUSES,
    UNFINISHED_STATUSES,
)
from app.models import WorkOrder, WorkOrderProcessingRecord, WorkOrderStatusHistory
from app.repositories.sql_helpers import trend_window


class WorkOrderStatusCounts(NamedTuple):
    """一次聚合查回来的四个数。

    用 NamedTuple 而不是裸元组，理由很实在：这是四个同类型的 int，
    拆包时顺序错一个，编译器不会吭声，界面上却会显示"未完结 2065995"这种鬼话。
    带上名字之后调用方写 total, unfinished, finished, rejected = ...，
    一眼能看出对不对（跟下面那几处 tuple 返回值不一样，
    那些是两三个不同类型的值，混不了）。
    """

    total: int
    unfinished: int
    finished: int
    rejected: int


class ResolutionStats(NamedTuple):
    """平均处理周期那两个数。

    average_days 是"建单到完工隔了多少天"的平均值，sample_count 是拿多少张单算的。
    这两个也得带名字：一个 Decimal 一个 int，都是数字，拆反了同样看不出来
    （跟上面四个 int 是同一种风险，所以待遇一样）。

    为什么非要带上 sample_count：22.0 天这个数，是拿 78520 张单算出来的，
    还是拿 3 张单算出来的，含义差得远。数字本身不会告诉你这件事。
    """

    average_days: Decimal | None
    sample_count: int


class StatusCount(NamedTuple):
    """状态分布图的一行：一个状态，加它名下的单数。

    下面这几个图表的行数据都是一行"分组列 + 条数"，为什么还要正经写个
    NamedTuple、不直接甩裸元组：service 那边要拿它拼
    StatusDistribution(status=..., work_order_count=...)。裸元组的话
    那边就得写 row[0] / row[1]，读的人得翻回这儿数第几个是哪列。
    带名字之后，出错只可能是拼错名字，而拼错名字会当场报错，不是静默取错值。
    """

    status: str
    work_order_count: int


class WorkTypeCount(NamedTuple):
    """工单类型分布图的一行。字段含义同 StatusCount，分组列换成 work_type。"""

    work_type: str
    work_order_count: int


class AssetWorkOrderCount(NamedTuple):
    """高维护资产榜的一行。

    注意这里只有 asset_id，没有资产名。名字是第二步才查的
    （AssetsRepository.list_by_ids），为什么拆两步写在
    list_high_maintenance_assets 的注释里。
    """

    asset_id: int
    work_order_count: int


class MonthlyWorkOrderCount(NamedTuple):
    """工单趋势图的一个点：某个月 + 那个月建了多少单。

    month 是 'YYYY-MM' 这样的字符串，不是 date 对象。它本来就是
    SQL 那边 DATE_FORMAT 出来给横轴当标签用的，转成 date 再转回来纯属白干，
    而且前端拿到 date 还得自己格式化一遍。
    """

    month: str
    work_order_count: int


class WorkOrderRepository:
    """工单表的查询。

    跟 AssetRepository 基本是一个模子：游标分页 + 按主键查单条 + 数总数。
    但还是有区别，下面一条条说。

    这里千万别忘了：WorkOrder 模型上有两个指向 users 的 relationship。
    它们原来是 lazy="joined"，也就是每次查工单都会白搭两次 LEFT JOIN。
    实测那条 JOIN 会让优化器放弃主键顺序、改用 filesort，
    一个 LIMIT 21 的查询从 2.5 ms 变成 16614 ms。
    2026-09-29 已经把模型上那两处改了（细节写在 models/data.py 的注释里）。
    以后再往这张表加 relationship，注意同样的事别再犯一次。
    """

    def __init__(self, db: Session) -> None:
        self.db = db

    def list_work_orders(self, *, after_id: int | None, limit: int) -> list[WorkOrder]:
        """按 id 往后翻，一次取 limit 条（其实会多要一条，跟 assets 一样）。

        工单表 222 万行，比 assets 大 15 倍，所以分页这儿没有任何理由用 OFFSET。
        第 15 步在 assets 上量过：OFFSET 220 万行要 3349 ms，换成游标 0.9 ms。
        这里直接一步到位用游标，不重复踩那个坑了。
        """
        statement = select(WorkOrder)
        if after_id is not None:
            # 不传 after_id 就是第一页
            statement = statement.where(WorkOrder.id > after_id)
        # 多要一条用来判断"后面还有没有"，多出来的那条由 service 裁掉
        statement = statement.order_by(WorkOrder.id).limit(limit + 1)
        return list(self.db.execute(statement).scalars().all())

    def get_by_id(self, work_order_id: int) -> WorkOrder | None:
        # 走主键，最多命中一行。实测 1.6 ms，跟 assets 那边一样
        statement = select(WorkOrder).where(WorkOrder.id == work_order_id)
        return self.db.execute(statement).scalar_one_or_none()

    def count_by_status_group(self) -> WorkOrderStatusCounts:
        """一次查出工单总数 + 未完结 / 已完成 / 已退回三个桶。

        为什么要一次查、不查四次：做过对照实验，不是拍的
        （2026-10-02 裸 SQL，各跑 3 次取中位数）：

            四个 COUNT 分开查
                总数 COUNT(*)                     248.7 ms
                未完结 IN (PENDING,ASSIGNED,...)   12.9 ms   type=range
                已完结 IN (COMPLETED,CLOSED)     1017.6 ms   type=range
                已退回 = 'REJECTED'                25.1 ms   type=range
                四次加起来                       1304.3 ms

            一次条件聚合（同样四个数，一条 SQL）
                1143.4 ms
                EXPLAIN: type=index key=ix_work_orders_status
                         rows=2158704 Extra=Using index

        ⇒ 1143.4 vs 1304.3，一次聚合快 1.14 倍。
        （同一天早上量过一次是 991.9 vs 1329.9，1.34 倍 —— 绝对值在抖，
        但"一次更快"这个方向两次都一样，所以结论是稳的。）

        赢的地方不在"索引用得好"，在少扫几铺：四条 SQL 要四次从头翻表，
        一条 SQL 只翻一次。那个 Extra=Using index 说明它连回表都不用，
        直接在 ix_work_orders_status 上扫完就够（count 要的 id 和筛选要的 status
        都在这棵索引里）。

        顺带记一个反直觉的数：'已完结' 那一条要 1017.6 ms，比全表扫（248.7 ms）还慢四倍。
        原因是 COMPLETED 占了 93.03% 的行 —— 走索引查一个"几乎每行都满足"的条件，
        等于随机跳着读全表，还不如老老实实从头顺序读回去。
        索引不是越多越好用，选择性别太差才是关键。

        还有个坑得记着：EXPLAIN 里 rows=2158704 是估算值，不是实际扫了多少行，
        别拿它当耗时看（这个数在 assets 那边也写了一次，因为老有人忘）。

        这儿没用 FORCE INDEX，跟 transactions 那边不一样。
        那边必须 FORCE 是因为 `id > 0` 这种筛不掉任何数据的条件把优化器带偏了；
        这条 SQL 上没有任何 WHERE，优化器没有可偏的地方，
        量出来的计划（走 status 索引、Using index）已经是好的了。

        SUM(...) 在空表上返回 NULL（不是 0），所以下面每个数都要过一遍 int(x or 0)。
        现在这张表 222 万行不可能空，但"不可能"跟"不会"是两回事，
        而且这种 NULL 一旦漏进去，Pydantic 那边会因为拿不到 int 直接 500。
        """
        statement = select(
            func.count(WorkOrder.id),
            # 这三个为什么写成 SUM(CASE WHEN ... THEN 1 ELSE 0 END)，
            # 而不是更短的那个 SUM(status IN (...)) —— 这里踩过一个静默错值的坑，
            # 记下来免得以后有人"顺手简化"又踩一遍：
            #
            # 一开始写的就是 func.sum(WorkOrder.status.in_(...))，SQL 编出来一字不差就是
            # SUM(status IN (...))，MySQL 也算得对（未完结 25196）。但拿回来的是 1。
            # 三个桶全是 1，而总数 2220853 是对的 —— 光看总数根本看不出问题。
            #
            # 根因在 SQLAlchemy 的返回处理，不在 SQL：func.sum() 不知道参数是布尔表达式，
            # 就照着参数的类型推断这一列是 Boolean，于是把 MySQL 算出来的 25196
            # 过了一遍 bool() 变成 True，int(True) 就是 1。
            # 换句话说，SQL 层对的、Python 层被改掉了，中间没有任何报错。
            #
            # 怎么发现的：验收脚本里有一条「未完结 + 已完成 + 已退回 = 总数」——
            # 3 ≠ 2220853，当场红。这也说明那条等式断言不是摆设。
            #
            # 修法有两种：给 SUM 套一个 cast(Integer)，或者换成 CASE。
            # 选 CASE 是因为它不依赖 MySQL"布尔当 1/0 用"这个隐式行为，
            # 类型是明摆着的整数。代价是 SQL 比原来长一点，执行计划一样是全表扫。
            func.sum(
                case((WorkOrder.status.in_(UNFINISHED_STATUSES), 1), else_=0)
            ),
            func.sum(case((WorkOrder.status.in_(FINISHED_STATUSES), 1), else_=0)),
            func.sum(case((WorkOrder.status.in_(REJECTED_STATUSES), 1), else_=0)),
        )
        total, unfinished, finished, rejected = self.db.execute(statement).one()
        return WorkOrderStatusCounts(
            total=int(total or 0),
            unfinished=int(unfinished or 0),
            finished=int(finished or 0),
            rejected=int(rejected or 0),
        )

    def count_by_status(self) -> list[StatusCount]:
        """每个状态各多少单 —— 状态分布图的数据。

        跟上面那个 count_by_status_group 是两个用途，别合到一起：
        上面那个回的是"活干完了没有"的三个桶（卡片上要的数），
        这个回的是"每个状态各多少"（图上每根柱子一根）。桶和状态是两套切法。

        2026-10-04 实测：全表 GROUP BY，591 ms。

        库里现在只有三个状态有数据（COMPLETED 2065995 / REJECTED 129662 /
        PENDING 25196），另外三个一条都没有。这不是查询写漏了 ——
        ASSIGNED / IN_PROGRESS / CLOSED 这三个官方导入的老数据里根本不存在，
        得等平台自己有人流转才会出现。所以这里就只报"库里有的"，
        把空的补成 0 是 service 的活（那边有 WorkOrderStatus 枚举，
        知道完整的六个是什么、按什么顺序排）。仓储层不该知道
        "这个图想让人看见几根柱子"，它只管回答"库里有什么"。

        排序按条数倒序，让最大的那个排在最前面。图是按状态机顺序画的，
        所以这个顺序其实用不上 —— 但它是"没有 ORDER BY 的 GROUP BY"
        在 MySQL 8 里不保证顺序的兜底，写了至少结果是确定的。
        """
        statement = (
            select(
                WorkOrder.status,
                func.count(WorkOrder.id).label("work_order_count"),
            )
            .group_by(WorkOrder.status)
            .order_by(func.count(WorkOrder.id).desc())
        )
        return [
            StatusCount(status=row.status, work_order_count=row.work_order_count)
            for row in self.db.execute(statement).all()
        ]

    def count_by_work_type(self) -> list[WorkTypeCount]:
        """工单类型分布 —— 按 work_type 分组。

        2026-10-04 实测 711 ms，回 7 种类型，不用 LIMIT：

            JOB  1840324 (82.9%) / IN 108164 / AA 100607 / PPM 98680 /
            STAT 42936 / XA 15062 / MRC 15080

        为什么不加个 LIMIT 15 兜底：work_type 这一列类型上是 String(150)
        的自由文本，但实际取值就是上面那七个码，JOB 一家占八成多。
        这种像码表的列不会长出几百种。真长出来了，那时候要加的是 LIMIT，
        不是现在先留一个 —— 留一个的话，图上会莫名其妙少几根柱子，
        而且没人知道是被截掉的。
        """
        statement = (
            select(
                WorkOrder.work_type,
                func.count(WorkOrder.id).label("work_order_count"),
            )
            .group_by(WorkOrder.work_type)
            .order_by(func.count(WorkOrder.id).desc())
        )
        return [
            WorkTypeCount(
                work_type=row.work_type,
                work_order_count=row.work_order_count,
            )
            for row in self.db.execute(statement).all()
        ]

    def list_recent(self, limit: int) -> list[WorkOrder]:
        """最近建的一批工单，给 Dashboard 右下角那个列表用。

        按 id 倒序，不按 request_date 倒序。三条理由，从硬到软：

        1. 快。2026-10-04 实测 0.5 ms，EXPLAIN 里写着
           type=index key=PRIMARY Extra=Backward index scan —— 主键索引
           本来就是按 id 排好的，倒着读就行，一次排序都不用做。
           换句话说这个查询的代价跟表有多大无关。

        2. id 唯一，排序稳定。request_date 同一天里有几千张单
           （2026-09-15 那天光 id 尾号 2789479~2789488 就是 10 张），
           按它排，同一天的顺序由 MySQL 说了算，翻两次可能不一样。

        3. request_date 有 15.14% 是 NULL（实测 336055 行）。按它倒序，
           这批 NULL 会全挤在最前面或者最后面，页面顶上出现一堆
           "日期是空的"的单，看着莫名其妙。

        代价说清楚：id 倒序 = 最后导进来的那些，不一定等于"单子日期最新的"。
        这次数据里两者恰好对得上（id 最大的 2789488 那张 request_date
        是 2026-09-15，就是全库最新的月份）。但这个巧合不该被依赖 ——
        所以上面三条理由里没有一条是"反正结果一样"。

        返回 ORM 对象、不返回 NamedTuple，跟 list_work_orders 一致：
        调用方要自己挑几个字段，ORM 上字段齐全挑起来方便。
        （不能学 count_by_* 那套 —— 那几个是 GROUP BY 出来的行，
        本来就不是表里的行，没有对应的模型。）
        """
        statement = select(WorkOrder).order_by(WorkOrder.id.desc()).limit(limit)
        return list(self.db.execute(statement).scalars().all())

    def list_high_maintenance_assets(self, limit: int) -> list[AssetWorkOrderCount]:
        """工单最多的那几台资产 —— 高维护资产榜的第一步。

        这一步只回 (asset_id, 工单数)，不带资产名。名字是第二步
        （AssetsRepository.list_by_ids）拿这批 id 去主键查的。

        为什么拆两步，不一条 JOIN 解决：一步 JOIN 出来 5852 ms，
        拆开 367 ms，省 15.9 倍。2026-10-04 实测：

            一步 JOIN assets      5852 ms   type=ALL   rows=151339
                                             Extra=Using temporary; Using filesort
            第一步 top10（这个）    367 ms   type=range key=ix_work_orders_asset_id
                                             Extra=Using index; Using temporary; Using filesort
            第二步 按主键查名字        0 ms   type=range key=PRIMARY rows=10
            ⇒ 两步合计 367 ms

        那 5.5 秒差在哪：一步写的时候 assets 那边是 type=ALL（14.8 万行全扫），
        因为优化器要先按 asset_id 分完组才知道哪 10 个进榜，而分组之前
        它还得为了取名字把 assets 也拖进来，最后两张表都扫一遍。
        拆成两步之后，第一步只用 ix_work_orders_asset_id 这棵索引
        （Extra 里的 Using index 说明连回表都不用），第二步是 10 次主键查，
        快到 0.4 ms 看不出来。

        所以这个不是"JOIN 一定慢"，是"这个 JOIN 让优化器挑了个坏计划"。
        拆成两步等于把优化器要做的选择替它做完了 —— 因为只有人知道
        "先进 top10 再查名字"才是对的顺序，优化器不知道。

        顺带记一笔数据：工单里 asset_id 非空的比例是 100.00%
        （2220847 / 2220853），所以下面那个 WHERE 一条都筛不掉。
        留着它不是因为现在有用，是因为 asset_id 在模型上是可空的 ——
        将来平台自己建单忘了挂资产，这批就会掉进 NULL 桶，
        那时候没有这个条件，榜上会冒出一个 asset_id 是空的"资产"。

        最后一句 ORDER BY 里的 n：SQL 里用 select 里定义的别名排序，
        MySQL 认。写成 func.count(WorkOrder.id).desc() 再编一遍也一样，
        但那样这个表达式就出现三次（select / group by / order by），
        改的时候容易漏一个。
        """
        count_expression = func.count(WorkOrder.id).label("n")
        statement = (
            select(WorkOrder.asset_id, count_expression)
            .where(WorkOrder.asset_id.is_not(None))
            .group_by(WorkOrder.asset_id)
            .order_by(count_expression.desc())
            .limit(limit)
        )
        return [
            AssetWorkOrderCount(asset_id=row.asset_id, work_order_count=row.n)
            for row in self.db.execute(statement).all()
        ]

    def resolution_stats(self, months: int) -> ResolutionStats:
        """平均处理周期 + 样本数。

        定义：完工日期减建单日期（DATEDIFF，单位是天），对有这两个日期的单求平均。

        三个 WHERE 条件，一条条说：

        1. 两个日期都不能空。没有建单日期的算不出周期；
           有建单日期、没有完工日期的说明这单还没干完，把它算进来
           等于假装"今天就完工了"，平均周期会被算短。

        2. completion_date >= request_date。滤掉补工日期比建单日期还早的脏行 ——
           那是导入时两边来源对不上造成的。留着会把平均值往下拽，
           而且拽多少取决于脏数据有多少，不是个稳定的偏差。

        3. 限最近 months 个月。这个不是图省事，是必须的，看下面。

        限窗为什么必须做（2026-10-04 实测，同一个聚合、只换窗口）：

            全历史         50.7206 天（1861985 张单）  3125 ms  type=ALL
            最近 12 个月   22.0449 天（  78520 张单）   147 ms  type=range 走日期索引
            最近 24 个月   24.8042 天（ 182058 张单）  2935 ms  type=ALL   <- 又掉回全表扫

        盯住 24 个月那行：单数只比 12 个月多 1.3 倍，耗时却是 20 倍。
        因为窗口一大，优化器就不认为走日期索引划算了，退回全表扫 2158704 行。
        也就是说 12 往上加一格，性能不是缓降而是塌方。
        （这段和 config 里 dashboard_trend_window_months 的注释是一件事的两面：
        那边说"为什么定 12"，这边说"换成别的会怎样"。）

        顺带说两个口径差多远：全历史 50.7 天 vs 最近一年 22.0 天，差一倍多。
        因为最早那批单是 2000 年起的，处理周期长得离谱，把全历史平均拖着走。
        所以限窗不只是为了快 —— "平均 50.7 天"这个数对现在的运维没有任何指导意义，
        它描述的是二十多年前的做事方式。
        """
        statement = select(
            func.avg(func.datediff(WorkOrder.completion_date, WorkOrder.request_date)),
            func.count(WorkOrder.id),
        ).where(
            WorkOrder.request_date.is_not(None),
            WorkOrder.completion_date.is_not(None),
            WorkOrder.completion_date >= WorkOrder.request_date,
            WorkOrder.request_date >= trend_window(months),
        )
        average_days, sample_count = self.db.execute(statement).one()
        return ResolutionStats(
            average_days=average_days,
            sample_count=int(sample_count or 0),
        )

    def trend_by_month(self, months: int) -> list[MonthlyWorkOrderCount]:
        """工单趋势：最近 months 个月，每个月建了多少单。

        2026-10-04 实测（同一个 GROUP BY、只换窗口）：

            全历史       1843 ms  223 个月  type=range key=ix_work_orders_request_date
            最近 12 个月   93 ms   12 个月  同一条索引，rows 从 1079352 降到 168864
            最近 24 个月  208 ms   24 个月
            最近 36 个月  318 ms   36 个月

        补一个数，因为它说明了一件容易搞错的事：上面那组是裸 SQL 量的，
        后来换成走 ORM 的写法（也就是下面这段代码）再量了一次 12 个月，
        得到 48 ms —— 不到 93 的一半。执行计划是一字不差的
        （都 type=range、都走 ix_work_orders_request_date、rows 都是 168864），
        差的只是量的时候 buffer pool 热不热：93 ms 那次是冷启动量的，
        48 ms 那次前面刚连跑过几个查询。
        ⇒ 两次不同时机量的绝对值不能直接比。要比就比执行计划，或者比同一批里的比例
        （"12 个月比全历史快 38 倍"这种，两个数出自同一批，才站得住）。

        这里和平均周期那次不一样：窗口放大是"缓涨"不是"塌方"
        （93 -> 208 -> 318，差不多跟着月份数走）。因为 GROUP BY 要建的临时表
        本来就得建，多几个月无非多几行。所以这个查询就算不限窗也才 1.8 秒 ——
        还是限 12 个月，理由不是性能，是 223 个点画在图上就是一根毛刺。

        日期边界用 DATE_FORMAT 取 'YYYY-MM'。MySQL 里没有 date_trunc
        （那是 Postgres 的），DATE_FORMAT 是这儿的正经做法。
        出来的字符串正好就是前端横轴上要显示的东西，不用二次加工。

        排序按 month 这个标签本身来。'YYYY-MM' 是定长零填充的，
        字典序就等于时间序，不用转成日期再排。
        （不用 ORDER BY 1 那种按序号排的写法：那个"1"指的是 select 里第几个字段，
        以后谁往前面插一列，排序就悄悄歪了，还不报错。）
        """
        month = func.date_format(WorkOrder.request_date, "%Y-%m").label("month")
        statement = (
            select(month, func.count(WorkOrder.id).label("work_order_count"))
            .where(WorkOrder.request_date >= trend_window(months))
            .group_by(month)
            .order_by(month)
        )
        return [
            MonthlyWorkOrderCount(
                month=row.month,
                work_order_count=row.work_order_count,
            )
            for row in self.db.execute(statement).all()
        ]

    def list_status_history(self, work_order_id: int) -> list[WorkOrderStatusHistory]:
        """查一张单的流转流水，按 id 正序 —— 也就是这单一路走过来的顺序。

        为什么不分页：一张单的流水在业务上就多不了。建单 1 条，
        之后每流转一次加 1 条，走到 CLOSED 也就 5 条。
        哪天真有人把一张单折腾出几百条，那件事本身就该去查清楚，
        而不是先给它套个分页把问题盖住。

        排序用 id 而不是 created_at：created_at 只精确到秒，
        同一秒里连着做两个动作（脚本批处理很容易这样）顺序就乱了 ——
        而"谁先谁后"恰恰是流水唯一要表达的东西。
        架构文档里那句"默认排序使用稳定字段"，说的就是这种事。
        """
        statement = (
            select(WorkOrderStatusHistory)
            .where(WorkOrderStatusHistory.work_order_id == work_order_id)
            .order_by(WorkOrderStatusHistory.id)
        )
        return list(self.db.execute(statement).scalars().all())

    def list_processing_records(
        self, work_order_id: int
    ) -> list[WorkOrderProcessingRecord]:
        """查一张单的处理记录，同样按 id 正序。分页和排序的理由跟上面一样。"""
        statement = (
            select(WorkOrderProcessingRecord)
            .where(WorkOrderProcessingRecord.work_order_id == work_order_id)
            .order_by(WorkOrderProcessingRecord.id)
        )
        return list(self.db.execute(statement).scalars().all())

    # 这里原来有个 count_work_orders()，是全项目最贵的单条查询，2026-09-29 删了。
    # 它当时量出来的数（keep 在这儿，因为这是"为什么删它"的证据）：
    #
    #     assets      148423 行  ->   16~23 ms
    #     work_orders 2220853 行 ->  322~358 ms
    #     同一条列表查询（游标取 21 行） ->  1.2~1.6 ms
    #
    # 也就是说这一个是列表查询的两百多倍，占了整个请求 437 ms 里的 330 ms（75%）。
    # 删掉它之后列表请求回到个位数毫秒。理由写在 schemas/common.py 的 CursorMeta 上。
    #
    # 记一笔当时排除的路子：本来说"上 Redis 缓存一下"，
    # 但缓存该给"确实需要、而且算起来贵"的东西用。这个数字不需要（游标分页跳不了页），
    # 也不值得为它引一整个 Redis 组件。真要看总量就该放 Dashboard 里缓存一次给整页复用。

    def add(self, work_order: WorkOrder) -> WorkOrder:
        """插一条工单。

        注意这里只 add 不 commit，提交时机交给 service ——
        跟 OperationLogRepository.add 那边一个道理：
        创建工单要同时写三张表（工单 + 状态流水 + 操作日志），
        得一起成功或者一起失败，中途谁都不能自己先提交一次。
        """
        self.db.add(work_order)
        return work_order

    def add_status_history(self, history: WorkOrderStatusHistory) -> None:
        """插一条状态流水。同样不 commit，理由见上面。"""
        self.db.add(history)

    def add_processing_record(self, record: WorkOrderProcessingRecord) -> None:
        """插一条处理记录。同样只 add 不 commit，理由见上面。

        这个跟 add_status_history 是两码事，别看名字像就合并：
        流水的每一行对应一次状态变化（所以有 from_status / to_status），
        处理记录是人随手写的备注（没有状态，只有一个 content）。
        合成一张表的话，就会有一半的列永远是 NULL。
        """
        self.db.add(record)

    def apply_transition(
        self,
        *,
        work_order_id: int,
        from_status: str,
        to_status: str,
        extra_values: dict[str, object] | None = None,
    ) -> int:
        """改状态，但只在"当前状态还是我以为的那一个"时才改。返回真改了几行。

        乐观锁就落在这一句 where 上。原来 service 那边是"先查出来、判断合法、
        再把对象的属性改掉"，判完到写库之间没人拦着，两个人同时点就会双双通过
        （2026-09-30 实测复现过：一个点开始一个点驳回，两条互斥的流水都写进去了）。
        现在把"我读到的那个状态"一起塞进 where：
        谁先提交，谁就把状态改走了，后到的那个 where 匹配不上、返回 0 行，
        调用方一看 0 就知道"我基于的那份判断已经过期了"。

        这跟加锁不是一回事。行锁能挡住"同时写"，挡不住"基于一个过期的状态做判断"——
        后到的人照样能拿到锁、照样能写，他只是不该写。要拦的是这个"不该"。

        两个 MySQL 的细节，都得记着：
        1. rowcount 是"真正改了内容的行数"，不是"匹配上的行数"
           （pymysql 默认没开 CLIENT_FOUND_ROWS）。所以这里能靠它判断，
           前提是这条 UPDATE 每次都确实改了东西 —— 好在状态机保证 from 和 to
           绝不会是同一个值（允许表里没有自环），所以 status 这一列必定变。
           哪天要是有人给这条语句加个"值没变就不改"的优化，这个判断就塌了。
        2. synchronize_session=False：不让 SQLAlchemy 顺手动 session 里那份对象。
           它默认会试着算一下"怎么把内存里的实例同步过去"，在带条件的 UPDATE 上
           那条路不一定对得上，算错了还不报错。我们只要行数，
           对象那份让调用方 refresh 一下，反而清楚。
        """
        values: dict[str, object] = {
            "status": to_status,
            # 状态来源顺手记成 PLATFORM：从这一刻起这个状态是人改出来的
            "status_origin": "PLATFORM",
        }
        if extra_values:
            # 完成要写完工日期、分派要写派给了谁，各自从这儿塞进来。
            # 用 dict 展开成列名是有意的：名字写错了 SQLAlchemy 编译时就炸，
            # 不会静默变成一个没人认识的属性
            values.update(extra_values)

        statement = (
            update(WorkOrder)
            .where(WorkOrder.id == work_order_id, WorkOrder.status == from_status)
            .values(**values)
            .execution_options(synchronize_session=False)
        )
        return self.db.execute(statement).rowcount
