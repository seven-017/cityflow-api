from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.deps import get_db, require_permissions
from app.core.permissions import PermissionCode
from app.models import User
from app.schemas.assets import AssetDetail, AssetSummary
from app.schemas.common import ApiResponse, CursorResponse
from app.services.assets import AssetService

router = APIRouter()


@router.get("", response_model=ApiResponse[CursorResponse[AssetSummary]])
def list_assets(
    db: Annotated[Session, Depends(get_db)],
    # 权限闸门。名字前面加下划线是因为这个参数我们自己不用，
    # 纯粹为了让那个依赖跑起来——它跑到了，权限就是查过了
    _: Annotated[User, Depends(require_permissions(PermissionCode.ASSET_READ))],
    # 这里原来是 page / page_size，2026-09-26 换成了 after_id / limit。
    # 前端翻页的方式也跟着变了：拿上一页 meta.next_cursor 当这次的 after_id 传回来，
    # 不传就是第一页。所以前端不再有"跳到第 5000 页"这种按钮了，只有上一页 / 下一页。
    after_id: int | None = Query(None, ge=1),
    # ge / le 是取值范围，越界 FastAPI 直接甩 422，函数体里不用再写 if 判断
    limit: int = Query(20, ge=1, le=100),
) -> ApiResponse[CursorResponse[AssetSummary]]:
    items, meta = AssetService(db).list_assets(after_id=after_id, limit=limit)
    return ApiResponse(data=CursorResponse(items=items, meta=meta))


@router.get("/{asset_id}", response_model=ApiResponse[AssetDetail])
def get_asset(
    asset_id: int,
    db: Annotated[Session, Depends(get_db)],
    # 详情页跟列表页要的是同一个权限，所以这儿还是 ASSET_READ，没新开一个
    _: Annotated[User, Depends(require_permissions(PermissionCode.ASSET_READ))],
) -> ApiResponse[AssetDetail]:
    # asset_id 走的是路径参数，FastAPI 自己会转成 int。
    # 传个 abc 进来会由它直接甩 422，不用我们写转换和 try
    return ApiResponse(data=AssetService(db).get_asset(asset_id))
