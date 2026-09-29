from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.deps import get_db, require_permissions
from app.core.permissions import PermissionCode
from app.models import User
from app.schemas.common import ApiResponse, CursorResponse
from app.schemas.work_orders import WorkOrderDetail, WorkOrderSummary
from app.services.work_orders import WorkOrderService

router = APIRouter()


@router.get("", response_model=ApiResponse[CursorResponse[WorkOrderSummary]])
def list_work_orders(
    db: Annotated[Session, Depends(get_db)],
    # 权限用的是 work_order:read，跟 asset:read 是两个独立的权限点。
    # 库里那 13 个权限点早就定好了，这里只是把它接上
    _: Annotated[User, Depends(require_permissions(PermissionCode.WORK_ORDER_READ))],
    # 跟资产列表一样走游标：拿上一页的 meta.next_cursor 当这次的 after_id 传回来
    after_id: int | None = Query(None, ge=1),
    limit: int = Query(20, ge=1, le=100),
) -> ApiResponse[CursorResponse[WorkOrderSummary]]:
    items, meta = WorkOrderService(db).list_work_orders(after_id=after_id, limit=limit)
    return ApiResponse(data=CursorResponse(items=items, meta=meta))


@router.get("/{work_order_id}", response_model=ApiResponse[WorkOrderDetail])
def get_work_order(
    work_order_id: int,
    db: Annotated[Session, Depends(get_db)],
    # 详情跟列表同一个权限。工单的"看"和"改"是分开的权限点，
    # 看只需要 WORK_ORDER_READ，改是 WORK_ORDER_UPDATE（第 18 步才用得上）
    _: Annotated[User, Depends(require_permissions(PermissionCode.WORK_ORDER_READ))],
) -> ApiResponse[WorkOrderDetail]:
    # work_order_id 是路径参数，FastAPI 自己转 int，传 abc 会甩 422
    return ApiResponse(data=WorkOrderService(db).get_work_order(work_order_id))
