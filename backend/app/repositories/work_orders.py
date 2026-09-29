from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import WorkOrder


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

    def count_work_orders(self) -> int:
        """数总数。

        这一下是全项目最贵的单条查询。实测（2026-09-29）：

            assets      148423 行  ->   16~23 ms
            work_orders 2220853 行 ->  322~358 ms（同一批里复测过，抖动 ±11%）

        EXPLAIN 显示它 type=index，走的是 ix_work_orders_request_date
        而不是主键 —— 因为 MySQL 会挑一条"足够便宜"的二级索引来数，
        数索引比数整张表便宜（不用回表）。那条索引存的是 date(3 字节)+主键，
        比主键的聚簇索引（整行都塞在里面）窄得多。

        代价大不大？跟列表查询本身比一下就知道：
            列表查询（游标翻页，21 行）  1.2~1.6 ms
            COUNT(*)                    322~358 ms
        差了两百多倍。也就是说分页接口本来很轻，是 total 把它拉重的。

        四个候选（不报 total / 只第一页算 / 上缓存 / 用 information_schema
        的估算值）的代价都量过，还没定用哪个。
        这一版先跟 assets 保持一致：每次都算。等定了再单独改一次。
        """
        return int(self.db.execute(select(func.count(WorkOrder.id))).scalar_one())
