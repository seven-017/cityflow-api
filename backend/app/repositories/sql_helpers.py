"""仓储层几个查询共用的 SQL 片段。

单独放一个文件，是为了不让仓储之间互相 import ——
labor.py 为了拿一个日期条件去 import work_orders.py，
读代码的人第一反应是"工时表和工单表有什么关系"，白绕一圈。
"""

from typing import Any

from sqlalchemy import ColumnElement, func, text


def trend_window(months: int) -> ColumnElement[Any]:
    """「只看最近 N 个月」这个条件，三个趋势图 + 平均处理周期都用它。

    起点交给数据库自己算：DATE_SUB(CURDATE(), INTERVAL N MONTH)。
    不在 Python 里算好日期再传进来，是因为那样得自己处理
    「今天是 3 月 31 号、往前一个月该算 2 月几号」这种破事（闰年还得单独想），
    数据库自己算不会错。

    N 是绑定参数，不是拼进字符串的 —— 这点特意验过（2026-10-04）：
    编出来是 date_sub(curdate(), INTERVAL %s MONTH)，pymysql 填进去就是
    INTERVAL 12 MONTH，MySQL 认这个写法，执行计划和写死字面量一模一样
    （两条都是 type=range、都走 ix_work_orders_request_date，
    16.1 ms vs 16.4 ms，差的那点全在噪声里）。
    所以这个函数可以放心收参数，"12"那个数字就放在 config 里，
    四个查询共用一个来源，换窗口只改一个地方。

    说清楚这个验证挡的是什么：要是不验、直接拼字符串，
    N 就成了一个能进 SQL 文本的值。现在它虽然是代码里的常量、不来自用户，
    但"常量拼 SQL"这个写法一旦成了习惯，下一个人往里塞变量是迟早的事。
    用绑定参数等于把这个口子焊死 —— 代价只是多验一次。

    真要说风险：这依赖 MySQL 允许 INTERVAL 后面跟占位符。
    哪天换数据库不认了，退回拼字符串也行，但拼的必须是代码里写死的整数。
    """
    return func.date_sub(
        func.curdate(),
        text("INTERVAL :months MONTH").bindparams(months=months),
    )
