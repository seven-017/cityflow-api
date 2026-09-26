from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Asset


class AssetRepository:
    """资产表的查询。

    整个项目里只有这一层允许出现 select()。上面 service 和 router 都不知道 SQL 长啥样。
    好处很实在：以后分页要改游标、要加缓存、要调索引，就动这一个文件，别处不用碰。

    跟 UserRepository 比，这儿少了一句 .options(selectinload(...))。
    因为 Asset 是一张"平"表，模型里没有任何 relationship，没有需要提前捞出来的关联对象。
    """

    def __init__(self, db: Session) -> None:
        self.db = db

    def list_assets(self, offset: int, limit: int) -> list[Asset]:
        # 分页说白了就俩数：跳过多少行（offset）、取多少行（limit）。
        # 落到 SQL 就是 LIMIT limit OFFSET offset，没什么玄机。
        #
        # order_by 千万别省。SQL 本身不保证顺序，说白了就是"我按什么顺序给你都行"。
        # 不写的话翻第 2 页可能又刷出第 1 页的东西，也有可能有些行你永远翻不到。
        # 按主键排最省事——既是稳定顺序，又走主键索引，不额外花钱。
        statement = select(Asset).order_by(Asset.id).offset(offset).limit(limit)
        return list(self.db.execute(statement).scalars().all())

    def count_assets(self) -> int:
        # 数总数交给数据库（SQL 的 COUNT），别把 148423 行捞回 Python 里 len()。
        # 捞回来的话光是传输 + 建 148423 个对象的开销就够呛，而我们要的只是一个数字。
        return int(self.db.execute(select(func.count(Asset.id))).scalar_one())
