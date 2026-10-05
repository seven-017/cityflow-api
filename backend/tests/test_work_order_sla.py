"""SLA 计算的测试。

下面这张表的数是照着业务规则抄的（P1 30 分钟 / P2 2 小时 / P3 8 小时 /
P4 24 小时），不是从实现里反推的 —— 反推的话实现写错、期望值跟着错，
测试照样全绿，等于什么都没测。
"""

from datetime import datetime, timedelta

from app.core.work_order_sla import (
    PRIORITY_SLA_MINUTES,
    WorkOrderPriority,
    compute_sla_deadline,
)

# 规则的原文。P2 是 120 分钟不是 60，P3 是 480 分钟不是 240 —— 这两个最容易记混
EXPECTED_MINUTES: dict[WorkOrderPriority, int] = {
    WorkOrderPriority.P1: 30,
    WorkOrderPriority.P2: 120,
    WorkOrderPriority.P3: 480,
    WorkOrderPriority.P4: 1440,
}


def test_deadline_is_start_plus_priority_window():
    """deadline 就是「起算点 + 该优先级的目标时长」。

    拿时间差去比，不写死绝对时间 —— 这样表里哪个数错了，这条就红。
    """
    start = datetime(2026, 10, 5, 9, 0, 0)

    for priority, minutes in EXPECTED_MINUTES.items():
        deadline = compute_sla_deadline(priority, start)
        assert deadline - start == timedelta(minutes=minutes)


def test_every_priority_has_a_window():
    """四个优先级必须一个不漏。

    实现里用的是字典下标，漏配要到「真有人建了那个优先级的单」才炸，
    而且炸在运行时。这条在测试阶段就把四个全扫一遍。
    """
    assert set(PRIORITY_SLA_MINUTES) == set(WorkOrderPriority)


def test_p1_deadline_is_half_an_hour_later():
    """P1 单独钉一下绝对值。

    它是唯一一个不满一小时的档，也是最容易把单位写错的地方
    （30 分钟写成 30 秒，或者当成 0.5 小时再去乘）。
    """
    start = datetime(2026, 10, 5, 9, 0, 0)
    assert compute_sla_deadline(WorkOrderPriority.P1, start) == datetime(
        2026, 10, 5, 9, 30, 0
    )


def test_start_point_is_used_as_is():
    """起算点原样用，不做「抹掉时分秒」这类加工。

    这条钉的是那个坑：起算点如果用 request_date（一个 date，没有时分秒），
    等于当天零点起算，P1 的单一建出来就已经逾期了。
    所以传进来的 start 必须被原样采信。
    """
    start = datetime(2026, 10, 5, 23, 45, 0)  # 快到第二天了，跨天也要算对
    assert compute_sla_deadline(WorkOrderPriority.P1, start) == datetime(
        2026, 10, 6, 0, 15, 0
    )
