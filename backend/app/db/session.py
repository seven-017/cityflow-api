from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.config import get_settings

settings = get_settings()

# 连接池两个关键参数：
# pool_pre_ping  借连接之前先 ping 一下，能自动踢掉被 MySQL 那边断掉的死连接，
#                不然偶尔会报 "MySQL server has gone away"
# pool_recycle   连接最多活 1 小时就回收。MySQL 默认 wait_timeout 是 8 小时，
#                设小一点省得半夜挂机第二天第一条请求必炸
engine = create_engine(
    settings.database_url,
    pool_pre_ping=True,
    pool_recycle=3600,
    echo=settings.sql_echo,
    connect_args={"local_infile": settings.mysql_local_infile},
)

# autoflush=False        查询前别偷偷把没提交的改动刷过去，不然排查问题时很懵
# autocommit=False       事务得自己 commit，这正是我们要的
# expire_on_commit=False commit 后对象字段还能直接用，不会又去查一次库
#                        （接口返回响应时 session 通常已经关了，所以必须关掉它）
SessionLocal = sessionmaker(
    bind=engine,
    autoflush=False,
    autocommit=False,
    expire_on_commit=False,
)
