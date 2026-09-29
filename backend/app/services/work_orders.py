from sqlalchemy.orm import Session

from app.core.exceptions import NotFoundException
from app.models import WorkOrder
from app.repositories.work_orders import WorkOrderRepository
from app.schemas.common import CursorMeta
from app.schemas.work_orders import WorkOrderDetail, WorkOrderSummary


def work_order_summary(work_order: WorkOrder) -> WorkOrderSummary:
    """把一条 WorkOrder 搬成 WorkOrderSummary。

    跟 assets 那边一模一样的代价：ORM 对象不能直接往外扔，得手动一个个搬。
    这边字段名跟模型同名，看着像废话，但这是故意的 ——
    不这么写的话，哪天想改个对外名字（比如把 source_record_id 叫成 work_order_no）
    就得连着模型一起动，那就不是"挑字段"而是"改数据库"了。
    """
    return WorkOrderSummary(
        id=work_order.id,
        source_record_id=work_order.source_record_id,
        data_source=work_order.data_source,
        description=work_order.description,
        work_type=work_order.work_type,
        status=work_order.status,
        request_date=work_order.request_date,
        completion_date=work_order.completion_date,
    )


def work_order_detail(work_order: WorkOrder) -> WorkOrderDetail:
    """把一条 WorkOrder 搬成 WorkOrderDetail。

    这已经是第三个这种搬运函数了（asset_summary / asset_detail / 这个）。
    三份长得几乎一样的东西摆在这儿，说好听点叫"每个视图互不干扰"，
    说难听点就是啰嗦。暂时不动 —— 真要收拾，应该是等第 19、20 步都做完，
    看看总共有几个视图，再决定是抽个基类还是干脆别抽。
    现在三个还看不出规律，提前抽反而抽错。
    """
    return WorkOrderDetail(
        id=work_order.id,
        source_record_id=work_order.source_record_id,
        data_source=work_order.data_source,
        asset_id=work_order.asset_id,
        asset_source_record_id=work_order.asset_source_record_id,
        description=work_order.description,
        work_type=work_order.work_type,
        work_class=work_order.work_class,
        status=work_order.status,
        status_origin=work_order.status_origin,
        source_status=work_order.source_status,
        request_date=work_order.request_date,
        created_source_at=work_order.created_source_at,
        completion_date=work_order.completion_date,
        scheduled_end_date=work_order.scheduled_end_date,
        assigned_title=work_order.assigned_title,
        source_notes=work_order.source_notes,
        duration=work_order.duration,
        job_type=work_order.job_type,
        source_update_count=work_order.source_update_count,
        created_at=work_order.created_at,
        updated_at=work_order.updated_at,
    )


class WorkOrderService:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.work_orders = WorkOrderRepository(db)

    def list_work_orders(
        self, *, after_id: int | None, limit: int
    ) -> tuple[list[WorkOrderSummary], CursorMeta]:
        # 这里原来第一句是 total = self.work_orders.count_work_orders()，2026-09-29 删了。
        # 那一下是 322~358 ms，占整个请求的 75% —— 接口慢就慢在这一句上。
        # 为什么干脆不报总数，理由写在 schemas/common.py 的 CursorMeta 上。
        rows = self.work_orders.list_work_orders(after_id=after_id, limit=limit)
        has_more = len(rows) > limit
        # 多要的那条只是探路的，不能发出去
        page_rows = rows[:limit]
        next_cursor = page_rows[-1].id if has_more and page_rows else None
        items = [work_order_summary(w) for w in page_rows]
        return items, CursorMeta(
            limit=limit,
            next_cursor=next_cursor,
            has_more=has_more,
        )

    def get_work_order(self, work_order_id: int) -> WorkOrderDetail:
        """查单条，查不到就 404。

        这里比 assets 那边多啰嗦一句：工单是有状态流转的东西，
        按理说详情页该把流转记录（work_order_status_history）和
        处理记录（work_order_processing_records）一起带出来。

        现在没带，原因是那两张表实测都是 0 行 —— 官方导入的数据里
        一条流转记录都没有（那是平台自己流转时才写的）。
        给一个永远是空的数组留个字段位，没意义。
        第 18 步做完状态机，这两张表才有数据，到那时候再加。
        """
        work_order = self.work_orders.get_by_id(work_order_id)
        if work_order is None:
            raise NotFoundException(f"Work order {work_order_id} not found.")
        return work_order_detail(work_order)
