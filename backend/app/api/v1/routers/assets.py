from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.deps import get_db, require_permissions
from app.core.permissions import PermissionCode
from app.models import User
from app.schemas.assets import AssetSummary
from app.schemas.common import ApiResponse, PageResponse
from app.services.assets import AssetService

router = APIRouter()


@router.get("", response_model=ApiResponse[PageResponse[AssetSummary]])
def list_assets(
    db: Annotated[Session, Depends(get_db)],
    # 权限闸门。名字前面加下划线是因为这个参数我们自己不用，
    # 纯粹为了让那个依赖跑起来——它跑到了，权限就是查过了
    _: Annotated[User, Depends(require_permissions(PermissionCode.ASSET_READ))],
    # ge / le 是取值范围，越界 FastAPI 直接甩 422，函数体里不用再写 if 判断
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
) -> ApiResponse[PageResponse[AssetSummary]]:
    items, meta = AssetService(db).list_assets(page, page_size)
    return ApiResponse(data=PageResponse(items=items, meta=meta))
