from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request, status
from sqlalchemy.orm import Session

from app.api.deps import get_db, require_permissions
from app.core.permissions import PermissionCode
from app.models import User
from app.schemas.common import ApiResponse, CursorResponse
from app.schemas.work_orders import (
    WorkOrderAssignRequest,
    WorkOrderCreateRequest,
    WorkOrderDetail,
    WorkOrderRejectRequest,
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


@router.post("/{work_order_id}/assign", response_model=ApiResponse[WorkOrderDetail])
def assign_work_order(
    work_order_id: int,
    payload: WorkOrderAssignRequest,
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    # 分派要的是 work_order:assign。这个权限点天然把"调度"和"干活"分开了：
    # ADMIN / DISPATCHER 有，ENGINEER 和 VIEWER 没有 ——
    # 所以"工程师只能接活不能派活"这句话，在权限层就已经说完了，
    # 函数体里一行角色判断都不用写
    operator: Annotated[
        User,
        Depends(require_permissions(PermissionCode.WORK_ORDER_ASSIGN)),
    ],
) -> ApiResponse[WorkOrderDetail]:
    ip_address = request.client.host if request.client else None
    updated = WorkOrderService(db).assign_work_order(
        work_order_id=work_order_id,
        assignee_id=payload.assignee_id,
        operator=operator,
        request_path=request.url.path,
        ip_address=ip_address,
    )
    return ApiResponse(data=updated)


# ---------------------------------------------------------------------------
# 状态流转的四个动作。权限点全都是 work_order:update —— 也就是说
# ADMIN / DISPATCHER / ENGINEER 都能调，VIEWER 没有 update 会被 403 挡掉。
#
# 这里有个文档上的矛盾，记一笔，免得以后有人看见觉得写错了：
# business-rules.md 的权限表里 ENGINEER 只有 work_order:update，
# 但同一篇的正文又写着"工程师可以驳回做不了的工单"。两处对不上。
# 取了口径宽的那一侧（驳回也能做），理由是：
#   1. 正文那句话本身就是需求，表格大概是漏了；
#   2. 我们的权限点是灌库的种子数据，项目里没有 seed.py，
#      为一个动作单开权限点要同时动 permissions 表、role_permissions 表
#      和 PermissionCode 三处，代价和收益不成比例。
# 真要收紧的话，加一个 work_order:reject 权限点、只给 ADMIN / DISPATCHER，
# 然后把这四个路由的依赖按动作拆开就行 —— 改起来是一处的事。
#
# 另外一个偷懒的地方：这四个函数体长得几乎一模一样，只有调用的 service 方法不同。
# 没抽工厂函数，因为 FastAPI 认的是函数签名（那些 Annotated[..., Depends(...)]），
# 用闭包生成出来的签名它读不干净（类型标注会变成一堆参数化泛型），
# 值得换来的那点行数不值当。四个就四个吧。
# ---------------------------------------------------------------------------


@router.post("/{work_order_id}/start", response_model=ApiResponse[WorkOrderDetail])
def start_work_order(
    work_order_id: int,
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    operator: Annotated[
        User,
        Depends(require_permissions(PermissionCode.WORK_ORDER_UPDATE)),
    ],
) -> ApiResponse[WorkOrderDetail]:
    # 没有请求体。开始就是开始，没有额外信息可传 ——
    # 谁点的、什么时候点的，服务端自己知道
    ip_address = request.client.host if request.client else None
    updated = WorkOrderService(db).start_work_order(
        work_order_id=work_order_id,
        operator=operator,
        request_path=request.url.path,
        ip_address=ip_address,
    )
    return ApiResponse(data=updated)


@router.post("/{work_order_id}/complete", response_model=ApiResponse[WorkOrderDetail])
def complete_work_order(
    work_order_id: int,
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    operator: Annotated[
        User,
        Depends(require_permissions(PermissionCode.WORK_ORDER_UPDATE)),
    ],
) -> ApiResponse[WorkOrderDetail]:
    ip_address = request.client.host if request.client else None
    updated = WorkOrderService(db).complete_work_order(
        work_order_id=work_order_id,
        operator=operator,
        request_path=request.url.path,
        ip_address=ip_address,
    )
    return ApiResponse(data=updated)


@router.post("/{work_order_id}/close", response_model=ApiResponse[WorkOrderDetail])
def close_work_order(
    work_order_id: int,
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    operator: Annotated[
        User,
        Depends(require_permissions(PermissionCode.WORK_ORDER_UPDATE)),
    ],
) -> ApiResponse[WorkOrderDetail]:
    ip_address = request.client.host if request.client else None
    updated = WorkOrderService(db).close_work_order(
        work_order_id=work_order_id,
        operator=operator,
        request_path=request.url.path,
        ip_address=ip_address,
    )
    return ApiResponse(data=updated)


@router.post("/{work_order_id}/reject", response_model=ApiResponse[WorkOrderDetail])
def reject_work_order(
    work_order_id: int,
    payload: WorkOrderRejectRequest,
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    operator: Annotated[
        User,
        Depends(require_permissions(PermissionCode.WORK_ORDER_UPDATE)),
    ],
) -> ApiResponse[WorkOrderDetail]:
    # 四个动作里只有这个要请求体，因为只有它有一个"为什么"要说
    ip_address = request.client.host if request.client else None
    updated = WorkOrderService(db).reject_work_order(
        work_order_id=work_order_id,
        reason=payload.reason,
        operator=operator,
        request_path=request.url.path,
        ip_address=ip_address,
    )
    return ApiResponse(data=updated)
