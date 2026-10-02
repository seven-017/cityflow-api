from typing import NamedTuple

from sqlalchemy import case, func, select, update
from sqlalchemy.orm import Session

from app.core.work_order_status import (
    FINISHED_STATUSES,
    REJECTED_STATUSES,
    UNFINISHED_STATUSES,
)
from app.models import WorkOrder, WorkOrderProcessingRecord, WorkOrderStatusHistory


class WorkOrderStatusCounts(NamedTuple):
    """一次聚合查回来的四个数。

    用 NamedTuple 而不是裸元组，理由很实在：这是四个同类型的 int，
    拆包时顺序错一个，编译器不会吭声，界面上却会显示"未完结 2065995"这种鬼话。
    带上名字之后调用方写 total, unfinished, finished, rejected = ...，
    一眼能看出对不对（跟上面那几处 tuple 返回值不一样，
    那些是两三个不同类型的值，混不了）。
    """

    total: int
    unfinished: int
    finished: int
    rejected: int


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

    def count_by_status_group(self) -> WorkOrderStatusCounts:
        """一次查出工单总数 + 未完结 / 已完成 / 已退回三个桶。

        为什么要一次查、不查四次：做过对照实验，不是拍的
        （2026-10-02 裸 SQL，各跑 3 次取中位数）：

            四个 COUNT 分开查
                总数 COUNT(*)                     248.7 ms
                未完结 IN (PENDING,ASSIGNED,...)   12.9 ms   type=range
                已完结 IN (COMPLETED,CLOSED)     1017.6 ms   type=range
                已退回 = 'REJECTED'                25.1 ms   type=range
                四次加起来                       1304.3 ms

            一次条件聚合（同样四个数，一条 SQL）
                1143.4 ms
                EXPLAIN: type=index key=ix_work_orders_status
                         rows=2158704 Extra=Using index

        ⇒ 1143.4 vs 1304.3，一次聚合快 1.14 倍。
        （同一天早上量过一次是 991.9 vs 1329.9，1.34 倍 —— 绝对值在抖，
        但"一次更快"这个方向两次都一样，所以结论是稳的。）

        赢的地方不在"索引用得好"，在少扫几铺：四条 SQL 要四次从头翻表，
        一条 SQL 只翻一次。那个 Extra=Using index 说明它连回表都不用，
        直接在 ix_work_orders_status 上扫完就够（count 要的 id 和筛选要的 status
        都在这棵索引里）。

        顺带记一个反直觉的数：'已完结' 那一条要 1017.6 ms，比全表扫（248.7 ms）还慢四倍。
        原因是 COMPLETED 占了 93.03% 的行 —— 走索引查一个"几乎每行都满足"的条件，
        等于随机跳着读全表，还不如老老实实从头顺序读回去。
        索引不是越多越好用，选择性别太差才是关键。

        还有个坑得记着：EXPLAIN 里 rows=2158704 是估算值，不是实际扫了多少行，
        别拿它当耗时看（这个数在 assets 那边也写了一次，因为老有人忘）。

        这儿没用 FORCE INDEX，跟 transactions 那边不一样。
        那边必须 FORCE 是因为 `id > 0` 这种筛不掉任何数据的条件把优化器带偏了；
        这条 SQL 上没有任何 WHERE，优化器没有可偏的地方，
        量出来的计划（走 status 索引、Using index）已经是好的了。

        SUM(...) 在空表上返回 NULL（不是 0），所以下面每个数都要过一遍 int(x or 0)。
        现在这张表 222 万行不可能空，但"不可能"跟"不会"是两回事，
        而且这种 NULL 一旦漏进去，Pydantic 那边会因为拿不到 int 直接 500。
        """
        statement = select(
            func.count(WorkOrder.id),
            # 这三个为什么写成 SUM(CASE WHEN ... THEN 1 ELSE 0 END)，
            # 而不是更短的那个 SUM(status IN (...)) —— 这里踩过一个静默错值的坑，
            # 记下来免得以后有人"顺手简化"又踩一遍：
            #
            # 一开始写的就是 func.sum(WorkOrder.status.in_(...))，SQL 编出来一字不差就是
            # SUM(status IN (...))，MySQL 也算得对（未完结 25196）。但拿回来的是 1。
            # 三个桶全是 1，而总数 2220853 是对的 —— 光看总数根本看不出问题。
            #
            # 根因在 SQLAlchemy 的返回处理，不在 SQL：func.sum() 不知道参数是布尔表达式，
            # 就照着参数的类型推断这一列是 Boolean，于是把 MySQL 算出来的 25196
            # 过了一遍 bool() 变成 True，int(True) 就是 1。
            # 换句话说，SQL 层对的、Python 层被改掉了，中间没有任何报错。
            #
            # 怎么发现的：验收脚本里有一条「未完结 + 已完成 + 已退回 = 总数」——
            # 3 ≠ 2220853，当场红。这也说明那条等式断言不是摆设。
            #
            # 修法有两种：给 SUM 套一个 cast(Integer)，或者换成 CASE。
            # 选 CASE 是因为它不依赖 MySQL"布尔当 1/0 用"这个隐式行为，
            # 类型是明摆着的整数。代价是 SQL 比原来长一点，执行计划一样是全表扫。
            func.sum(
                case((WorkOrder.status.in_(UNFINISHED_STATUSES), 1), else_=0)
            ),
            func.sum(case((WorkOrder.status.in_(FINISHED_STATUSES), 1), else_=0)),
            func.sum(case((WorkOrder.status.in_(REJECTED_STATUSES), 1), else_=0)),
        )
        total, unfinished, finished, rejected = self.db.execute(statement).one()
        return WorkOrderStatusCounts(
            total=int(total or 0),
            unfinished=int(unfinished or 0),
            finished=int(finished or 0),
            rejected=int(rejected or 0),
        )

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
