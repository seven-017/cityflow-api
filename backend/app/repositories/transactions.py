from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Transaction, TransactionDetail

# 明细那张表上跟 transaction_id 有关的索引名。硬编码到 SQL 里的东西，
# 单独拎出来放个常量，至少改名时能一眼搜到有几处引用。
DETAIL_TRANSACTION_INDEX = "ix_transaction_details_transaction_id"

# 交易头表上按工单过滤用的索引名。道理同上：写死的索引名要有个地方能搜。
WORK_ORDER_INDEX = "ix_transactions_work_order_id"


class TransactionRepository:
    """物料交易两张表的查询：头（transactions）和明细（transaction_details）。

    两张表放一个仓储里，跟别处"一个表一个仓储"的切法不一样，所以说一句：
    明细这张表没有独立存在的意义 —— 它永远是"某张交易单的明细"，
    查它必然带着 transaction_id。也就是说这两张表在业务上是一件事，
    拆成两个仓储只会让 service 每次都得同时 new 出两个来。
    （labor 那边只有一张表，所以没这个问题。）

    整个项目里只有这一层允许出现 select()。
    """

    def __init__(self, db: Session) -> None:
        self.db = db

    def get_by_id(self, transaction_id: int) -> Transaction | None:
        """按主键查交易头。

        走主键索引，75 万行里命中最多一行，实测 0.61 ms。
        用 scalar_one_or_none 而不是 first()：主键上万一真命中两行（说明数据出问题了），
        前者会直接报错，后者会闷头给你第一条。这种地方宁可直接炸。
        """
        statement = select(Transaction).where(Transaction.id == transaction_id)
        return self.db.execute(statement).scalar_one_or_none()

    def count_transactions(self) -> int:
        """数交易头有多少张单。

        2026-10-02 实测：752746 张，COUNT 86.2 ms。
        比 assets（17.7 ms）贵是因为表大五倍（75 万 vs 14.8 万），
        跟数据本身有关，不是查询写歪了，不用动它。
        """
        return int(self.db.execute(select(func.count(Transaction.id))).scalar_one())

    def count_transaction_details(self) -> int:
        """数明细一共有多少行。

        2026-10-02 实测：2290091 行，COUNT 1361 ms —— 是这套指标里第二贵的
        （最贵的是 labor 那个合计 3257.5 ms）。

        在"指标汇总"里放这个数，值不值当，说清楚免得以后有人来问：
        它唯一的用处是让人看见明细这一层的量级（229 万行，是头的三倍）——
        也就是"一张单平均三行多一点"这件事的数字来源。
        真嫌它贵想砍掉的话，砍了就是 —— 它不像"未完结"那种数还有人拿去做决定，
        它纯粹是个规模展示。留着的原因是这一整套指标算完一次要缓存的，
        砍掉它只省掉 1361 / 5962 ≈ 23% 的冷启动时间，代价是首页少一块信息。
        这个取舍是拍过脑袋的，不是漏想的。
        """
        return int(
            self.db.execute(select(func.count(TransactionDetail.id))).scalar_one()
        )

    def list_transactions(
        self,
        *,
        after_id: int | None,
        limit: int,
        work_order_id: int | None = None,
    ) -> list[Transaction]:
        """按 id 往后翻，一次取 limit 条（其实会多要一条，见下面）。

        这是本仓库第四个列表查询（assets / work_orders / labor / 这个），
        分页的骨头跟它们一样：游标不用 OFFSET，多要一条探路。
        但每次都得重新量一遍，因为表不一样、坑不一样。2026-10-02 实测
        （各跑 5 次取中位数，75 万行）：

            WHERE id > 0          ORDER BY id LIMIT 21  ->     0.45 ms
            WHERE id > 410000     ORDER BY id LIMIT 21  ->     0.47 ms
            对照 LIMIT 21 OFFSET 0                      ->     0.46 ms
            对照 LIMIT 21 OFFSET 700000                 ->   919.69 ms

        最后一组是对照：同样 21 行，OFFSET 要 0.92 秒。
        EXPLAIN 里 OFFSET 那条 type=index、rows=700021 —— 它真的是"从头一行行走，
        走过 70 万行全丢掉再取 21 行"。游标那条 0.47 ms。
        ⇒ 919.69 / 0.47 差不多 1966 倍。
        （assets 上量到 3700 倍、labor 上 7300 倍、这儿 1966 倍 ——
        差这么多不是表小，是因为这三张表的主键密度和行宽不一样，
        OFFSET 的代价本来就跟"要走多少行"绑定。数字不一样不代表哪个是错的。）

        一句题外话：OFFSET 那条 rows 写着 700021，看着像"扫了 70 万行所以慢"，
        对，它就是真的扫了。但反过来看前面那些游标条的 rows 也写着 373078、
        却只要 0.45 ms —— 因为 LIMIT 21 到了就停。所以 rows 是估算，别拿它当耗时看。

        ---------------------------------------------------------------
        按工单过滤的 FORCE INDEX（跟明细那个坑是同一个坑，但结论要重写）：

        不传 work_order_id 就是全表翻页，走 PRIMARY，没什么可说的。
        传了 work_order_id 就得走另一个索引，这儿出了跟明细一样的岔子 ——
        只要语句里带上 `id > 0`（也就是翻到第二页之后），优化器就走 index_merge：

            A 带 id>0（不加 FORCE）   1.62 ms  type=index_merge  Using intersect(...)
            B 带 id>0 + FORCE         0.44 ms  type=range        Using index condition

        ⇒ 快 3.7 倍。原理跟明细那次一模一样（`id > 0` 筛不掉任何一行，
        但优化器为了用它放弃了本来就用得上的索引），不再重复。

        但有一处跟明细不一样，值得单独记，因为它反直觉：

            C 不带 id>0（第一页真实形状）  0.60 ms  type=ref    <- 本来就快
            D 不带 id>0 + FORCE            0.53 ms  type=ref

        第一页根本不需要 FORCE —— 0.60 ms 已经够好。坑只在翻页时出现。
        那为什么不写成"只在带 after_id 时才 FORCE"？两个理由：

          1. 一个仓库方法里出现两种执行计划，读代码的人得先想"这次走的哪种"。
             而 FORCE 之后第一页也没变慢（0.60 -> 0.53，还在噪声范围内），
             那就统一 FORCE，少一个分支。
          2. 第一页快是因为它碰巧不带 id>0。可"碰巧"这种东西，
             SQLAlchemy 生成条件时一个 `if` 的写法变化就没了。
             与其赌它，不如定死。

        代价跟明细那次一样：索引名写死在 SQL 里，谁把这索引改名或删了，
        这条查询报 MySQL 1176 当场炸，不会静默走回慢 3.7 倍的计划。
        用 WORK_ORDER_INDEX 常量引着，改名时搜得到。
        """
        statement = select(Transaction)
        if work_order_id is not None:
            # 不传就是"全部交易"，不加工单条件
            statement = statement.with_hint(
                Transaction,
                f"FORCE INDEX ({WORK_ORDER_INDEX})",
                "mysql",
            ).where(Transaction.work_order_id == work_order_id)
        if after_id is not None:
            # 不传 after_id 就是第一页
            statement = statement.where(Transaction.id > after_id)
        # 多要一条探路，多出来的那条由 service 裁掉，不会发到前端
        statement = statement.order_by(Transaction.id).limit(limit + 1)
        return list(self.db.execute(statement).scalars().all())

    def list_details(
        self,
        *,
        transaction_id: int,
        after_id: int | None,
        limit: int,
    ) -> list[TransactionDetail]:
        """查一张交易单的明细，按 id 往后翻，一次取 limit 条（会多要一条）。

        这儿的分页不是抄 labor 那边的，是「被两条独立的证据逼出来的」：

        证据一，行数。2026-10-02 量的：741245 张有明细的单里，
            最短 1 行、平均 3.09 行、「最长 3628 行」，
            超过 10 行的有 41325 张（5.6%）。
        证据二，体积。把那 3628 行序列化成 JSON 是 812932 字节（约 800 KB），
            而 20 行只有 4393 字节 —— 一次全发是 20 行的 185 倍。

        所以这个接口从一开始就得带分页，不是"以后数据多了再说"：
        数据现在就在那儿，已经不是"以后"了。
        文档 api.md 里写的是"返回交易头信息和逐行物料明细"，读起来像要一次全给；
        这一版没照做，理由就是上面那个 3628。

        绝大多数单（71.5% 只有 1 行）第一页就够了，多一个游标不影响它们；
        真正需要翻页的是剩下那 5.6%。

        排序用 id 不用 transaction_date：跟 labor 那边一个道理，
        同一张单的明细本来就是同一天的多，靠日期排不出稳定顺序。
        更直接的证据在 schemas/transactions.py 里（明细的日期跟头不一样的有 89989 行），
        但那是"两列要不要都留"的问题，跟排序无关 —— 排序要的是唯一且递增，id 才是。

        ---------------------------------------------------------------
        FORCE INDEX 是怎么回事（这段是本仓库里少数几处硬编码索引的地方，
        所以把来龙去脉写全）：

        最初这一版没加 hint，写完跑验收时发现一个很难看的东西 ——
        「分页居然比不分页还慢」。同一张 3628 行明细的单（id=663966）：

            一次全拿 WHERE transaction_id=? ORDER BY id              25.16 ms
            第一页  WHERE transaction_id=? AND id>0 ORDER BY id LIMIT 21   143.47 ms

        分页取 21 行反而比取 3628 行慢 5 倍，那就不可能是数据量的问题，
        只能是执行计划选错了。EXPLAIN 一对就明白了：

            不加 id>0 ： type=ref             key=ix_..transaction_id        Extra=(空)
            加了 id>0 ： type=index_merge     key=ix_..transaction_id,PRIMARY
                                             Extra=Using intersect(...); Using filesort

        `id > 0` 这个条件一个数据都筛不掉（明细 id 全大于 0，最小值是 203），
        但优化器看见"主键上也有个范围条件"，就把两个索引取交集（index_merge）——
        交出来还是那 3628 行，然后再 filesort 排一遍。白干一趟。
        换句话说：「它为了用一个没有选择性的条件，放弃了那个本来已经有序的索引。」

        对照组（同一个查询，只多一句 FORCE INDEX）：

            加 id>0 + FORCE(transaction_id)  ->  0.51 ms   type=range
                                                 Extra=Using index condition

        ⇒ 143.47 -> 0.51，快 281 倍。这就证明是「优化器选错计划，不是索引不存在」。
        （如果 FORCE 之后一样慢，那说明索引压根没被用上，方向就完全不同了 ——
        所以这个对照必须做，不能只看到"慢"就去加索引。）

        FORCE 之所以成立，是因为 `ix_transaction_details_transaction_id` 是
        InnoDB 的二级索引，叶子节点上还挂着主键。所以它内部其实是
        (transaction_id, id) 有序的 —— 定死 transaction_id 之后，
        顺着它读出来天然就是按 id 排好的，filesort 那一步根本不需要。
        这个查询的 WHERE 里必然有 transaction_id（不传就没有"哪张单的明细"可言），
        所以强制走这个索引不会误伤别的查询形态。

        代价说清楚：索引名被写死在 SQL 里了。将来谁把这个索引改名或者删掉，
        这条查询会报 MySQL 错误 1176（key doesn't exist）「当场炸」，不会静默走回慢计划。
        这个代价能接受 —— 炸了看得见，比悄悄慢 281 倍强。
        用 DETAIL_TRANSACTION_INDEX 这个常量引用它，也是为了改名时能搜得到。
        """
        statement = (
            select(TransactionDetail)
            .with_hint(
                TransactionDetail,
                f"FORCE INDEX ({DETAIL_TRANSACTION_INDEX})",
                "mysql",
            )
            .where(TransactionDetail.transaction_id == transaction_id)
        )
        if after_id is not None:
            # 不传 after_id 就是明细的第一页
            statement = statement.where(TransactionDetail.id > after_id)
        # 多要一条探路，多出来的那条由 service 裁掉，不会发到前端
        statement = statement.order_by(TransactionDetail.id).limit(limit + 1)
        return list(self.db.execute(statement).scalars().all())
