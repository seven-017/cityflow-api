from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Role


class RoleRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def list_roles(self) -> list[Role]:
        # 这里不加 .options(selectinload(Role.permissions))。
        # 实测过（见 users.py 的注释）：模型上已经声明 lazy="selectin"，
        # 再写一遍不多发一条 SQL，那就别写
        statement = select(Role).order_by(Role.id)
        return list(self.db.execute(statement).scalars().all())
