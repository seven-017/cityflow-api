from sqlalchemy.orm import Session

from app.core.exceptions import NotFoundException
from app.models import Asset
from app.repositories.assets import AssetRepository
from app.schemas.assets import AssetDetail, AssetSummary
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


def asset_detail(asset: Asset) -> AssetDetail:
    """把一条 Asset 搬成 AssetDetail。

    跟上面的 asset_summary 是一回事，只是搬的字段多一些。
    这种"一个模型、两个搬运函数"的写法有点啰嗦，但换来的是两边的字段互不干扰——
    详情页要多显示几列，不会把列表接口的返回也撑大。

    另外一个好处：AssetSummary 和 AssetDetail 都只声明自己有的字段，
    所以哪天把 AssetSummary 里某个字段删了，这里不用跟着改。
    """
    return AssetDetail(
        id=asset.id,
        source_record_id=asset.source_record_id,
        data_source=asset.data_source,
        asset_type=asset.asset_type,
        description=asset.description,
        asset_class=asset.asset_class,
        category=asset.category,
        location=asset.location,
        manufacturer=asset.manufacturer,
        model=asset.model,
        serial_number=asset.serial_number,
        mrc_code=asset.mrc_code,
        status=asset.status,
        commissioned_on=asset.commissioned_on,
        withdrawn_on=asset.withdrawn_on,
        record_value=asset.record_value,
        source_updated_at=asset.source_updated_at,
    )


class AssetService:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.assets = AssetRepository(db)

    def list_assets(self, *, after_id: int | None, limit: int) -> tuple[list[AssetSummary], CursorMeta]:
        # 这里原来第一句是 total = self.assets.count_assets()，2026-09-29 删了。
        # 分页元数据不再报总数，理由写在 schemas/common.py 的 CursorMeta 上。
        # 删掉之后这个请求少了一次全表 COUNT，assets 上省 16~23 ms。
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
            next_cursor=next_cursor,
            has_more=has_more,
        )

    def get_asset(self, asset_id: int) -> AssetDetail:
        """查单条。查不到就 404，不返回 null。

        为什么是 404 而不是 data=null：404 是接口层面的语义，前端按状态码分支
        比按"data 是不是空"去猜要清楚。而且日志/监控里 404 率是个有意义的指标，
        返回 200 + null 的话这个信号就丢了。

        没做的事（明说，免得以为是漏了）：这个接口没写 operation_logs。
        只读接口要不要留痕是个产品决定，真要做也是所有只读接口一起做，
        单独给资产详情开一个特例没意义。先记着。
        """
        asset = self.assets.get_by_id(asset_id)
        if asset is None:
            raise NotFoundException(f"Asset {asset_id} not found.")
        return asset_detail(asset)
