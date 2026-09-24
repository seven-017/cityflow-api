from datetime import datetime

from pydantic import BaseModel, Field

from app.core.permissions import RoleCode


class LoginRequest(BaseModel):
    # 给长度限制是防"超大请求体"打日志/打哈希把 CPU 占满，不是防密码被猜
    username: str = Field(min_length=1, max_length=50)
    password: str = Field(min_length=1, max_length=128)


class UserIdentity(BaseModel):
    """登录成功后回给前端的"我是谁"。前端拿它决定菜单显示哪些、按钮灰不灰。"""

    id: int
    username: str
    display_name: str
    email: str | None
    enabled: bool
    role_codes: list[RoleCode]
    # permissions 直接给扁平的权限码列表，前端不用自己去算"角色能干什么"
    permissions: list[str]
    last_login_at: datetime | None


class TokenData(BaseModel):
    access_token: str
    # token_type 固定 bearer，前端拼请求头时就是 Authorization: Bearer <token>
    token_type: str = "bearer"
    expires_in: int
    user: UserIdentity
