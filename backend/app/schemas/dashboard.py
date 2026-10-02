from decimal import Decimal

from pydantic import BaseModel


class DashboardMetrics(BaseModel):
    """Dashboard 首页「指标汇总」那一块 —— 就是最上面那排数字卡片。

    字段不是照着哪个文档抄的。api.md 里 GET /dashboard/overview 底下只写了
    一行「指标汇总」，一个字段名都没给（后面那九项图表倒是列了名字）。
    所以这十个字段是按"这一页会摆哪几张卡片"挑出来的，每个都对着一条真 SQL。

    冷启动要花的钱，2026-10-02 各跑 3 次取中位数（走仓储层，含 ORM 开销）：

        assets             COUNT(*)                         19.9 ms
        work_orders        一次条件聚合（四个数）           1275.4 ms
        work_order_labor   COUNT + SUM(hours) + SUM(cost)   3180.7 ms   ← 最贵
        transactions       COUNT(*)                          93.2 ms
        transaction_details COUNT(*)                       1389.6 ms
        --------------------------------------------------------------
        合计                                               5958.7 ms

    这 5.96 秒就是缓存存在的理由（进程内 TTL 5 分钟，见 core/cache.py）。
    缓存命中时这个接口不该再碰数据库一下。

    工单为什么给四个数（总数 + 未完结 / 已完成 / 已退回），不干脆只给总数：
    因为光有总数看不出活干完了没有。而这三个桶的分法是有讲究的 ——
    「总数 = 未完结 + 已完成 + 已退回」这条等式恒成立，
    依据和推导写在 core/work_order_status.py 那三个常量上面。
    验收脚本拿它当断言，就是为了挡住"数字悄悄算错"这类问题
    （真挡下过一次，见 repositories/work_orders.py 里那个 Boolean 的坑）。

    那为什么不再给一份"每个状态各多少"？那是 20b 的状态分布图该干的事，
    是图表不是卡片，两件事不并到一块。

    两个合计（labor_total_hours / labor_total_cost）是可空的，
    这跟模型上 hours / cost 允许 NULL 是一致的，不是照库里现在有没有空值定的
    （实测 3202020 行一个 NULL 都没有，但那是导入脚本的行为，不是数据库的约束）。
    空表上 SUM 返回 NULL，接口这边就照原样返回 null，
    不把它编成 0 —— 理由写在 repositories/labor.py 的 totals() 里。

    还有个已知的坑，跟 AssetDetail.record_value 是同一个：
    这两个 Decimal 序列化出来是字符串（"19794050.87" 带引号），不是数字。
    这是故意的 —— 金额用 float 会掉精度。前端自己转，或者直接当字符串显示。
    """

    # 资产 148423（2026-10-02）
    asset_count: int
    # 工单 2220853，其中未完结 25196 / 已完成 2065995 / 已退回 129662。
    # 三个桶加起来正好是总数，见类注释
    work_order_count: int
    unfinished_work_order_count: int
    finished_work_order_count: int
    rejected_work_order_count: int
    # 工时 3202020 条
    labor_record_count: int
    # 合计 19794050.87 小时 / 468445281.65 —— 都允许为 null，见类注释
    labor_total_hours: Decimal | None
    labor_total_cost: Decimal | None
    # 交易头 752746 张
    transaction_count: int
    # 明细 2290091 行（是头的三倍，也就是"一张单平均三行多一点"）
    transaction_detail_count: int


class DashboardOverview(BaseModel):
    """/dashboard/overview 的 data 部分。

    现在它只有一个字段，看着像个多余的壳子。留着是有原因的：
    api.md 里这个接口要返回十样东西 —— 指标汇总，加九个图表
    （状态分布 / 工单类型 / 资产类型 / 高维护资产 / 平均处理周期 /
    Labor 趋势 / Transaction 趋势 / 最近工单 / 工单趋势）。

    20a 这一步只做「指标汇总」，图表是 20b。
    要是现在直接把 metrics 摊在 data 底下，20b 一加别的字段就得改返回形状 ——
    那是个没必要的破坏性变更。套个壳，20b 往里面加兄弟字段就行，
    已有的那部分（data.metrics）一个字都不用动。

    也就是说：这个壳不是为了漂亮，是为了让下一步只做加法。
    """

    metrics: DashboardMetrics
