from sqlalchemy import MetaData
from sqlalchemy.orm import DeclarativeBase

# 给索引 / 唯一约束 / 外键起统一名字。不配这个的话，Alembic 自动生成的迁移里
# 约束名是一串随机字符，以后想删或改根本对不上号
NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    # 所有模型的爹。models 里继承它就自动被 SQLAlchemy 收进同一份 metadata
    metadata = MetaData(naming_convention=NAMING_CONVENTION)
