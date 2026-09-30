from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import WorkOrder, WorkOrderStatusHistory


class WorkOrderRepository:
    """工单表的查询。

    跟 AssetRepository 基本是一个模子：游标分页 + 按主键查单条 + 数总数。
    但还是有区别，下面一条条说。

    这里千万别忘了：WorkOrder 模型上有两个指向 users 的 relationship。
    它们原来是 lazy="joined"，也就是每次查工单都会白搭两次 LEFT JOIN。
    实测那条 JOIN 会让优化器放弃主键顺序、改用 filesort，
    一个 LIMIT 21 的查询从 2.5 ms 变成 16614 ms。
    2026-09-29 已经把模型上那两处改了（细节写在 models/data.py 的注释里）。
    以后再往这张表加 relationship，注意同样的事别再犯一次。
    """

    def __init__(self, db: Session) -> None:
        self.db = db

    def list_work_orders(self, *, after_id: int | None, limit: int) -> list[WorkOrder]:
        """按 id 往后翻，一次取 limit 条（其实会多要一条，跟 assets 一样）。

        工单表 222 万行，比 assets 大 15 倍，所以分页这儿没有任何理由用 OFFSET。
        第 15 步在 assets 上量过：OFFSET 220 万行要 3349 ms，换成游标 0.9 ms。
        这里直接一步到位用游标，不重复踩那个坑了。
        """
        statement = select(WorkOrder)
        if after_id is not None:
            # 不传 after_id 就是第一页
            statement = statement.where(WorkOrder.id > after_id)
        # 多要一条用来判断"后面还有没有"，多出来的那条由 service 裁掉
        statement = statement.order_by(WorkOrder.id).limit(limit + 1)
        return list(self.db.execute(statement).scalars().all())

    def get_by_id(self, work_order_id: int) -> WorkOrder | None:
        # 走主键，最多命中一行。实测 1.6 ms，跟 assets 那边一样
        statement = select(WorkOrder).where(WorkOrder.id == work_order_id)
        return self.db.execute(statement).scalar_one_or_none()

    # 这里原来有个 count_work_orders()，是全项目最贵的单条查询，2026-09-29 删了。
    # 它当时量出来的数（keep 在这儿，因为这是"为什么删它"的证据）：
    #
    #     assets      148423 行  ->   16~23 ms
    #     work_orders 2220853 行 ->  322~358 ms
    #     同一条列表查询（游标取 21 行） ->  1.2~1.6 ms
    #
    # 也就是说这一个是列表查询的两百多倍，占了整个请求 437 ms 里的 330 ms（75%）。
    # 删掉它之后列表请求回到个位数毫秒。理由写在 schemas/common.py 的 CursorMeta 上。
    #
    # 记一笔当时排除的路子：本来说"上 Redis 缓存一下"，
    # 但缓存该给"确实需要、而且算起来贵"的东西用。这个数字不需要（游标分页跳不了页），
    # 也不值得为它引一整个 Redis 组件。真要看总量就该放 Dashboard 里缓存一次给整页复用。

    def add(self, work_order: WorkOrder) -> WorkOrder:
        """插一条工单。

        注意这里只 add 不 commit，提交时机交给 service ——
        跟 OperationLogRepository.add 那边一个道理：
        创建工单要同时写三张表（工单 + 状态流水 + 操作日志），
        得一起成功或者一起失败，中途谁都不能自己先提交一次。
        """
        self.db.add(work_order)
        return work_order

    def add_status_history(self, history: WorkOrderStatusHistory) -> None:
        """插一条状态流水。同样不 commit，理由见上面。"""
        self.db.add(history)
