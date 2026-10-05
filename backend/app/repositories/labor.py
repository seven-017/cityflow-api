from decimal import Decimal
from typing import NamedTuple

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import WorkOrderLabor
from app.repositories.sql_helpers import trend_window


class LaborTotals(NamedTuple):
    """工时表一次性查回来的三个数：条数、合计小时、合计金额。

    跟工单那边的 WorkOrderStatusCounts 一个道理用 NamedTuple：
    三个数里前一个是 int、后两个是可空的 Decimal，虽然类型不完全一样，
    但"合计小时"和"合计金额"这两兄弟长得太像了，光是拆包位置错一位就容易搞反。
    """

    record_count: int
    total_hours: Decimal | None
    total_cost: Decimal | None


class MonthlyLaborTotals(NamedTuple):
    """Labor 趋势图的一个点：某个月 + 条数 + 合计小时 + 合计金额。

    四个字段：一个 str、一个 int、两个可空 Decimal。后面三个全是数字，
    而且两个合计又是那对容易搞反的兄弟，所以照样带名字。

    两个合计允许是 NULL：某个月一条记录都没有的话它根本不会出现在结果里
    （GROUP BY 的性质），但"这个月有一行、那行的 hours 是 NULL"是另一回事 ——
    SUM 会跳过 NULL，所以只要组里有一行有值就不会是 NULL。真正 NULL 的情况是
    整组都是 NULL。现在库里 hours / cost 两列一行 NULL 都没有，
    但那是导入脚本的行为，不是数据库的约束。
    """

    month: str
    record_count: int
    total_hours: Decimal | None
    total_cost: Decimal | None


class LaborRepository:
    """工时表的查询。

    整个项目里只有这一层允许出现 select()。上面 service 和 router 都不知道 SQL 长啥样。

    这张表 320 万行（2026-10-01 实测），比 assets 少一点，比 work_orders 多一点，
    属于"必须走游标"的量级。
    """

    def __init__(self, db: Session) -> None:
        self.db = db

    def list_labor(
        self,
        *,
        after_id: int | None,
        limit: int,
        work_order_id: int | None = None,
    ) -> list[WorkOrderLabor]:
        """按 id 往后翻，一次取 limit 条（其实会多要一条，见下面）。

        跟 assets 那边同一个套路：游标翻页，不用 OFFSET。
        但这边多量了一组数，因为 labor 的行数是 assets 的 1.4 倍，
        不能想当然认为"那边好这边就好"。2026-10-01 实测（各跑 3 次取中位数）：

            WHERE id > 0         ORDER BY id LIMIT 21  ->     0.97 ms
            WHERE id > 3190000   ORDER BY id LIMIT 21  ->     0.49 ms
            对照 LIMIT 21 OFFSET 0                     ->     0.43 ms
            对照 LIMIT 21 OFFSET 3000000               ->  3579.84 ms

        最后一组是这次的对照组：同一个位置、同样 21 行，OFFSET 要 3.58 秒。
        EXPLAIN 里 OFFSET 那条 type=index、rows=3000021 —— 它真的是"从头一行行走，
        走过 300 万行全丢掉再取 21 行"。游标那条 rows 只剩 22464，0.49 ms。
        ⇒ 3579.84 / 0.49 差不多 7300 倍。assets 上量出来是 3700 倍，
        这次更狠，因为表更大。

        注意 EXPLAIN 第一页那条的 rows 写着 1579628，看着像要扫 158 万行，
        但它只花了 0.97 ms —— 因为 LIMIT 21 到了就停。rows 是优化器的估算，
        不是实际扫描行数，别拿它当耗时看。

        第二个参数 work_order_id 是可选的过滤，也就是"这张工单下都有哪些工时"。
        这是 labor 上唯一做了的过滤条件，为什么就它，理由有三条：
          1. 文档里明确点名了这个用法（工单详情要带 Labor 汇总）；
          2. 表上有现成的索引 ix_work_order_labor_work_order_id；
          3. 它是"一个页面上必须的"，不是"某个筛选项"。
        文档里还列了 keyword / trade / operation_type / asset_id / date_from / date_to，
        那些都没做，理由见 service 那边的说明。

        带过滤时的计划不太一样，也量了（拿一个名下有 3867 条 labor 的工单试的）：
            WHERE work_order_id = ? AND id > 0 ORDER BY id LIMIT 21  ->  8.95 ms
            EXPLAIN: type=index_merge, key=ix_work_order_labor_work_order_id,PRIMARY
                     Extra: Using intersect(...); Using where; Using filesort

        ⇒ 它走了 index_merge（把工单索引和主键索引取交集），而且带 filesort。
        不算漂亮，但 8.95 ms 能用。原因是工单索引只有 work_order_id 一列，
        过滤完还得按 id 排序，排序这一步躲不掉。
        要根治得建联合索引 (work_order_id, id) —— 但那是新增索引，
        属于"数据量上来之后才谈得上算账"的事，这一版先不动。
        先把这个数和这条结论记在这儿，将来真要优化，从这儿起步。
        """
        statement = select(WorkOrderLabor)
        if work_order_id is not None:
            # 不传就是"全部工时"，不加工单条件
            statement = statement.where(WorkOrderLabor.work_order_id == work_order_id)
        if after_id is not None:
            # 不传 after_id 就是第一页
            statement = statement.where(WorkOrderLabor.id > after_id)
        # 多要一条（limit + 1）：拿回来是 limit + 1 条就说明"后面还有"，
        # 只有 limit 条就说明到底了。省掉额外一次查询。
        # 多出来的那一条由 service 裁掉，不会发到前端。
        statement = statement.order_by(WorkOrderLabor.id).limit(limit + 1)
        return list(self.db.execute(statement).scalars().all())

    def totals(self) -> LaborTotals:
        """一次查出工时条数、合计小时、合计金额。

        三个数一条 SQL 搞定，不分成三条 —— 跟工单那边同一个道理（那边有对照实验，
        991.9 ms vs 1329.9 ms），这里不再重复量一遍：扫一次表拿三个数，
        永远比扫三次各拿一个数便宜，何况这张表 320 万行。

        2026-10-02 实测：3202020 条，一条聚合 3257.5 ms。
        这是整套 Dashboard 指标里最贵的一个 —— 比第二贵的（交易明细 1361 ms）
        还贵一倍多。缓存值不值得做，分母主要就是它贡献的。

        两个 SUM 都允许是 None。空表上 SUM 返回 NULL，不是 0。
        这儿不把它改成 0 是故意的：这张表要是真的一条都没有，
        "合计 0 小时"读起来像"确实有人干活但没花时间"，
        跟"一条记录都没有"是两回事。business-rules.md 里那句
        「空值不伪造」说的就是这个 —— 宁可让前端显示一个破折号。

        另外记一笔数据现状：hours 和 cost 列一行 NULL 都没有（3202020 行全满），
        但有负数 —— hours < 0 的 73861 行、cost < 0 的 70642 行。
        那是导入进来的原始数据自带的（冲正、退回之类的记录），不清洗、不过滤，
        合计就按原样算。要按"正数才算工时"来合计，那是个业务决定，
        不是这里能自己拍的事。
        """
        statement = select(
            func.count(WorkOrderLabor.id),
            func.sum(WorkOrderLabor.hours),
            func.sum(WorkOrderLabor.cost),
        )
        record_count, total_hours, total_cost = self.db.execute(statement).one()
        return LaborTotals(
            record_count=int(record_count or 0),
            total_hours=total_hours,
            total_cost=total_cost,
        )

    def trend_by_month(self, months: int) -> list[MonthlyLaborTotals]:
        """Labor 趋势：最近 months 个月，每月的条数 / 合计小时 / 合计金额。

        三个汇总一条 SQL 出，不分成三条 —— 跟 totals() 那边同一个道理，
        这张表 320 万行，扫三遍拿三个数不如扫一遍拿三个数。

        这里有个坑，量了才知道，而且它是九个图表里最贵的一格。

        结论先摆出来：「只要 select 里带上 SUM(hours) / SUM(cost)，
        work_date 那个索引就用不上了」，窗口限多小都一样。

        2026-10-04 实测（同一个 session 里连着跑，buffer pool 是热的）：

            只数条数，限 12 个月       94.2 ms   type=range key=ix_work_order_labor_work_date
            带三个汇总，限 12 个月   3083.7 ms   type=ALL   rows=3159256
            带三个汇总，限 24 个月   3195.1 ms   type=ALL   rows=3159256

        盯住后两行：窗口从 12 翻到 24 个月，耗时只涨 3.6%，EXPLAIN 里 rows
        一个数都没变 —— 都是 3159256，也就是整张表。这说明它压根没在"按窗口筛"，
        每次都是把 320 万行从头到尾扫一遍，扫完再丢掉窗口外的。

        为什么：限窗那个条件只用 work_date 一列，单独走索引没问题；但 select 里
        还要 hours 和 cost，这两列不在索引里，走索引就得回表 39 万次。
        优化器一算"回表 39 万次"比"顺序扫 320 万行"贵，就放弃索引了。
        这是它的判断，不是 bug —— 对行宽不小的表，这个判断通常还是对的。

        那为什么明知道 3 秒还这么写，三条理由：

        1. 图上真正要看的是"每月花了多少工时 / 多少钱"，只看条数没意义。
           一个"每月录了多少条"的图，看不出这个月是活多还是活重。
        2. 三个数必须出自同一次扫描。拆成三条 SQL 就是三次全表扫，只会更贵。
        3. 这整页是缓存的，5 分钟才算一次。3 秒摊进 5 分钟里不算什么 ——
           缓存存在的意义就是让这种"偶尔贵一次、然后一直便宜"的东西不难受。

        根治的办法是建 (work_date, hours, cost) 这种覆盖索引：
        三个值都在索引里，不用回表，优化器就愿意走它了。
        但加索引是另一件事 —— 多一个索引就多一份写入代价，得先量清楚值不值当。
        这一版先把这个数记在这儿，将来真要优化，从这一行起步。
        （跟上面 list_labor 里那个"要根治得建 (work_order_id, id)"是同一类决定：
        都是"知道怎么治，但现在不治"，两处都留了数，不是忘了。）

        最后一件必须记下来的数据，因为图上会出现一根突兀的高柱：
        2026-08 那个月的合计是 1961495.60 小时，比平常的 3 万多个 60 倍。
        原因查过了，是单条脏数据 —— id=3175170 那一行 hours=1929817
        （换算下来约 220 年）、cost=52761196.78，它一条就把整月从 3 万拉到 196 万。

        别急着说"就这一条"。我去全表扫了一遍，hours 超过十万的有 84 行。
        最大的是 id=2416976（2023-04-28），1023 万小时 —— 换算下来 1168 年，
        cost 五个亿，比 2026-08 那条还大五倍。2025-08 也有一条类似的
        （id=2966342，45 万小时）。这两条都不在最近 12 个月的窗口里，所以图上看不见。
        说白了：窗口里那根柱子，只是这批脏数据里恰好被画出来的那一条。

        （这段原来只写了 2026-08 一条，口气像"就是这个月的特例"。
        后来把 24 个月的序列整个看了一遍，又去全表扫了两回，才改成现在这样 ——
        只查一个点就下"这是个例外"的结论，结论往往是错的。）

        不清洗、不过滤，照原样发出去。它们是库里真真切切存在的行，不是查询算错了，
        也不是聚合写歪了。前端要是嫌那根柱子难看可以自己处理（截断纵轴之类），
        但后端不替它决定"哪个数不算数" —— 真实数据里的异常值该被看见，
        抹掉它只是在骗下一个看图的人。
        """
        month = func.date_format(WorkOrderLabor.work_date, "%Y-%m").label("month")
        statement = (
            select(
                month,
                func.count(WorkOrderLabor.id).label("record_count"),
                func.sum(WorkOrderLabor.hours).label("total_hours"),
                func.sum(WorkOrderLabor.cost).label("total_cost"),
            )
            .where(WorkOrderLabor.work_date >= trend_window(months))
            .group_by(month)
            .order_by(month)
        )
        return [
            MonthlyLaborTotals(
                month=row.month,
                record_count=row.record_count,
                total_hours=row.total_hours,
                total_cost=row.total_cost,
            )
            for row in self.db.execute(statement).all()
        ]

    def add(self, labor: WorkOrderLabor) -> WorkOrderLabor:
        """插一条工时。

        只 add 不 commit，提交时机交给 service ——
        因为创建工时是"业务记录 + 操作日志"两件事一起落库，
        必须一起成功或者一起失败。要是在这儿自己提交了，
        后面写日志时万一抛异常，就会留下一条"凭空出现、查不到谁录的"工时。
        （跟 operation_logs / work_orders 两边的 add 一个规矩。）
        """
        self.db.add(labor)
        return labor
