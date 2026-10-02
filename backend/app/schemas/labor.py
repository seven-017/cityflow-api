from datetime import date
from decimal import Decimal

from pydantic import BaseModel, Field


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


class LaborCreateRequest(BaseModel):
    """平台自己录一条工时。

    七个字段，只有三个必填。这份取舍一条条说：

    必填的三个，缺了这条工时就不成立：

        work_order_id   挂在哪张单上。
                        表上这一列其实可以为空（导入数据里 0.41% 是空的 ——
                        那是 AMPS 原始数据本身就挂不上单）。但我们自己录的
                        要求必填：一条不挂单的工时进不了任何工单的汇总、
                        不进 SLA、不进 Dashboard 的工时趋势，等于一条谁都看不见的
                        孤儿数据。平台主动造孤儿数据没意义，所以不开放这个可能。
                        这个判据跟"表可不可空"是两回事，别混。

        hours           多少小时。这是这个实体存在的理由。

        rate            时薪。为什么让录单的人自己填、而不是系统带出来 ——
                        因为库里没有"工种 -> 时薪"这张映射表（AMPS 没给）。
                        将来真要补那张表就该从那儿查，但那是这一步之后的事。

    可选的四个：

        work_date       不填就是今天。允许填过去的日期 —— 补录昨天干的活是常事。
        trade           工种，97 种值。
        operation_type  作业类型，只有 2 种值。
        action          动作码，19 种值，其中 99.3% 就两种（'10' / '20'）。

    没有的字段，以及为什么没有：

        cost            服务端算，不收。库里 cost = hours x rate 这条关系
                        实测 20 万行 100% 成立（容差算上了 hours 被截到两位小数的
                        那部分）。让调用方自己传 cost 就等于放开了"三个数互相对不上"
                        的可能 —— 而那条关系正是列表接口拿来做断言的依据。
                        所以只收两个数，第三个由服务端乘出来，保证内部一致。

        description     表上有这一列，但 labor 既没有详情接口、列表也不带它
                        （它在导入数据里 99.95% 是空的，列表那一步按这个砍了）。
                        填了没地方看，所以不开放 —— 让用户以为"我记了备注"、
                        结果哪儿都显示不出来，比一开始就不收更糟。

        source_record_id / data_source / entered_at
                        这三个是服务端填的，不是调用方能挑的：编号得保证不重复
                        （所以服务端生成）、数据源必须是 SYNTHETIC_PLATFORM
                        （写成 REAL_PUBLIC 这条记录就永远没人能改了）、
                        录入时刻只有一个正确答案（现在）。
    """

    work_order_id: int = Field(ge=1)
    # 上限跟列定义对齐：hours 是 Numeric(12,2)、rate 是 Numeric(18,4)。
    # 不限制小数位的话，传个 hours=6.005 会被 MySQL 静默截成 6.01 ——
    # 存进去的数跟用户填的不是一个数，而且没有任何提示。
    # 在这儿挡住变成 422，比事后去库里找"这数怎么不对"强。
    hours: Decimal = Field(gt=0, max_digits=12, decimal_places=2)
    # 允许 0（志愿工时也是工时），但不允许负。库里那些负数（73861 行）
    # 是导入数据的原样，平台自己录的不开放负数。
    rate: Decimal = Field(ge=0, max_digits=18, decimal_places=4)
    work_date: date | None = None
    # 三个字符串字段都照列宽卡上限。不卡的话超长会撞 MySQL 的
    # Data too long（Error 1406）变成 500，本来是个 422 的事
    trade: str | None = Field(None, max_length=150)
    operation_type: str | None = Field(None, max_length=100)
    action: str | None = Field(None, max_length=255)
