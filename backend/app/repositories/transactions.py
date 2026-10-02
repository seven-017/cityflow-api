from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Transaction, TransactionDetail

# 明细那张表上跟 transaction_id 有关的索引名。硬编码到 SQL 里的东西，
# 单独拎出来放个常量，至少改名时能一眼搜到有几处引用。
DETAIL_TRANSACTION_INDEX = "ix_transaction_details_transaction_id"


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
