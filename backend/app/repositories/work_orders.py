from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.models import WorkOrder, WorkOrderProcessingRecord, WorkOrderStatusHistory


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

    def list_status_history(self, work_order_id: int) -> list[WorkOrderStatusHistory]:
        """查一张单的流转流水，按 id 正序 —— 也就是这单一路走过来的顺序。

        为什么不分页：一张单的流水在业务上就多不了。建单 1 条，
        之后每流转一次加 1 条，走到 CLOSED 也就 5 条。
        哪天真有人把一张单折腾出几百条，那件事本身就该去查清楚，
        而不是先给它套个分页把问题盖住。

        排序用 id 而不是 created_at：created_at 只精确到秒，
        同一秒里连着做两个动作（脚本批处理很容易这样）顺序就乱了 ——
        而"谁先谁后"恰恰是流水唯一要表达的东西。
        架构文档里那句"默认排序使用稳定字段"，说的就是这种事。
        """
        statement = (
            select(WorkOrderStatusHistory)
            .where(WorkOrderStatusHistory.work_order_id == work_order_id)
            .order_by(WorkOrderStatusHistory.id)
        )
        return list(self.db.execute(statement).scalars().all())

    def list_processing_records(
        self, work_order_id: int
    ) -> list[WorkOrderProcessingRecord]:
        """查一张单的处理记录，同样按 id 正序。分页和排序的理由跟上面一样。"""
        statement = (
            select(WorkOrderProcessingRecord)
            .where(WorkOrderProcessingRecord.work_order_id == work_order_id)
            .order_by(WorkOrderProcessingRecord.id)
        )
        return list(self.db.execute(statement).scalars().all())

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

    def add_processing_record(self, record: WorkOrderProcessingRecord) -> None:
        """插一条处理记录。同样只 add 不 commit，理由见上面。

        这个跟 add_status_history 是两码事，别看名字像就合并：
        流水的每一行对应一次状态变化（所以有 from_status / to_status），
        处理记录是人随手写的备注（没有状态，只有一个 content）。
        合成一张表的话，就会有一半的列永远是 NULL。
        """
        self.db.add(record)

    def apply_transition(
        self,
        *,
        work_order_id: int,
        from_status: str,
        to_status: str,
        extra_values: dict[str, object] | None = None,
    ) -> int:
        """改状态，但只在"当前状态还是我以为的那一个"时才改。返回真改了几行。

        乐观锁就落在这一句 where 上。原来 service 那边是"先查出来、判断合法、
        再把对象的属性改掉"，判完到写库之间没人拦着，两个人同时点就会双双通过
        （2026-09-30 实测复现过：一个点开始一个点驳回，两条互斥的流水都写进去了）。
        现在把"我读到的那个状态"一起塞进 where：
        谁先提交，谁就把状态改走了，后到的那个 where 匹配不上、返回 0 行，
        调用方一看 0 就知道"我基于的那份判断已经过期了"。

        这跟加锁不是一回事。行锁能挡住"同时写"，挡不住"基于一个过期的状态做判断"——
        后到的人照样能拿到锁、照样能写，他只是不该写。要拦的是这个"不该"。

        两个 MySQL 的细节，都得记着：
        1. rowcount 是"真正改了内容的行数"，不是"匹配上的行数"
           （pymysql 默认没开 CLIENT_FOUND_ROWS）。所以这里能靠它判断，
           前提是这条 UPDATE 每次都确实改了东西 —— 好在状态机保证 from 和 to
           绝不会是同一个值（允许表里没有自环），所以 status 这一列必定变。
           哪天要是有人给这条语句加个"值没变就不改"的优化，这个判断就塌了。
        2. synchronize_session=False：不让 SQLAlchemy 顺手动 session 里那份对象。
           它默认会试着算一下"怎么把内存里的实例同步过去"，在带条件的 UPDATE 上
           那条路不一定对得上，算错了还不报错。我们只要行数，
           对象那份让调用方 refresh 一下，反而清楚。
        """
        values: dict[str, object] = {
            "status": to_status,
            # 状态来源顺手记成 PLATFORM：从这一刻起这个状态是人改出来的
            "status_origin": "PLATFORM",
        }
        if extra_values:
            # 完成要写完工日期、分派要写派给了谁，各自从这儿塞进来。
            # 用 dict 展开成列名是有意的：名字写错了 SQLAlchemy 编译时就炸，
            # 不会静默变成一个没人认识的属性
            values.update(extra_values)

        statement = (
            update(WorkOrder)
            .where(WorkOrder.id == work_order_id, WorkOrder.status == from_status)
            .values(**values)
            .execution_options(synchronize_session=False)
        )
        return self.db.execute(statement).rowcount
