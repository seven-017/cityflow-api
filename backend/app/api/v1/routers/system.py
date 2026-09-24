from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.orm import Session

from app.api.deps import get_db, require_permissions
from app.core.permissions import PermissionCode
from app.models import User
from app.schemas.common import ApiResponse, PageResponse
from app.schemas.system import RoleAssignmentRequest, RoleSummary, UserSummary
from app.services.system import SystemService

router = APIRouter()


@router.get("/users", response_model=ApiResponse[PageResponse[UserSummary]])
def list_users(
    db: Annotated[Session, Depends(get_db)],
    # 这一行就是权限闸门。require_permissions 是个工厂函数，
    # 调用它（带上要什么权限）产出一个依赖，挂上去即可。
    # 前面加下划线是因为这个参数本身我们不用，只是为了让依赖被执行
    _: Annotated[User, Depends(require_permissions(PermissionCode.USER_MANAGE))],
    # ge/le 是取值范围校验，超出范围 FastAPI 直接返 422，
    # 函数体里就不用自己写 if 判断了
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
) -> ApiResponse[PageResponse[UserSummary]]:
    items, meta = SystemService(db).list_users(page, page_size)
    return ApiResponse(data=PageResponse(items=items, meta=meta))


@router.get("/roles", response_model=ApiResponse[list[RoleSummary]])
def list_roles(
    db: Annotated[Session, Depends(get_db)],
    _: Annotated[User, Depends(require_permissions(PermissionCode.ROLE_MANAGE))],
) -> ApiResponse[list[RoleSummary]]:
    return ApiResponse(data=SystemService(db).list_roles())


@router.put("/users/{user_id}/roles", response_model=ApiResponse[UserSummary])
def set_user_roles(
    user_id: int,
    payload: RoleAssignmentRequest,
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    # 这个依赖不用下划线，因为下面写操作日志要记"是谁改的"
    operator: Annotated[User, Depends(require_permissions(PermissionCode.USER_MANAGE))],
) -> ApiResponse[UserSummary]:
    ip_address = request.client.host if request.client else None
    updated = SystemService(db).set_user_roles(
        user_id=user_id,
        role_codes=payload.role_codes,
        operator=operator,
        request_path=request.url.path,
        ip_address=ip_address,
    )
    return ApiResponse(data=updated)
