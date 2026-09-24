import math

from sqlalchemy.orm import Session

from app.core.exceptions import BusinessException, NotFoundException
from app.models import Role, User
from app.repositories.operation_logs import OperationLogRepository
from app.repositories.roles import RoleRepository
from app.repositories.users import UserRepository
from app.schemas.common import PageMeta
from app.schemas.system import RoleSummary, UserSummary


def user_summary(user: User) -> UserSummary:
    return UserSummary(
        id=user.id,
        username=user.username,
        display_name=user.display_name,
        email=user.email,
        enabled=user.enabled,
        role_codes=sorted(role.code for role in user.roles),
        last_login_at=user.last_login_at,
    )


def role_summary(role: Role) -> RoleSummary:
    return RoleSummary(
        id=role.id,
        code=role.code,
        name=role.name,
        description=role.description,
        enabled=role.enabled,
        permissions=sorted(permission.code for permission in role.permissions),
    )


class SystemService:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.users = UserRepository(db)
        self.roles = RoleRepository(db)
        self.logs = OperationLogRepository(db)

    def list_users(self, page: int, page_size: int) -> tuple[list[UserSummary], PageMeta]:
        # 先数总数再取这一页。两条 SQL，但分页就是这个套路：
        # 少了总数前端画不出页码
        total = self.users.count_users()
        offset = (page - 1) * page_size
        items = [user_summary(u) for u in self.users.list_users(offset, page_size)]
        # math.ceil 是向上取整：7 条 / 每页 5 条 = 1.4 -> 要 2 页
        pages = math.ceil(total / page_size) if page_size else 0
        return items, PageMeta(page=page, page_size=page_size, total=total, pages=pages)

    def list_roles(self) -> list[RoleSummary]:
        return [role_summary(r) for r in self.roles.list_roles()]

    def set_user_roles(
        self,
        *,
        user_id: int,
        role_codes: list[str],
        operator: User,
        request_path: str,
        ip_address: str | None,
    ) -> UserSummary:
        user = self.users.get_by_id(user_id)
        if user is None:
            raise NotFoundException(f"User {user_id} not found.")

        roles = self.users.roles_for_codes(role_codes)
        # 前端可能传了库里没有的角色码。这里要挡住，不能默默忽略 ——
        # 不然管理员以为改成功了，实际只改了一半
        missing = sorted(set(role_codes) - {r.code for r in roles})
        if missing:
            raise BusinessException(f"Unknown role code: {', '.join(missing)}")

        user.roles = roles
        self.logs.add(
            user_id=operator.id,
            operation="ASSIGN_ROLES",
            module="system",
            target_type="user",
            target_id=str(user.id),
            request_method="PUT",
            request_path=request_path,
            result="SUCCESS",
            detail="roles=" + ",".join(sorted(role_codes)),
            ip_address=ip_address,
        )
        # 改角色和写日志一起提交，不会出现"日志写了但角色没改"
        self.db.commit()
        return user_summary(user)
