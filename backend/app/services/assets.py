import math

from sqlalchemy.orm import Session

from app.models import Asset
from app.repositories.assets import AssetRepository
from app.schemas.assets import AssetSummary
from app.schemas.common import PageMeta


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

    def list_assets(self, page: int, page_size: int) -> tuple[list[AssetSummary], PageMeta]:
        # 先数总数，再取这一页——两条 SQL 打底。跟第 14 步的 list_users 一个套路，
        # 少了总数前端画不出页码，"第 3 页"这种按钮就没法点。
        total = self.assets.count_assets()
        # "第几页"是业务概念，仓库层不认这个，所以在这儿换算成"跳过多少行"再传下去
        offset = (page - 1) * page_size
        items = [asset_summary(a) for a in self.assets.list_assets(offset, page_size)]
        # math.ceil 就是向上取整：148423 条、每页 20 算出来是 7421.15，得给 7422 页
        #
        # 后面那个 if page_size else 0 其实是多余的——FastAPI 那边 ge=1 已经把 0 拦了。
        # 留着只是防以后有人绕过接口直接调 service，不算错，但确实是废话，先记着。
        pages = math.ceil(total / page_size) if page_size else 0
        return items, PageMeta(page=page, page_size=page_size, total=total, pages=pages)
