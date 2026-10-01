"""工单的 SLA 规则。

AMPS 那套原始数据里没有 SLA 这个概念 —— 这几条是平台自己定的
（文档里管它叫 "Synthetic Platform Business Rule"）。
所以这个文件跟 work_order_status.py 是一个性质：纯规则，不连库、不认识 session。

四个字段的分工，别混：

    priority       人录单的时候选的，P1 最急。这一列是"输入"
    sla_deadline   建单那一刻起算，加上对应分钟数。这是"算出来的结果"
    sla_source     记这个 SLA 是谁给的。平台算的一律 PLATFORM_RULE
    sla_policy     故意不写，理由见 compute_sla_deadline 上面那段
"""

from datetime import datetime, timedelta
from enum import StrEnum


class WorkOrderPriority(StrEnum):
    """工单优先级。库里的列是 String(2)，P1~P4 正好占满。

    用 StrEnum 而不是普通字符串，理由跟状态机那边一样：写错字母当场报错，
    不会悄悄变成一个谁都不认识的优先级，一路混到库里才被发现。
    """

    P1 = "P1"
    P2 = "P2"
    P3 = "P3"
    P4 = "P4"


# 优先级 -> 目标处理时间（分钟）。
#
# 这张表是文档里给的，不是我们编的：P1 30 分钟 / P2 2 小时 / P3 8 小时 / P4 24 小时。
#
# 单位统一用分钟：P1 是 30 分钟，要是用小时就得写 0.5 ——
# 0.5 这种小数在代码里既容易看漏那个点，也容易在乘除里攒出浮点误差。
# 要显示成"2 小时"是前端该干的事，不是数据该存的样子。
PRIORITY_SLA_MINUTES: dict[WorkOrderPriority, int] = {
    WorkOrderPriority.P1: 30,
    WorkOrderPriority.P2: 120,
    WorkOrderPriority.P3: 480,
    WorkOrderPriority.P4: 1440,
}


# SLA 是谁给的。取值照文档写死：平台自己算出来的都是这个值。
#
# 官方导入的那两百万单这一列是 NULL —— 它们代表历史上真实发生过的事，
# 没有谁给它们定过 SLA，我们也不去伪造一个补上
# （文档原话："历史 AMPS 工单不生成伪造 SLA"）。
SLA_SOURCE_PLATFORM = "PLATFORM_RULE"


def compute_sla_deadline(priority: WorkOrderPriority, start: datetime) -> datetime:
    """按优先级算这一单的目标完成时间。

    起算点是"建单那一刻"，不是 request_date。request_date 那一列是个 date，
    没有时分秒，拿它去加 30 分钟，等于当天零点就已经逾期了 ——
    P1 的单一建出来就该报警，那这个字段也就白算了。

    start 用 Python 的 datetime.now()，落库是 naive 的本地时间，
    跟库里 created_at 那个 func.now() 是同一个基准（跑在同一台机器上）。
    将来要是应用和数据库分到两台机器、时区还不一样，这儿就会算错 ——
    到时候得改成拿数据库的时间来算。

    函数里没有 sla_policy，是故意的：库里已经有了 created_at 和 sla_deadline，
    两者一减就是当时用的时限，一眼看得出来的东西不用再存一份加工版。
    真存了 sla_policy，规则哪天改了、老数据又没重算，就会跟 deadline 对不上，
    那时候还得判断哪个才是真的 —— 不如只留一个算得出来的。
    """
    return start + timedelta(minutes=PRIORITY_SLA_MINUTES[priority])
