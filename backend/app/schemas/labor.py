from datetime import date
from decimal import Decimal

from pydantic import BaseModel


class LaborSummary(BaseModel):
    """工时列表里一行长什么样。

    跟 WorkOrderSummary 一样，这是张白名单：没写在这儿的字段前端拿不到。
    12 个字段是"挑"出来的，不是把 work_order_labor 那 21 列抄一遍。

    挑选依据是 2026-10-01 跑的 NULL 占比统计（一次全表扫量完 18 列，
    320 万行花了 10.49 秒）。分三档：

        一档，一个空值都没有（占了 11 列）
            source_record_id / data_source / source_work_order_record_id
            action / work_date / operation_type / hours / rate / cost / entered_at / misc

        二档，零星几个空值
            work_order_id     0.41%（13078 行，原始数据里挂不上工单的那批）
            trade             0.59%（18875 行）

        三档，基本整列是空的 —— 全砍了
            job_category     99.51%    on_text   99.79%
            off_text         99.79%    description 99.95%
            correction_flag 100.00%（区分度 0 种，一个值都没有）

    二档那两个留着，理由不一样：
        work_order_id 留着，因为"这条工时是哪个工单干的"是列表最核心的一列，
            缺了那 0.41% 前端显示成空就好。原始数据本来就有 13078 条挂不上工单，
            文档里也没要求伪造这个关系。
        trade 留着同上，它是工种的唯一来源，虽然缺 0.59%，
            但列表上没工种这一列，"谁干的这活"就无从判断了。

    另外单独说一个看起来能留、其实该砍的：misc。
    它 0% NULL，一个空值都没有 —— 光看"有没有值"这个判据，它该留下。
    但它总共只有两种值：'-' 占了 3200635 行（99.96%），'+' 只有 1385 行。
    ⇒ 列表页上这就是一整列重复的字，区分度 0.04%。所以砍了。
    （我一开始猜 misc 是 cost 的正负号，量完才发现不是：misc='-' 的 320 万行里
    只有 70618 行 cost 是负的。假设错了，好在量了。）

    最后说清楚可空性跟"砍没砍"是两件事：
        schema 上标不标 `| None`，看的是「模型那一列允不允许 NULL」，不是看实测有没有空值。
        实测 0% NULL 只是说明"当下数据干净"，模型没加 NOT NULL 约束就迟早会有空值。
        action 实测一个空都没有，但列本身可空，所以这儿还是写 str | None ——
        写死成 str 的话，将来真来一行 NULL 就是 500，为了一行数据把整个列表打挂不值。

    单位：hours 是小时，rate 是时薪，cost 是这一条工时的金额。
    这三个数不是随便摆的，cost = hours x rate（2026-10-01 量的）。

    但严格相等只有 84.51%（前 20 万行），一开始看着像数据有问题。
    抽了 5 行出来看才发现原因：hours 这一列是两位小数，被截过 ——
        id=38  hours=0.42  rate=24.16  cost=10.07
        cost/rate = 10.0748/24.16 = 0.4168...
    也就是说 cost 是用「没被截断的小时数」算出来的，hours 只是它截到两位小数的样子。
    把容差换成「hours 最多被截掉 0.005 小时 x rate，再留一分钱」之后，
    前 20 万行 200000/200000 全部满足。
    ⇒ 这条关系可以当断言用：哪天搬字段时把 hours / rate / cost 三个搬错了位，
    这条会挂。三个名字长得像，搬错了不会报错，只会静默给出错的数。

    另外原始数据里有脏值：cost < 0 的 70642 行、hours < 0 的 73861 行。
    最夸张的一行 cost 是 -501452280.00。我们不做清洗（ETL 规则里"空值不伪造"
    是同一个口径：原始数据什么样就是什么样，要修也得记进导入报告，不能在接口层悄悄抹掉）。
    """

    id: int
    # 官方数据集里那串工时号，跟 assets 的 source_record_id 是一个来路
    source_record_id: str
    data_source: str
    # 这条工时挂在哪个工单上。0.41% 是空的，原始数据里挂不上的那批
    work_order_id: int | None
    # 保留原始 BOO_EVENT，跟 work_orders 上那个 asset_source_record_id 是一回事：
    # 外键解析之前先留一手，解析丢了也能回去对
    source_work_order_record_id: str | None
    # 干了什么。实测 19 种值，但 99.3% 就两种：'10' 有 1898627 行、'20' 有 1282296 行。
    # 这几个码什么意思文档里没给，所以不翻译，原样发出去
    action: str | None
    work_date: date | None
    # 工种。97 种值，是 labor 上最自然的分类维度
    trade: str | None
    # 作业类型。只有 2 种值（全表 COUNT DISTINCT 花了 3.70 秒才数出来）
    operation_type: str | None
    # 这三列用 Decimal 不用 float。浮点算钱会掉精度，这不是洁癖 ——
    # 0.1 + 0.2 在浮点里不等于 0.3，对账的时候会莫名其妙对不上。
    #
    # 代价是它们出 JSON 的时候是「字符串」，不是数字（2026-10-01 验过）：
    #     {"hours": "6.00", "rate": "26.1400", "cost": "156.84"}
    # 连数据库那列的标度都带出来了（rate 是 Numeric(18,4)，所以尾巴上两个零）。
    # 前端要是直接拿它做加法，会变成字符串拼接 "156.84" + "26.14" = "156.8426.14"；
    # 得先 parseFloat。这是有意的取舍：宁可让前端多一步转换，
    # 也不在服务端把精度丢掉 —— 钱算错比格式难看严重得多。
    hours: Decimal | None
    rate: Decimal | None
    cost: Decimal | None
