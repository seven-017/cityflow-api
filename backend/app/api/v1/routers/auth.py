from typing import Annotated

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_db
from app.models import User
from app.schemas.auth import LoginRequest, TokenData, UserIdentity
from app.schemas.common import ApiResponse
from app.services.auth import AuthService, user_identity

router = APIRouter()


@router.post("/login", response_model=ApiResponse[TokenData])
def login(
    payload: LoginRequest,
    request: Request,
    db: Annotated[Session, Depends(get_db)],
) -> ApiResponse[TokenData]:
    """登录换 token。用户名密码放在请求体里，不要放 URL 上（会被记进访问日志）。"""
    # 请求是从哪个 IP 来的，记进操作日志。request.client 可能是 None
    # （某些反向代理场景），所以要判一下
    ip_address = request.client.host if request.client else None
    token_data = AuthService(db).login(
        username=payload.username,
        password=payload.password,
        request_path=request.url.path,
        ip_address=ip_address,
    )
    return ApiResponse(data=token_data)


@router.get("/me", response_model=ApiResponse[UserIdentity])
def me(user: Annotated[User, Depends(get_current_user)]) -> ApiResponse[UserIdentity]:
    """我是谁。前端刷新页面后靠它恢复登录状态。

    只要加上 Depends(get_current_user)，这个接口就自动变成"必须带有效 token 才能访问"，
    函数体里一行鉴权代码都不用写。
    """
    return ApiResponse(data=user_identity(user))
