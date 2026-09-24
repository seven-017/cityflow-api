from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.core.exceptions import UnauthorizedException
from app.core.security import create_access_token, verify_password
from app.models import User
from app.repositories.operation_logs import OperationLogRepository
from app.repositories.users import UserRepository
from app.schemas.auth import TokenData, UserIdentity


def permission_codes(user: User) -> list[str]:
    """把"用户的角色"摊平成"权限码清单"。

    为什么要摊平：前端要判断一个按钮能不能点，它不想自己算"角色->权限"这套映射，
    所以我们在登录时直接给它一份扁平的权限清单。

    set 是为了去重 —— 一个人同时是 DISPATCHER 和 ENGINEER 时，两边都有的
    asset:read 只会出现一次。sorted 是为了让结果稳定，方便比对和测试。
    """
    return sorted(
        {
            permission.code
            for role in user.roles
            if role.enabled                      # 角色被停用了，它带的权限也不算数
            for permission in role.permissions
        }
    )


def role_codes(user: User) -> list[str]:
    return sorted(role.code for role in user.roles if role.enabled)


def user_identity(user: User) -> UserIdentity:
    """User ORM 对象 -> 可以安全返回给前端的结构。

    为什么要转一道：ORM 对象上有 password_hash，直接返回就等于把密码哈希漏出去了。
    过一道 schema 就等于白名单，只有列出来的字段能出去。
    """
    return UserIdentity(
        id=user.id,
        username=user.username,
        display_name=user.display_name,
        email=user.email,
        enabled=user.enabled,
        role_codes=role_codes(user),
        permissions=permission_codes(user),
        last_login_at=user.last_login_at,
    )


class AuthService:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.users = UserRepository(db)
        self.logs = OperationLogRepository(db)

    def login(
        self,
        *,
        username: str,
        password: str,
        request_path: str,
        ip_address: str | None,
    ) -> TokenData:
        user = self.users.get_by_username(username)

        # 用户不存在和密码错，走同一个分支、报同一句话。
        # 这是有意的：如果分开报，攻击者就能靠"用户名错"和"密码错"的不同提示
        # 把系统里有哪些用户名一个个试出来（用户枚举）
        if user is None or not verify_password(password, user.password_hash):
            self.logs.add(
                user_id=user.id if user else None,
                operation="LOGIN",
                module="auth",
                target_type="user",
                target_id=str(user.id) if user else username,
                request_method="POST",
                request_path=request_path,
                result="FAILED",
                detail="Invalid username or password",
                ip_address=ip_address,
            )
            self.db.commit()   # 失败的记录也要落库，不然爆破尝试就查不到了
            raise UnauthorizedException("Invalid username or password.")

        if not user.enabled:
            # 账号被禁用是"知道你是谁但不让你进"，跟"密码错"性质不同，
            # 所以单独记一条 DENIED，方便管理员查
            self.logs.add(
                user_id=user.id,
                operation="LOGIN",
                module="auth",
                target_type="user",
                target_id=str(user.id),
                request_method="POST",
                request_path=request_path,
                result="DENIED",
                detail="User account is disabled",
                ip_address=ip_address,
            )
            self.db.commit()
            raise UnauthorizedException("User account is disabled.")

        # replace(tzinfo=None)：MySQL 的 DATETIME 不带时区，
        # 要塞进去就得先去掉 tzinfo，不然 pymysql 会抱怨
        user.last_login_at = datetime.now(UTC).replace(tzinfo=None)
        self.logs.add(
            user_id=user.id,
            operation="LOGIN",
            module="auth",
            target_type="user",
            target_id=str(user.id),
            request_method="POST",
            request_path=request_path,
            result="SUCCESS",
            ip_address=ip_address,
        )
        # 一次 commit 把"更新最后登录时间"和"写成功日志"一起提交
        self.db.commit()

        access_token, expires_in = create_access_token(user.id)
        return TokenData(
            access_token=access_token,
            expires_in=expires_in,
            user=user_identity(user),
        )
