from collections.abc import Callable, Generator
from typing import Annotated

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.core.exceptions import PermissionDeniedException, UnauthorizedException
from app.core.permissions import PermissionCode
from app.core.security import decode_access_token
from app.db.session import SessionLocal
from app.models import User
from app.repositories.users import UserRepository
from app.services.auth import permission_codes

# auto_error=False 的意思是"请求头里没有 token 不要立刻报错，交给我自己处理"。
# 默认是 True，那样缺 token 时 FastAPI 会直接甩一个英文的 403，格式跟我们统一的返回体不一样
bearer_scheme = HTTPBearer(auto_error=False)


def get_db() -> Generator[Session, None, None]:
    """一个请求发一个 session，请求结束不管成功失败都关掉。

    FastAPI 的依赖注入会替我们管这个生成器的生命周期：
    yield 之前算"请求刚开始"，yield 之后算"请求结束了"，
    所以 finally 里的 close 一定跑得到，不会漏掉连接。

    注意别在函数里自己 commit：提不提交是业务层的事，
    这里只负责开和关。
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def get_current_user(
    credentials: Annotated[
        HTTPAuthorizationCredentials | None,
        Depends(bearer_scheme),
    ],
    db: Annotated[Session, Depends(get_db)],
) -> User:
    """从 Authorization 请求头里把"当前登录的是谁"解出来。

    这一句 Depends 挂在哪个接口上，哪个接口就变成"必须登录才能访问"。
    顺序是：取请求头 -> 验签解码 -> 拿 user_id 查库 -> 返回 User 对象。
    """
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise UnauthorizedException()

    payload = decode_access_token(credentials.credentials)
    subject = payload.get("sub")
    if subject is None:
        raise UnauthorizedException("Access token does not contain a subject.")

    try:
        user_id = int(subject)
    except (TypeError, ValueError) as exc:
        # 签 token 时 sub 是 str(user_id)，理论上不会是别的；
        # 但万一有人拿旧格式的 token 来试，这里要能兜住而不是 500
        raise UnauthorizedException("Access token subject is invalid.") from exc

    # 每次请求都回库查一次，而不是把权限塞进 token 里。
    # 代价是多一次查询，换来的是"改了权限立刻生效"——
    # 否则得等旧 token 过期（30 分钟）新权限才生效
    user = UserRepository(db).get_by_id(user_id)
    if user is None or not user.enabled:
        raise UnauthorizedException("User account is unavailable.")

    return user


def require_permissions(
    *required: PermissionCode,
) -> Callable[[User], User]:
    """生成一个"必须同时拥有这些权限"的依赖。

    用法：`dependencies=[Depends(require_permissions(PermissionCode.WORK_ORDER_CREATE))]`
    它是"工厂函数"——调用一次产出一个依赖函数，所以能带参数。
    """
    def dependency(
        user: Annotated[User, Depends(get_current_user)],
    ) -> User:
        granted = set(permission_codes(user))
        # 把所有缺的权限一次报全，而不是遇到第一个就抛。
        # 前端一次就能知道"我还差哪几个权限"，不用改一个试一次
        missing = sorted(permission.value for permission in required if permission not in granted)
        if missing:
            raise PermissionDeniedException(
                f"Missing required permission: {', '.join(missing)}"
            )
        return user

    return dependency
