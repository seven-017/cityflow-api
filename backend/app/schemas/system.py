from datetime import datetime

from pydantic import BaseModel, Field


class UserSummary(BaseModel):
    # 注意这里**没有** password_hash。schema 就是白名单，
    # 没写上去的字段一个都出不去
    id: int
    username: str
    display_name: str
    email: str | None
    enabled: bool
    role_codes: list[str]
    last_login_at: datetime | None


class RoleSummary(BaseModel):
    id: int
    code: str
    name: str
    description: str | None
    enabled: bool
    permissions: list[str]


class RoleAssignmentRequest(BaseModel):
    """改某个用户的角色时，前端传这样一串角色码过来。

    默认空列表的意思是"传空就是清空所有角色"，
    default_factory 不能写成 default=[] —— 那样所有实例会共用同一个列表
    """

    role_codes: list[str] = Field(default_factory=list)
