from decimal import Decimal
from typing import NamedTuple

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import WorkOrderLabor


class LaborTotals(NamedTuple):
    """工时表一次性查回来的三个数：条数、合计小时、合计金额。

    跟工单那边的 WorkOrderStatusCounts 一个道理用 NamedTuple：
    三个数里前一个是 int、后两个是可空的 Decimal，虽然类型不完全一样，
    但"合计小时"和"合计金额"这两兄弟长得太像了，光是拆包位置错一位就容易搞反。
    """

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
