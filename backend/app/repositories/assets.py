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

    def list_assets(self, *, after_id: int | None, limit: int) -> list[Asset]:
        """按 id 往后翻，一次取 limit 条（其实会多要一条，见下面）。

        这里原来是 LIMIT ? OFFSET ? 那种写法，2026-09-26 换成了游标。
        换的原因是量出来一个很难看的东西：

            LIMIT 20 OFFSET 2200000   ->  3349 ms   EXPLAIN: type=index, rows=2158704
            WHERE id > 2768635 LIMIT 20 ->  0.9 ms   EXPLAIN: type=range, rows=37932

        同一个位置、同样 20 条数据，差了 3700 倍。
        根因是 OFFSET 的实现方式：它不是"跳过去"，是"从索引头开始一行行走，
        走过 offset 行全部丢掉，再取 limit 行"。所以 OFFSET 越大越慢，
        而且是线性的——EXPLAIN 里那个 rows 从 20 一路涨到 215 万就是证据。
        WHERE id > ? 就不一样了，主键索引是有序的，直接定位到那个位置往下取。

        代价是跳不了页了：你不知道第 5000 页的第一条 id 是多少，只能一页页往后走。
        前端那边得从"页码按钮"改成"上一页 / 下一页"或者"加载更多"。
        这个取舍是有意的——一个 222 万行的表，硬跳第 5000 页本来也没什么意义。
        """
        statement = select(Asset)
        if after_id is not None:
            # 不传 after_id 就是第一页，不加这个条件
            statement = statement.where(Asset.id > after_id)
        # 多要一条（limit + 1）：拿回来是 limit + 1 条就说明"后面还有"，
        # 只有 limit 条就说明到底了。这样省掉了额外一次查询。
        # 多出来的那一条由 service 裁掉，不会发到前端。
        statement = statement.order_by(Asset.id).limit(limit + 1)
        return list(self.db.execute(statement).scalars().all())

    def get_by_id(self, asset_id: int) -> Asset | None:
        # 按主键查单条。走主键索引，行数不用管——主键最多命中一行。
        #
        # 用 scalar_one_or_none 而不是 first()：万一主键上真的命中两行（说明数据出问题了），
        # 前者会直接报错，后者会闷头给你第一条。这种地方宁可直接炸，也别悄悄给错数据。
        statement = select(Asset).where(Asset.id == asset_id)
        return self.db.execute(statement).scalar_one_or_none()

    # 这里原来还有个 count_assets()，2026-09-29 删了。
    # 因为分页元数据里的 total 一起删了（原因写在 schemas/common.py 的 CursorMeta 上），
    # 没人调它了 —— 没调用者的方法就是死代码。
    # 留个空行在这儿，省得以后有人翻 git blame 时一头雾水。
    #
    # 2026-10-02 又加回来了，理由写在下面这个方法的注释里。
    # 那段"删了"的记录没删掉，是有意的 —— 同一段代码该不该留，取决于当时有没有人用，
    # 两次的答案不一样很正常，把两次的判断都留着比抹掉一次更清楚。

    def count_assets(self) -> int:
        """数资产有多少条。

        它是"删了又加回来"的，所以先说清楚为什么当年删、现在为什么又要：

        当年（2026-09-29）它唯一的调用者是分页元数据里那个 total，
        而那个 total 本身被删了（320 万行上算一次 COUNT 是纯浪费，
        理由写在 schemas/common.py 的 CursorMeta 上）。调用者没了，它就成死代码了。

        现在（2026-10-02）加回来，因为 Dashboard 的指标汇总要报这个数 ——
        身份从"分页里一个没人看的装饰"变成了"首页上的一张卡片"。
        所以「没用到的不许先写」这条规矩反过来说也成立：
        没用到的不许留，但真用到的时候，也不该因为"以前删过"就不敢加。

        2026-10-02 实测：assets 148423 行，COUNT 17.7 ms。
        这是整套 Dashboard 指标里最便宜的一个，不用为它做任何优化。
        """
        return int(self.db.execute(select(func.count(Asset.id))).scalar_one())
