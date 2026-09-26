from datetime import date

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
