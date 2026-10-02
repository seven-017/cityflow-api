from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request, status
from sqlalchemy.orm import Session

from app.api.deps import get_db, require_permissions
from app.core.permissions import PermissionCode
from app.models import User
from app.schemas.common import ApiResponse, CursorResponse
from app.schemas.labor import LaborCreateRequest, LaborSummary
from app.services.labor import LaborService

router = APIRouter()


@router.post(
    "",
    response_model=ApiResponse[LaborSummary],
    # 创建资源返 201 而不是默认的 200，跟创建工单一个口径 ——
    # 前端看状态码就能分清"新建了一条"和"查到了点什么"，不用解析返回体
    status_code=status.HTTP_201_CREATED,
)
def create_labor(
    payload: LaborCreateRequest,
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    # 这个依赖前面不加下划线，因为录工时确实要用到"是谁录的" ——
    # 它要写进操作日志，而且日志里那一列是审计"这条工时谁填的"的唯一依据
    #
    # 权限点是 labor:create，跟列表用的 labor:read 是分开的两个。
    # 库里 labor:create 只给了 ADMIN 和 ENGINEER（DISPATCHER / VIEWER 没有），
    # 跟业务规则那张 RBAC 表一致：Labor 那一列 ADMIN 是"读写"、ENGINEER 是"创建/读"、
    # 另外两个只有"读"。用 DISPATCHER 去调会被权限层挡在 403
    operator: Annotated[
        User, Depends(require_permissions(PermissionCode.LABOR_CREATE))
    ],
) -> ApiResponse[LaborSummary]:
    # 返回的形状就是列表里那一行的形状（LaborSummary）。
    # 不是偷懒 —— 一条工时就是一行，它没有"详情"这种东西：
    # 工单有流水和备注两张子表所以详情比列表宽，labor 没有子表，
    # 列表那 12 个字段就是它的全部。为它再造一个同名的 schema 只会让字段定义有两处
    #
    # ip 取不到就传 None，操作日志那一列本来就可空，不用为它编个假地址
    ip_address = request.client.host if request.client else None
    created = LaborService(db).create_labor(
        payload=payload,
        operator=operator,
        request_path=request.url.path,
        ip_address=ip_address,
    )
    return ApiResponse(data=created)


@router.get("", response_model=ApiResponse[CursorResponse[LaborSummary]])
def list_labor(
    db: Annotated[Session, Depends(get_db)],
    # 权限闸门。名字前面加下划线是因为这个参数我们自己不用，
    # 纯粹为了让那个依赖跑起来 —— 它跑到了，权限就是查过了
    #
    # 用的是 labor:read，跟 asset:read / work_order:read 是两个独立的权限点。
    # 库里 labor:read 四个角色都有（ADMIN / DISPATCHER / ENGINEER / VIEWER），
    # 跟业务规则那张表一致：四个角色对 Labor 都是"读"，只有 ADMIN 和 ENGINEER 能写。
    # 那个"写"就是本文件上面那个 POST，用的是 labor:create
    _: Annotated[
        User, Depends(require_permissions(PermissionCode.LABOR_READ))
    ],
    # 游标翻页，跟 assets / work-orders 两个列表完全一致：
    # 拿上一页 meta.next_cursor 当这次的 after_id 传回来，不传就是第一页。
    # 没有 page / page_size —— 320 万行的表上 OFFSET 翻页实测 3.5 秒一次，
    # 具体数字写在 repositories/labor.py 的注释里
    after_id: int | None = Query(None, ge=1),
    # ge / le 是取值范围，越界 FastAPI 直接甩 422，函数体里不用再写 if 判断
    limit: int = Query(20, ge=1, le=100),
    # 唯一的过滤条件：只看某张工单下的工时。
    # 传 0 或者负数会被 ge 挡掉直接 422；传一个不存在的工单号不报错，
    # 返回空列表 —— 理由写在 services/labor.py 里
    work_order_id: int | None = Query(None, ge=1),
) -> ApiResponse[CursorResponse[LaborSummary]]:
    items, meta = LaborService(db).list_labor(
        after_id=after_id, limit=limit, work_order_id=work_order_id
    )
    return ApiResponse(data=CursorResponse(items=items, meta=meta))
