from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.deps import get_db, require_permissions
from app.core.permissions import PermissionCode
from app.models import User
from app.schemas.common import ApiResponse, CursorResponse
from app.schemas.labor import LaborSummary
from app.services.labor import LaborService

router = APIRouter()


@router.get("", response_model=ApiResponse[CursorResponse[LaborSummary]])
def list_labor(
    db: Annotated[Session, Depends(get_db)],
    # 权限闸门。名字前面加下划线是因为这个参数我们自己不用，
    # 纯粹为了让那个依赖跑起来 —— 它跑到了，权限就是查过了
    #
    # 用的是 labor:read，跟 asset:read / work_order:read 是两个独立的权限点。
    # 库里 labor:read 四个角色都有（ADMIN / DISPATCHER / ENGINEER / VIEWER），
    # 跟业务规则那张表一致：四个角色对 Labor 都是"读"，只有 ADMIN 和 ENGINEER 能写。
    # 那个"写"是 labor:create，这个文件里没有接口用它 —— 平台自己记工时的接口还没做。
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
