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
    WorkOrderRecordItem,
    WorkOrderRecordRequest,
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
# 状态流转的四个动作。权限是两层的 —— 只看这儿那个 Depends，会以为工程师什么都能干：
#
#   第一层 路由上的 work_order:update：能不能碰工单。
#          ADMIN / DISPATCHER / ENGINEER 有，VIEWER 没有，到这儿就被 403 挡掉。
#   第二层 service 里按角色和归属判：能碰工单的人里，哪个动作归谁。
#          ENGINEER 只能对"派给自己的那张单"做 START / COMPLETE
#          （规则在 core/work_order_status.py 的 ENGINEER_ALLOWED_ACTIONS），
#          ADMIN / DISPATCHER 不吃这两条限制。
#
# 第二层为什么不也做成权限点（比如单开一个 work_order:reject）：一小半是因为
# 项目里没有 seed.py，权限点是直接灌库的，为一个动作要同时动 permissions 表、
# role_permissions 表和 PermissionCode 三处；更大一半是因为"只能操作自己的单"
# 这条根本表达不成权限点 —— 它是数据级的判断，得知道具体是哪张单、派给了谁。
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


@router.post(
    "/{work_order_id}/records",
    response_model=ApiResponse[WorkOrderRecordItem],
    # 201：这是往工单底下新建了一个子资源，跟建工单本身一个道理。
    # 四五十行上面那几个流转接口返的是 200 —— 它们改的是已有资源的属性，没新建东西
    status_code=status.HTTP_201_CREATED,
)
def add_work_order_record(
    work_order_id: int,
    payload: WorkOrderRecordRequest,
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    # 权限还是 work_order:update：能改这张单的人就能在它底下写备注。
    # 不吃上面那两条角色限制 —— 那两条管的是"谁能推动这张单"（状态流转），
    # 写备注不推状态。所以工程师路过别人的单、留一句"泵在响"，这是允许的；
    # 文档里那句"Engineer 只能更新分配给自己的工单"说的是改工单那一行，
    # 不含它下面的子资源
    operator: Annotated[
        User,
        Depends(require_permissions(PermissionCode.WORK_ORDER_UPDATE)),
    ],
) -> ApiResponse[WorkOrderRecordItem]:
    ip_address = request.client.host if request.client else None
    created = WorkOrderService(db).add_processing_record(
        work_order_id=work_order_id,
        content=payload.content,
        operator=operator,
        request_path=request.url.path,
        ip_address=ip_address,
    )
    return ApiResponse(data=created)
