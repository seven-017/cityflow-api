from datetime import date
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


class StatusDistribution(BaseModel):
    """状态分布图的一根柱子。

    status 用 str 而不是 WorkOrderStatus 枚举，是故意的：枚举在这儿会变成
    一道校验闸门 —— 库里哪天冒出一个枚举里没有的状态，整个 Dashboard 接口
    就 500 了，而那时候最该看见的恰恰是"多出来一个状态"这件事本身。
    用 str 的话它会照原样出现在图上，一眼看得出来。

    反过来说，service 拼这个列表的时候是按枚举遍历的（六个状态，
    库里没有的填 0）。所以正常情况下这儿只会出现那六个值，
    用 str 只是不想让"异常"变成"打不开页面"。
    """

    status: str
    # 六个状态加起来应该等于 metrics.work_order_count，这是守恒等式
    work_order_count: int


class WorkTypeDistribution(BaseModel):
    """工单类型分布的一根柱子。

    work_type 是官方数据里的自由文本列，实测只有 7 个取值
    （JOB / IN / AA / PPM / STAT / MRC / XA），JOB 一家占 82.9%。
    这儿不补零，理由写在 AssetTypeDistribution 上（同一类问题，只说一遍）。

    标可空不是照着模型定义抄的，是验收时真炸过一次，记下来：
    一开始这儿写的是 str。验收脚本跑到最后一步 —— 新建一张工单、
    再请求一次 overview —— 接口直接 500。冷启动那十几次请求全好好的，
    就这次炸，因为平台自己建的工单 work_type 是空的（创建接口不要求填），
    那个 NULL 一路传到 Pydantic 这儿，str 拒收，整页打不开。

    官方那 222 万行 work_type 一个 NULL 都没有，所以这个坑
    只有"平台自己建过单之后"才会踩到 —— 属于上线第二天才炸的那类。
    标成可空之后页面照常打开，只是那根柱子的标签是空的。
    让一根柱子难看，比让整页打不开好。
    """

    work_type: str | None
    work_order_count: int


class AssetTypeDistribution(BaseModel):
    """资产类型分布的一根柱子。

    跟状态分布一样是"分组 + 条数"，但有一个关键区别：「这个不补零」。

    状态那六个是 WorkOrderStatus 枚举定义好的，是权威清单，缺的补 0 才完整；
    asset_type 是自由文本列，谁也没定义过它有哪几种。
    真给它编一张类型表出来，等于凭空造一份码表，而且编错了没人发现。
    所以这儿只报库里现有的（实测 10 种，含一个值是 '*' 的脏数据，1 条）。

    asset_type 标可空，理由跟 WorkTypeDistribution.work_type 一样：
    这一列在模型上就是可空的，实测 0% NULL 只是"这批数据恰好没有"。
    真出现一条，接口该照常打开而不是 500。
    """

    asset_type: str | None
    asset_count: int


class HighMaintenanceAsset(BaseModel):
    """高维护资产榜的一条。

    名次由 work_order_count 排出来，列表顺序就是名次（service 那边保证的，
    因为 MySQL 不保证 IN 查询按传入顺序返回，所以重排那一步是必须的）。

    没有 rank 字段：名次就是列表下标，前端自己 +1 就行。
    加一个 rank 字段等于把同一件事存两份，两份还可能对不上。
    """

    asset_id: int
    # asset_type 在模型上可空，所以这儿标可空。一开始写的是 str、
    # 并且 service 里拿 or "" 把 null 兜成空字符串 —— 那是错的：
    # 空字符串和"没有类型"在数据上是两件事，兜一下就把它们混成一件了。
    # 不兜，让 null 就是 null（跟下面 asset_id / work_type 一个处理方式）。
    asset_type: str | None
    # 取资产表里的 description 那一列。实测最长 80 字符左右，
    # 不截断 —— 截多长是前端排版的事，后端截了它就改不回来了。
    # 注意这个字段在 assets 表上是 NOT NULL，所以这儿不用标可空
    description: str
    work_order_count: int


class ResolutionSummary(BaseModel):
    """平均处理周期 —— 这一项不是图，是一个数加一句限定。

    average_days 是可空的，两种情况会给 null：
      1. 窗口内一张符合条件的单都没有（AVG 返回 NULL）；
      2. 数据库里 COUNT 是 0 而 AVG 也是 NULL —— 其实是同一种情况。
    这种时候不编成 0，跟 LaborTotals 那两个合计一样：0 天和"没有数据"不是一回事。

    window_months 为什么必须跟着返回：22.04 天这个数，
    是"最近 12 个月"还是"全历史"算出来的，含义差一倍以上
    （实测全历史 50.72 天 vs 最近 12 个月 22.04 天）。
    光甩一个天数出去，前端只能瞎猜该标什么，或者干脆不标 ——
    那不标的话这个数就是误导。把窗口一起给出去，前端才可能把它标对。

    sample_count 同理：22.04 天是拿 78520 张单算的，还是拿 3 张算的，
    可信度差得远。这个数也必须露出来（仓储那层就特意带上了）。
    """

    average_days: Decimal | None
    sample_count: int
    window_months: int


class WorkOrderTrendPoint(BaseModel):
    """工单趋势图上的一个点。

    下面三个趋势 schema 长得几乎一样（都是 month + 数字），为什么不抽一个
    公共基类出来，说一下：

    1. 字段名不一样（work_order_count / record_count / transaction_count）。
       硬抽基类的话，基类里只能放 month 一个字段，剩下全靠子类 ——
       那不是抽象，只是把"每个类写两行"换成"每个类写两行 + 多一层继承"。
    2. 读的时候要跳着看。想知道"工单趋势图上有些什么"，得先看基类、
       再看子类，才能拼出完整字段。字段本来就没几个，摊开写更清楚。
    3. 它们的字段名是有讲究的，不是随便起的：工单趋势报的是 count(工单)，
       labor 趋势报的是 count(工时记录) 加两个金额。名字一样反而会让人以为
       它们报的是同一种东西。

    month 是 'YYYY-MM' 字符串。不是 date 对象，理由写在仓储那边的
    MonthlyWorkOrderCount 上（它本来就是给横轴当标签用的）。
    """

    month: str
    work_order_count: int


class LaborTrendPoint(BaseModel):
    """Labor 趋势图上的一个点。

    比另外两个趋势多两个数：合计小时和合计金额。都允许是 null
    （SUM 碰上整组全 NULL 会是 NULL），不编成 0 —— 理由跟指标汇总里
    那两个合计一样，写在 repositories/labor.py 的 totals() 里。

    提个醒（不是这里的问题，是数据本身）：2026-08 那个点的 total_hours
    是 1961495.60，比平常的 3 万多个 60 倍。原因是那边有一条
    hours=1929817 的脏数据（单条约 220 年），不是聚合算错了。
    详细来龙去脉写在仓储方法的注释里，图上那根高柱不是 bug。
    """

    month: str
    record_count: int
    total_hours: Decimal | None
    total_cost: Decimal | None


class TransactionTrendPoint(BaseModel):
    """交易趋势图上的一个点。

    数的是交易头（那张单），不是明细行。一张单领几样东西跟"做了多少笔交易"
    不是一回事，理由写在仓储方法的注释里。
    """

    month: str
    transaction_count: int


class RecentWorkOrder(BaseModel):
    """最近工单列表里的一条。

    七个字段，是从 WorkOrder 那三十来个列里挑出来的。挑的判据是
    "这一行在首页的小列表上要显示什么"：

        id               点进去要用的主键
        status           状态色块
        description      那一行正文
        work_type        类型标签
        request_date     建单日期
        completion_date  完工日期（没完工就是 null）
        asset_id         关联资产（实测 100% 非空，但仍标可空 —— 详见下）

    为什么没带 priority：这一列在库里 2220853 行「全是 NULL」（实测），
    带上就是每行发一个 null 出去。等平台自己建单开始填它了，再加不迟 ——
    那时候加字段不算破坏性变更（前端多一个可选字段而已）。
    这也算「没用到的不许先写」在对外契约上的样子：不是"以后可能需要"，
    是"现在一个非空值都没有"。

    为什么 asset_id 标了可空、实际却不是：模型上它确实可空
    （外键 ondelete="SET NULL"），现在 100% 非空只是因为这批数据的样貌。
    对外 schema 说的是"接口保证什么"，不是"今天库里长什么样" ——
    标成 int 的话，哪天出现一条没挂资产的单，整个列表接口就 500 了。
    """

    id: int
    status: str
    # 实测最长 80 字符、平均 30.9，不截断，理由同 HighMaintenanceAsset.description
    description: str
    work_type: str | None
    request_date: date | None
    completion_date: date | None
    asset_id: int | None


class DashboardCharts(BaseModel):
    """九个图表的数据，一个不留 —— api.md 列的九项全在这儿。

    排序大致照着页面上从上到下的摆放来的（分布类在前、趋势类在后、
    明细列表垫底），不是按重要性。前端不依赖这个顺序，但读代码时
    对上页面会比较顺。

    resolution_summary 夹在一堆 list 中间，看着有点不成群 ——
    它确实不是图，是"平均处理周期"那一项，api.md 把它跟图表列在一起了，
    所以按同一个层次放在这儿，没有单独给它开一个字段。
    """

    status_distribution: list[StatusDistribution]
    work_type_distribution: list[WorkTypeDistribution]
    asset_type_distribution: list[AssetTypeDistribution]
    high_maintenance_assets: list[HighMaintenanceAsset]
    resolution_summary: ResolutionSummary
    work_order_trend: list[WorkOrderTrendPoint]
    labor_trend: list[LaborTrendPoint]
    transaction_trend: list[TransactionTrendPoint]
    recent_work_orders: list[RecentWorkOrder]


class DashboardOverview(BaseModel):
    """/dashboard/overview 的 data 部分。

    两个字段：指标汇总（metrics）+ 九个图表（charts）。

    20a 建这个壳的时候，它底下只有 metrics 一个字段，看着多余 ——
    留壳的理由写在当时的注释里：api.md 定的返回形状是"指标汇总 + 九个图表"，
    套个壳，20b 往里面加兄弟字段就行，已有的 data.metrics 一个字不用动。
    现在 20b 到了，charts 加进来，壳的用处兑现了 ——
    上面那段说明留着不删，因为它是"当初为什么这么设计"的证据。

    整个响应会被缓存 5 分钟（core/cache.py）。冷启动一次要多久，
    分项数据写在 DashboardMetrics 的注释里，外加图表那一份，
    加起来的量级就是"为什么必须缓存"的答案。
    """

    metrics: DashboardMetrics
    charts: DashboardCharts
