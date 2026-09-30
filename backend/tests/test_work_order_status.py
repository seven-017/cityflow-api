import pytest

from app.core.exceptions import ConflictException
from app.core.work_order_status import (
    WorkOrderAction,
    WorkOrderStatus,
    is_terminal,
    resolve_transition,
)


# 期望表：这 30 格里，哪几格是通的、通完变成什么状态。
#
# 千万别图省事，从这个模块的 ALLOWED_TRANSITIONS 把这张表算出来。
# 那样就成了「拿实现去测实现」—— 你把允许表改错，期望值跟着一起错，
# 测试照样全绿，等于什么都没测。
#
# 这 6 行是照着业务文档里那张状态图抄的，属于「独立的一份答案」。
# 说白了：测试不能是把自己的答案再念一遍。
EXPECTED: dict[tuple[WorkOrderStatus, WorkOrderAction], WorkOrderStatus] = {
    # 格式是 (当前状态, 动作): 做完之后应该变成什么状态。
    # 没写在这张表里的格子，一律当成「不该被允许」。
    (WorkOrderStatus.PENDING, WorkOrderAction.ASSIGN): WorkOrderStatus.ASSIGNED,
    (WorkOrderStatus.PENDING, WorkOrderAction.REJECT): WorkOrderStatus.REJECTED,
    (WorkOrderStatus.ASSIGNED, WorkOrderAction.START): WorkOrderStatus.IN_PROGRESS,
    (WorkOrderStatus.ASSIGNED, WorkOrderAction.REJECT): WorkOrderStatus.REJECTED,
    (WorkOrderStatus.IN_PROGRESS, WorkOrderAction.COMPLETE): WorkOrderStatus.COMPLETED,
    (WorkOrderStatus.COMPLETED, WorkOrderAction.CLOSE): WorkOrderStatus.CLOSED,
}


def test_legal_transitions_return_target_status():
    """能走通的那 6 格：调用了就该正常返回目标状态。"""
    for (current, action), expected in EXPECTED.items():
        assert resolve_transition(current, action) is expected


def test_illegal_transitions_raise_conflict():
    """剩下 24 格：调用了就该抛 ConflictException。

    这里是把 6 个状态 × 5 个动作全遍历一遍，再回头看每个格子
    在不在期望表里 —— 不在的，就是「这个动作在当前状态下不该被允许」。
    顺手也把期望表本身查了一遍：漏填一格，这一格就会被当成非法来测，然后报红。
    """
    for current in WorkOrderStatus:
        for action in WorkOrderAction:
            if (current, action) in EXPECTED:
                continue
            with pytest.raises(ConflictException):
                resolve_transition(current, action)


def test_terminal_states_are_exactly_two():
    """终态正好是两个：REJECTED 和 CLOSED。

    这里故意写死「就这两个」，而不是去问允许表 —— 一样是为了让期望值独立。
    顺手也把「COMPLETED 不是终态」这件事钉死：完成这两个字听起来像结束了，
    实际它后面还有一步 CLOSED。
    """
    terminal = set()
    for status in WorkOrderStatus:
        if is_terminal(status):
            terminal.add(status)

    assert terminal == {WorkOrderStatus.REJECTED, WorkOrderStatus.CLOSED}
