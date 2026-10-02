from enum import StrEnum

from app.core.exceptions import ConflictException


class WorkOrderStatus(StrEnum):
    """工单的六个状态，跟库里 work_orders.status 那一列一一对应。

    用 StrEnum 而不是裸字符串，理由跟 permissions.py 里那几个枚举一样：
    拼错 IN_PROGRES 会当场 AttributeError，而不是悄悄变成一个谁都匹配不上的值。
    另外它是 str 的子类，从数据库读出来直接拿来比就行，不用来回转换。
    """

    PENDING = "PENDING"
    ASSIGNED = "ASSIGNED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    REJECTED = "REJECTED"
    CLOSED = "CLOSED"


class WorkOrderAction(StrEnum):
    """能对工单做的五个流转动作。

    注意这里没有「创建」。创建的时候 from_status 是 None —— 它不是从某个状态
    走过来的，是被造出来的，所以不算流转，不归这张表管。创建是后面的事。
    """

    ASSIGN = "ASSIGN"
    START = "START"
    COMPLETE = "COMPLETE"
    CLOSE = "CLOSE"
    REJECT = "REJECT"


# 动作 -> 目标状态。这五条是死的，跟「当前状态是谁」没关系。
ACTION_TARGET: dict[WorkOrderAction, WorkOrderStatus] = {
    WorkOrderAction.ASSIGN: WorkOrderStatus.ASSIGNED,
    WorkOrderAction.START: WorkOrderStatus.IN_PROGRESS,
    WorkOrderAction.COMPLETE: WorkOrderStatus.COMPLETED,
    WorkOrderAction.CLOSE: WorkOrderStatus.CLOSED,
    WorkOrderAction.REJECT: WorkOrderStatus.REJECTED,
}


# 允许表：从左边这个状态出发，允许走到右边这几个状态里去。
#
# 为什么不写成 if/elif 链：表能一眼看完，还能被遍历 —— 那个 30 组合的测试
# 就是直接遍历它生成的，改一条规则不用爬到函数里头去翻。
#
# 最后两行千万别删。写成空的 set() 意思是「这状态哪儿都去不了」，
# 和「压根没这个键」是两回事 —— 后者只会让人以为是自己漏填了。
ALLOWED_TRANSITIONS: dict[WorkOrderStatus, set[WorkOrderStatus]] = {
    WorkOrderStatus.PENDING: {WorkOrderStatus.ASSIGNED, WorkOrderStatus.REJECTED},
    WorkOrderStatus.ASSIGNED: {WorkOrderStatus.IN_PROGRESS, WorkOrderStatus.REJECTED},
    WorkOrderStatus.IN_PROGRESS: {WorkOrderStatus.COMPLETED},
    WorkOrderStatus.COMPLETED: {WorkOrderStatus.CLOSED},
    WorkOrderStatus.REJECTED: set(),
    WorkOrderStatus.CLOSED: set(),
}


# 工程师能执行哪几个流转动作。
#
# 原话在 architecture.md 里："Engineer 只能执行 ASSIGNED -> IN_PROGRESS 和
# IN_PROGRESS -> COMPLETED。Admin 和 Dispatcher 可以执行管理型转换。"
# 说白了：开始和完成是"干活的人干完了自己那摊活"，驳回和关闭是"这张单接下来怎么走"，
# 后者归调度和管理。
#
# 写"允许的"而不是"禁止的"，是因为将来加新动作的时候，默认会落到
# "工程师不能做"这一边 —— 漏配置的后果是多一道闸门（顶多多问一嘴），
# 而不是少一道（可能被人绕过去）。
#
# 注意这个跟权限点不是一回事，别混。work_order:update 管的是
# "你能不能碰工单"，四个角色里三个都有；这张表管的是"能碰工单的人里，
# 哪个动作归谁"。两层都要过，缺一层就是漏洞。
ENGINEER_ALLOWED_ACTIONS: frozenset[WorkOrderAction] = frozenset(
    {WorkOrderAction.START, WorkOrderAction.COMPLETE}
)


def resolve_transition(
    current: WorkOrderStatus,
    action: WorkOrderAction,
) -> WorkOrderStatus:
    """问一句「这单现在是 current，我想对它做 action，行不行」。

    行就返回做完之后该是什么状态，不行就抛 ConflictException。

    这里抛 409 而不是别的，是有讲究的：这不是服务器坏了，是调用方想做的事情
    跟这单当前的状态对不上 —— 「想驳回一个已经完成的单」就属于这一类。
    要是随手抛个普通异常，会被兜底处理器接走变成 500，等于把「用户点错了」
    说成「我们服务出问题」，面试官一问就露馅。
    """
    # 这儿用中括号而不是 .get()：action 的类型标注已经是枚举了，五个值上面全写
    # 在这个映射里，走不到「找不到」那条路。真有人绕过类型标注硬塞个字符串进来，
    # 那就让它 KeyError —— 报出来比默默当成「不允许」强，至少你知道哪写错了。
    target = ACTION_TARGET[action]

    allowed = ALLOWED_TRANSITIONS.get(current, set())
    if target not in allowed:
        raise ConflictException(
            f"Cannot {action.value} a work order in status {current.value}."
        )

    return target


def is_terminal(status: WorkOrderStatus) -> bool:
    """是不是走到头了。

    注意 COMPLETED 不算 —— 它后面还有一步 CLOSED。这个特别容易搞错，
    因为「完成」这两个字听起来就像结束了，实际上它还能再关一次。
    """
    return not ALLOWED_TRANSITIONS.get(status, set())


# 「活干完了没有」的三个桶。Dashboard 的指标汇总就按这三个桶报数。
#
# 先说清楚一件事：这个分组文档里没有。business-rules.md 只给了
# 「源状态 -> 标准化状态」那张映射表，从头到尾没提过哪些状态算"未完结"。
# 所以这三个桶是我们自己切的 —— 但切法有依据，依据就是上面那份状态机：
#
#     主干：PENDING -> ASSIGNED -> IN_PROGRESS -> COMPLETED -> CLOSED
#     岔路：PENDING / ASSIGNED -> REJECTED（到这儿就断了，哪儿也去不了）
#
# 一刀切在 COMPLETED 上：主干左半边算未完结，右半边算已完成。
# REJECTED 是条死胡同，既不是"还在干"也不是"干完了"，单独占一个桶。
#
# 为什么非得给 REJECTED 留个桶：不留的话三个数（总数 / 未完结 / 已完成）
# 对不上账 —— 差的那批（实测库里 REJECTED 占 5.84%，129662 行）
# 没地方交代，看的人只会以为数字算错了。
# 三个桶互不重叠、合起来正好是全部六个状态，所以
# 「总数 = 未完结 + 已完成 + 已退回」这条等式恒成立。
# 验收脚本里拿它当断言：将来谁加了第七个状态忘了归类，那条断言当场红。
#
# 别跟 is_terminal 混。那个问的是「还能不能往下走」（COMPLETED 还能 CLOSED，
# 所以它不算走到头）；这儿问的是「活干完了没有」（COMPLETED 就算干完了）。
# 两个问题不一样，答案自然不一样，别把其中一个当成另一个的同义词。
UNFINISHED_STATUSES: tuple[str, ...] = (
    WorkOrderStatus.PENDING.value,
    WorkOrderStatus.ASSIGNED.value,
    WorkOrderStatus.IN_PROGRESS.value,
)
FINISHED_STATUSES: tuple[str, ...] = (
    WorkOrderStatus.COMPLETED.value,
    WorkOrderStatus.CLOSED.value,
)
REJECTED_STATUSES: tuple[str, ...] = (WorkOrderStatus.REJECTED.value,)
