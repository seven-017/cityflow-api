from collections.abc import Generator

from sqlalchemy.orm import Session

from app.db.session import SessionLocal


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
