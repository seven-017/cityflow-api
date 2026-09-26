from sqlalchemy.orm import Session

from app.models import Asset
from app.repositories.assets import AssetRepository
from app.schemas.assets import AssetSummary
from app.schemas.common import CursorMeta


def asset_summary(asset: Asset) -> AssetSummary:
    """把一条 Asset 搬成 AssetSummary。

    这就是 schema 那层要付的代价：查出来的 ORM 对象不能直接往外扔，
    得手动把要发的字段一个个搬过来。
    这么做的好处是表加列时这儿不用动——表加多少列，这 7 行都纹丝不动。
    反过来也有个坑：漏搬了不会报错，前端就是少个字段，得自己留意。
    """
    return AssetSummary(
        id=asset.id,
        source_record_id=asset.source_record_id,
        data_source=asset.data_source,
        asset_type=asset.asset_type,
        description=asset.description,
        status=asset.status,
        commissioned_on=asset.commissioned_on,
    )


class AssetService:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.assets = AssetRepository(db)

    def list_assets(self, *, after_id: int | None, limit: int) -> tuple[list[AssetSummary], CursorMeta]:
        # 总数还是要给的——前端得显示"共 148423 条"。
        # 实测这一下 assets 是 17 ms，跟原来深分页那 2 秒比起来不算主要矛盾，先留着。
        # （work_orders 那张表是 258 ms，到第 17 步得重新考虑这块，见仓库层那句注释。）
        total = self.assets.count_assets()
        # 仓库层故意多要了一行，这里看它到底有没有多给
        rows = self.assets.list_assets(after_id=after_id, limit=limit)
        has_more = len(rows) > limit
        # 多出来那一条只是用来探测"还有没有下一页"的，不能发给前端
        page_rows = rows[:limit]
        # 下一页从哪开始？就是这一页最后那条的 id。
        # has_more 为假的时候给 None，让前端一眼看出到底了
        next_cursor = page_rows[-1].id if has_more and page_rows else None
        items = [asset_summary(a) for a in page_rows]
        return items, CursorMeta(
            limit=limit,
            total=total,
            next_cursor=next_cursor,
            has_more=has_more,
        )
