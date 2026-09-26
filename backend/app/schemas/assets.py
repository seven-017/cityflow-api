from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel


class AssetSummary(BaseModel):
    """资产列表页里一行长什么样。

    这东西就是一张白名单：没写在这儿的字段，前端一个都拿不到。
    所以它不是把 Asset 抄一遍，是"挑"——列表页用得上哪几个就挑哪几个。

    可空性怎么定：跟模型里的 Mapped[X | None] 一对一照抄，别去看库里现在有没有空值。
    拿 asset_type 举例，模型上是 nullable，全表 148423 行碰巧一个 NULL 都没有——
    那是导入脚本的行为，不是数据库的约束。写成 str 的话，哪天换份数据源冒出一个 NULL，
    Pydantic 当场抛 ValidationError，接口直接 500。这种错还特别难查，因为平时都是好的。

    为啥只留这 7 个：量过（2026-09-24 把各列的 NULL 占比跑了一遍）——
    location 99.3% 是空的、record_value 99.4% 空、manufacturer 96.6% 空、
    category 91.8% 空。这几列要是摆到列表页上，前端就是一整列破折号，没意义，砍掉。
    留下来的这 7 个：要么全表没空值，要么只有 1 行是空的。
    """

    id: int
    # 官方数据集里那串 OBJ_CODE，落在这一列上
    source_record_id: str
    # 双数据源隔离用的：列表上得让前端看出来这行是官方老数据，还是平台自己录的
    data_source: str
    # 老系统留下的单字母代码，实测就 A / S / T / W / F 这五种。
    # 要不要翻成中文名，等真有页面需要了再说，列表页先原样扔给前端
    asset_type: str | None
    description: str
    status: str | None
    commissioned_on: date | None


class AssetDetail(BaseModel):
    """资产详情页里那条资产长什么样。

    跟 AssetSummary 是同一个模型的两个视图：列表页一行放不下这么多列，详情页可以。
    但这里也还是"挑"，不是全给 —— 模型里 27 列，这儿 17 列。

    没进来的那几列是 GIS 那组（gis_object_id / gis_layer / x_location / y_location）。
    不是不能给，是现在没人用。等真要做地图了再加，没必要提前占坑。
    这也顺便说明了"列表页砍掉的字段在详情页可能有用"——比如 withdrawn_on、
    manufacturer、serial_number，在列表页是噪音，在详情页就是该看的东西。

    已知的坑（先留着不修，明确记录在案）：
    record_value 这个字段返回给前端时是"字符串"，不是数字。
    实测 Pydantic 2.13 把 Decimal("1234567.89") 序列化成 "1234567.89"（带引号）。
    为什么不干脆声明成 float？因为这是金额，float 会掉精度，数据库里存的本来就是
    Numeric(18,2)。所以"字符串"是有意的代价，前端自己转一下就好。
    真要修是给这个字段挂个 serializer 转成 float —— 但那等于放弃精度，是个新决定，
    这一版先不动。
    """

    id: int
    source_record_id: str
    data_source: str
    asset_type: str | None
    description: str
    asset_class: str | None
    category: str | None
    location: str | None
    manufacturer: str | None
    model: str | None
    serial_number: str | None
    mrc_code: str | None
    status: str | None
    commissioned_on: date | None
    withdrawn_on: date | None
    # 见类注释最后一段：这里出来的是字符串，是有意的，不是 bug
    record_value: Decimal | None
    source_updated_at: datetime | None
