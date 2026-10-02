from sqlalchemy.orm import Session

from app.core.exceptions import NotFoundException
from app.models import Transaction
from app.repositories.transactions import TransactionRepository
from app.schemas.common import CursorMeta
from app.schemas.transactions import TransactionDetail, TransactionLineItem

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


class TransactionService:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.transactions = TransactionRepository(db)

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
