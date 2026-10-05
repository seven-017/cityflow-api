from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.models import Role, User


class UserRepository:
    """注意下面两句里的 `.options(selectinload(...))`。

    实测（2026-09-24，同一查询跑两遍数 SELECT 次数）：带上它 3 次、去掉它还是 3 次
    —— 因为 `User.roles` 和 `Role.permissions` 在模型上已经声明了 `lazy="selectin"`，
    这里显式再写一遍不会多发一条 SQL，属于冗余。

    那为什么还留着？两个理由：
    1. 查询点自解释 —— 读到这行就知道"这条查询依赖角色和权限也被加载出来"，
       不用翻回模型定义去确认
    2. 防御性 —— 万一以后有人把模型上的 `lazy="selectin"` 改成默认的 `select`，
       这条查询不会悄悄退化成 N+1

    如果哪天要精简，可以删，但删之前得先确认模型上的 lazy 设置没变。
    """

    def __init__(self, db: Session) -> None:
        self.db = db

    def get_by_username(self, username: str) -> User | None:
        # 登录时按用户名找。这里必须把 roles 和 permissions 一起捞出来，
        # 不然下面算"这个用户有哪些权限"会在循环里一次次查库（N+1）
        statement = (
            select(User)
            .options(selectinload(User.roles).selectinload(Role.permissions))
            .where(User.username == username)
        )
        return self.db.execute(statement).scalar_one_or_none()

    def get_by_id(self, user_id: int) -> User | None:
        # 每个带 token 的请求都要走这里（token 里只有 user_id，得回来查完整信息）
        statement = (
            select(User)
            .options(selectinload(User.roles).selectinload(Role.permissions))
            .where(User.id == user_id)
        )
        return self.db.execute(statement).scalar_one_or_none()

    def list_users(self, offset: int, limit: int) -> list[User]:
        statement = (
            select(User)
            .options(selectinload(User.roles))
            .order_by(User.id)
            .offset(offset)
            .limit(limit)
        )
        return list(self.db.execute(statement).scalars().all())

    def count_users(self) -> int:
        return int(self.db.execute(select(func.count(User.id))).scalar_one())

    def roles_for_codes(self, role_codes: list[str]) -> list[Role]:
        # 建用户 / 改角色时用：前端传的是一串角色码，要换成真正的 Role 对象
        statement = (
            select(Role)
            .options(selectinload(Role.permissions))
            .where(Role.code.in_(role_codes))
            .order_by(Role.id)
        )
        return list(self.db.execute(statement).scalars().all())
