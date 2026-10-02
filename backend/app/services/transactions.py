from sqlalchemy.orm import Session

from app.core.exceptions import NotFoundException
from app.models import Transaction
from app.repositories.transactions import TransactionRepository
from app.schemas.common import CursorMeta
from app.schemas.transactions import (
    TransactionDetail,
    TransactionLineItem,
    TransactionSummary,
)

# 模型和 schema 撞名了，得分开叫。
#   app.models.TransactionDetail           一条明细行（对应 transaction_details 一行）
#   app.schemas.transactions.TransactionDetail   交易详情（头 + 一页明细 + 游标）
# 名字撞上是因为两边都各叫各的合理：模型那边"明细"就是一行，
# schema 那边"详情"就是整个返回体。与其为了避让把其中一个改成别扭的名字，
# 不如在这儿加个别名，把区别写清楚。
from app.models import TransactionDetail as TransactionDetailRow


def transaction_line_item(row: TransactionDetailRow) -> TransactionLineItem:
    """把一条 TransactionDetail（明细行）搬成 TransactionLineItem。

    第五个搬运函数了（asset_summary / asset_detail / work_order_summary /
    work_order_detail / labor_summary / 这个）。规矩一直没变：
    ORM 对象不能直接往外扔，要发的字段一个个搬过来。
    """
    return TransactionLineItem(
        id=row.id,
        source_record_id=row.source_record_id,
        transaction_source_record_id=row.transaction_source_record_id,
        line_number=row.line_number,
        transaction_date=row.transaction_date,
        part_code=row.part_code,
        part_description=row.part_description,
        part_class=row.part_class,
        part_uom=row.part_uom,
    )


def transaction_detail(
    transaction: Transaction,
    *,
    details: list[TransactionDetailRow],
    detail_meta: CursorMeta,
) -> TransactionDetail:
    """把交易头 + 一页明细一起搬成 TransactionDetail。

    明细和游标从外面传进来，不在这个函数里自己查：它是个纯函数，
    手里没有 db 也拿不到仓储。查库是 service 的事，搬字段是这儿的事。
    （跟 work_order_detail 一样的切法。）
    """
    return TransactionDetail(
        id=transaction.id,
        source_record_id=transaction.source_record_id,
        data_source=transaction.data_source,
        work_order_id=transaction.work_order_id,
        source_work_order_record_id=transaction.source_work_order_record_id,
        description=transaction.description,
        transaction_type=transaction.transaction_type,
        transaction_date=transaction.transaction_date,
        status=transaction.status,
        from_entity=transaction.from_entity,
        from_code=transaction.from_code,
        to_entity=transaction.to_entity,
        to_code=transaction.to_code,
        source_update_count=transaction.source_update_count,
        source_created_at=transaction.source_created_at,
        source_updated_at=transaction.source_updated_at,
        details=[transaction_line_item(r) for r in details],
        detail_meta=detail_meta,
    )


def transaction_summary(row: Transaction) -> TransactionSummary:
    """把一条 Transaction 搬成 TransactionSummary。

    第六个搬运函数了（asset_summary / asset_detail / work_order_summary /
    work_order_detail / labor_summary / 这个）。规矩一直没变：
    ORM 对象不能直接往外扔，要发的字段一个个搬过来。
    """
    return TransactionSummary(
        id=row.id,
        source_record_id=row.source_record_id,
        data_source=row.data_source,
        work_order_id=row.work_order_id,
        source_work_order_record_id=row.source_work_order_record_id,
        description=row.description,
        transaction_type=row.transaction_type,
        transaction_date=row.transaction_date,
        status=row.status,
        from_entity=row.from_entity,
        from_code=row.from_code,
        to_entity=row.to_entity,
        to_code=row.to_code,
    )


class TransactionService:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.transactions = TransactionRepository(db)

    def list_transactions(
        self,
        *,
        after_id: int | None,
        limit: int,
        work_order_id: int | None = None,
    ) -> tuple[list[TransactionSummary], CursorMeta]:
        """翻页查交易。仓库层多要一行探路，这儿看它有没有多给，多出来那行裁掉。

        这个方法是本仓库第四个列表（assets / work_orders / labor / 这个），
        前三段说明（没 total / 工单不存在不 404）跟 labor 那边一字不差，不重复写。

        要展开写的是第四段：没做哪些过滤条件，以及为什么不做的理由
        跟 labor 那边根本不是同一套。

        文档 api.md 里 GET /transactions 列了 10 个参数：
            keyword / transaction_type / status / work_order_id /
            asset_id / date_from / date_to / sort_by / sort_order / page / page_size
        这一版只做了 2 个：work_order_id、（page/page_size 换成了游标 after_id）。
        剩下 8 个都没做，但它们是三个不同的原因，别混着说：

        (一) 表结构上就做不了 —— asset_id
            跟 labor 那边一模一样的理由：transactions 这张表上压根没有 asset_id
            这一列。要按资产过滤只能 JOIN work_orders（222 万行）再拿 w.asset_id 比。
            不是不能做，是"为了一列去连一张两百万行的表"这个代价，
            得先有个非做不可的页面需求才谈得上。

        (二) 有索引撑着、做起来不贵，但当前没有消费方 —— status / transaction_type
            / date_from / date_to / keyword

            这一条是跟 labor 最大的不同。labor 那张表上没索引，所以我写的理由是
            "320 万行做 LIKE 全扫快不了"。这儿不能照抄，因为这张表的索引底子好得多，
            数据库里就有：ix_transactions_status、ix_transactions_transaction_date、
            description 上还有个 FULLTEXT 叫 ix_transactions_search。
            （这几个索引是建表时就有的，不是这一版加的。）

            而且实测也支持"能快"（2026-10-02）：
                status='A'（74 万行）         0.56 ms   （不加 FORCE 就行，走 PRIMARY）
                status='U'（只有 500 行）     2.44 ms   （index_merge，加 FORCE 后 0.59 ms）
                transaction_type='RECV'       0.52 ms
                work_order_id + status 一起   0.45 ms
            最坏也就是 2.44 ms 那个，加一句 FORCE 就压到 0.59。

            ⇒ 所以理由是：做得起，但现在没人要。
            这一版的列表接口只服务一个真实场景 —— 工单详情页要显示
            "这张维修单动过哪些料"，所以 work_order_id 做了。
            status / transaction_type 这类是"筛选项"，得有前端那个筛选面板
            提出需求才知道要做成什么样（单选还是多选？要不要跟 keyword 组合？），
            现在做就是替还没画的界面猜需求。

            顺带把这几个"以后要做"的账记清楚，省得下次从零量：
              - status 过滤将来要做，必须带 FORCE INDEX(ix_transactions_status)，
                否则 status='U' 这种低频值会掉进 index_merge（2.44 -> 0.59 ms）
              - keyword 有 FULLTEXT 索引，但 InnoDB 的全文检索有最小词长限制
                （innodb_ft_min_token_size 默认 3），而且这几个 description 值
                都是 'Stock initialization' 这种英文短语，真做之前得先量一下
                全文索引到底命中不命中，别看着有索引就以为能用
              - date_from / date_to 有索引，但它是范围条件，配上 id 游标排序后
                大概率又要 index_merge —— 跟 status 那边一样，做之前先量

        (三) 是另一种接口的活，不该塞进列表 —— sort_by / sort_order
            这个列表的排序是 id（游标分页的前提：排序列必须唯一且递增，
            不然翻页会漏行或重行）。让人按 transaction_date 排，
            就撞上"同一天的单几千笔、日期排不出稳定顺序"这个问题，
            而解决它得靠 (transaction_date, id) 这种复合排序 ——
            那已经不是"加个参数"了，是换一套分页。而且 98% 的场景
            就是"按时间倒序看最近的"，按 id 排本来就等价于它。

        最后一句：这一版没做的比做了的多，这是有意的。
        不是"文档列了我就得挨个实现"，是"文档列的是用户可能想干什么，
        实现的是现在真有人要干什么"。这两者中间差着一个前端界面。
        """
        # 仓库层故意多要了一行，这里看它到底有没有多给
        rows = self.transactions.list_transactions(
            after_id=after_id, limit=limit, work_order_id=work_order_id
        )
        has_more = len(rows) > limit
        # 多出来那一条只是用来探测"还有没有下一页"的，不能发给前端
        page_rows = rows[:limit]
        # 下一页从哪开始？就是这一页最后那条的 id。
        # has_more 为假的时候给 None，让前端一眼看出到底了
        next_cursor = page_rows[-1].id if has_more and page_rows else None
        items = [transaction_summary(r) for r in page_rows]
        return items, CursorMeta(
            limit=limit,
            next_cursor=next_cursor,
            has_more=has_more,
        )

    def get_transaction(
        self,
        *,
        transaction_id: int,
        detail_after_id: int | None,
        detail_limit: int,
    ) -> TransactionDetail:
        """查一张交易单 + 它的第一页（或下一页）明细。查不到就 404。

        一共两条 SQL，固定两条，跟明细有几行没关系：
            1. 按主键查头（走 PRIMARY）
            2. 按 transaction_id + 游标查一页明细（走 transaction_id 索引）
        换句话说明细是"一次查一页"而不是"查头、然后每行再查一次" ——
        这就是防 N+1 的全部内容。这一条特别值得说，因为 transaction_details
        上有 2290091 行，真写成 N+1（1 + 3628 条查询）会当场看出来。

        没做的事，明说：

        1. 头不存在时是 404，不是空对象。跟 get_asset 一个口径 ——
           404 是接口层面的语义，前端按状态码分支比按"data 是不是空"去猜要清楚。
           注意这儿和"明细是空的"是两回事：单子存在但没有明细，
           那是 200 + details=[]，不是 404。实测这种情况确实有
           （752746 张单里有 741245 张有明细，剩下 11501 张是空的）。
           ⇒ 也就是说"查一张没有明细的单"必须能正常返回，不能报错。

        2. 没写操作日志。跟 assets / work-orders 的只读接口一个态度：
           只读接口要不要留痕是个产品决定，真要做也是所有只读接口一起做，
           单独给交易详情开个特例没意义。

        3. 头字段里没带 request_number（78.63% 是空的），理由写在 schema 上。
        """
        transaction = self.transactions.get_by_id(transaction_id)
        if transaction is None:
            raise NotFoundException(f"Transaction {transaction_id} not found.")

        # 仓库层故意多要了一行，这里看它到底有没有多给
        rows = self.transactions.list_details(
            transaction_id=transaction.id,
            after_id=detail_after_id,
            limit=detail_limit,
        )
        has_more = len(rows) > detail_limit
        # 多出来那一条只是用来探测"还有没有下一页"的，不能发给前端
        page_rows = rows[:detail_limit]
        # 下一页从哪开始？就是这一页最后一条明细的 id。
        # has_more 为假的时候给 None，让前端一眼看出明细到底了
        next_cursor = page_rows[-1].id if has_more and page_rows else None

        return transaction_detail(
            transaction,
            details=page_rows,
            detail_meta=CursorMeta(
                limit=detail_limit,
                next_cursor=next_cursor,
                has_more=has_more,
            ),
        )
