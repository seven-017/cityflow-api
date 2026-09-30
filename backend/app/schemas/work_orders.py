from datetime import date, datetime

from pydantic import BaseModel, Field


class WorkOrderSummary(BaseModel):
    """工单列表页里一行长什么样。

    跟 AssetSummary 是一个套路：这东西是张白名单，没写在这儿的字段前端拿不到。
    字段是"挑"出来的，不是把 WorkOrder 抄一遍。

    挑选依据是 2026-09-29 跑的那份 NULL 占比统计（跑一次全表扫要 9~17 秒，
    为了挑这 8 个字段花掉的；顺带也说明了"做画像"本身就是有代价的）：

        description     0%     work_type     0%（7 个值）
        status          0%（3 个值）            source_record_id  0%
        completion_date 1.16%  request_date  15.14%
        data_source     0%，但不同值只有 1 个

    两个"明明有空值却还是留了"的：request_date 缺 15%、completion_date 缺 1%。
    工单列表上没日期基本没法用，缺的那 15% 前端显示成空就好。

    data_source 这个字段单独说一句：这张表上它 100% 是 REAL_PUBLIC，
    列表页上就是一整列重复的字。留着是因为它是"双数据源隔离"那条线的锚点 ——
    等平台自己开始录工单，它才有区分度。这一版先留着占一个位置。
    """

    id: int
    # 官方数据集里那串工单号，跟 assets 的 source_record_id 是一个来路
    source_record_id: str
    data_source: str
    description: str
    # 实测就 JOB / IN / AA / PPM / STAT / MRC / 空 这 7 种。
    # 要不要翻成中文，等真有页面需要了再说
    work_type: str | None
    status: str
    request_date: date | None
    completion_date: date | None


class WorkOrderDetail(BaseModel):
    """工单详情页里那条工单长什么样。

    比列表页多 14 个字段。跟 AssetDetail 一样，也是"挑"，不是全给 ——
    WorkOrder 一共 37 列，这儿 22 列。

    砍掉的那批基本是"整列都是空的"（都是 100% NULL，实测）：
        priority / sla_policy / sla_deadline / sla_source
        is_ppm / is_safety / is_reopened / has_warranty
        created_by_id / assigned_to_id

    priority 这个砍得最值得说：它 100% 是 NULL，而且不同值个数是 0。
    意思是这一列官方数据压根没给过。优先级本来是工单系统很重要的一个字段，
    但它得等平台自己录数据才会有值 —— 那是第 18 步之后的事。

    另外砍了两个：route（95% 空）、parent_source_record_id（96.6% 空）。
    source_updated_raw 也砍了，那是导入时留下的原样字符串，给人看不合适。
    """

    id: int
    source_record_id: str
    data_source: str
    # 指向 assets 表。官方数据里不少工单压根没关联资产，所以两列都可空
    asset_id: int | None
    asset_source_record_id: str | None
    description: str
    work_type: str | None
    work_class: str | None
    status: str
    # 这个状态是谁写的：DERIVED_FROM_SOURCE = 从来源数据推的，不是人改的。
    # 平台自己流转出来的状态才不是这个值，所以详情页上要给前端看这个区别
    status_origin: str
    source_status: str | None
    request_date: date | None
    created_source_at: datetime | None
    completion_date: date | None
    scheduled_end_date: date | None
    assigned_title: str | None
    source_notes: str | None
    duration: str | None
    job_type: str | None
    source_update_count: int | None
    created_at: datetime
    updated_at: datetime


class WorkOrderCreateRequest(BaseModel):
    """平台自己录一条工单时，前端要传什么。

    这里只留四个字段，不是把 WorkOrder 那 37 列倒过来抄一遍。
    挑选方向和详情页正好相反：详情页是"能给人看的尽量给"，
    这里是"不填就干不了活的才留"。

    description 是唯一必填的 —— 模型上它本来就是 nullable=False，
    而且一条没写描述的工单，拿给工程师他也不知道要去干什么。

    这几个 max_length 是照模型上对应列的长度写的，不是随手定的：
    在这儿挡住，前端当场拿到明确的 422，不用等写库那一步才炸。
    """

    description: str = Field(min_length=1, max_length=2000)
    # 官方数据里实测就 JOB / IN / AA / PPM / STAT / MRC 这几种，平台工单沿用这套
    work_type: str | None = Field(default=None, max_length=150)
    # 关联哪个资产。这儿存的是资产的来源编号（字符串），不是 assets.id。
    # 理由是平台录入时手上只有编号；真要换成 id 就得先查一次库，
    # 而这列在模型上本来就可空，没必要为了好看多搭一次查询
    asset_source_record_id: str | None = Field(default=None, max_length=100)
    scheduled_end_date: date | None = None
