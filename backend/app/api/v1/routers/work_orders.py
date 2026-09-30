from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request, status
from sqlalchemy.orm import Session

from app.api.deps import get_db, require_permissions
from app.core.permissions import PermissionCode
from app.models import User
from app.schemas.common import ApiResponse, CursorResponse
from app.schemas.work_orders import (
    WorkOrderCreateRequest,
    WorkOrderDetail,
    WorkOrderSummary,
)
from app.services.work_orders import WorkOrderService

router = APIRouter()


@router.post(
    "",
    response_model=ApiResponse[WorkOrderDetail],
    # 创建资源返 201 而不是默认的 200。这不是洁癖 ——
    # 前端看状态码就能分清"新建成功"和"改了点什么成功"，不用去解析返回体
    status_code=status.HTTP_201_CREATED,
)
def create_work_order(
    payload: WorkOrderCreateRequest,
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    # 这个依赖前面不加下划线，因为创建工单要记"是谁录的"
    # （写进 created_by_id，也写进操作日志）
    operator: Annotated[
        User,
        Depends(require_permissions(PermissionCode.WORK_ORDER_CREATE)),
    ],
) -> ApiResponse[WorkOrderDetail]:
    # 工单的写接口到这儿才算开张，权限点跟读是分开的：
    # ENGINEER 和 VIEWER 都没有 work_order:create，他们调这个会被权限层挡在 403。
    # ip 取不到就传 None，操作日志那一列本来就可空，不用为它编一个假地址
    ip_address = request.client.host if request.client else None
    created = WorkOrderService(db).create_work_order(
        payload=payload,
        operator=operator,
        request_path=request.url.path,
        ip_address=ip_address,
    )
    return ApiResponse(data=created)


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
