from datetime import date, datetime

from pydantic import BaseModel, Field

from app.core.work_order_sla import WorkOrderPriority


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

    跟 AssetDetail 一样，字段是"挑"出来的，不是把 WorkOrder 那 37 列抄一遍。

    挑选依据是各列的 NULL 占比（实测），所以这张名单会来回变 ——
    砍掉一个字段的依据是"这一列到底有没有值"，**依据变了就得跟着改**。
    已经来回变过两次了，都记在这儿，免得后来的人看着纳闷：

        priority / sla_deadline / sla_source    砍过，又加回来
            当初砍的理由是"官方数据里 100% 是 NULL，给了也是一片空白"。
            现在平台自己建的工单会填这三列（录单时选优先级、建单时算 deadline），
            它们有真实含义了。官方那两百万单仍然是 NULL，详情页显示成空就好。

        assigned_to_id                          砍过，又加回来
            理由同上 —— 分派做完之后它才有值。

    仍然砍掉的（都是 100% NULL，官方数据压根没给过）：
        sla_policy / is_ppm / is_safety / is_reopened / has_warranty / created_by_id
        （sla_policy 是我们自己决定不填的，理由写在 core/work_order_sla.py 里）

    另外砍了两个空得没那么彻底的：route（95% 空）、parent_source_record_id（96.6% 空）。
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
    # 这一列原来被砍掉了，理由是"官方数据里 100% 是 NULL，给了也是一片空白"。
    # 现在平台工单能分派了，它有了真实含义，所以加回来 ——
    # 砍掉一个字段的依据是"这一列有没有值"，依据变了就得跟着改，
    # 不然就会出现"功能做完了但前端拿不到结果"这种事
    assigned_to_id: int | None
    source_notes: str | None
    duration: str | None
    job_type: str | None
    source_update_count: int | None
    # 下面这三个是一组，只有平台自己建的工单才有值（官方那批全是 NULL，
    # 文档说过不给历史数据伪造 SLA）。
    # priority 是录单时选的，sla_deadline 是建单那一刻按优先级算出来的，
    # sla_source 记这个 SLA 是谁给的 —— 平台算的一律是 PLATFORM_RULE
    priority: str | None
    sla_deadline: datetime | None
    sla_source: str | None
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
    # 优先级。不填就按 P4 算 —— P4 是最不急的那一档，
    # 录单的人没评估过，就让这张单排到最后去，总比让它去挤急单的位置强。
    #
    # 另一种做法是"没填就不算 SLA"（priority 和 sla_deadline 都留空），
    # 但那样列表页和详情页都得处理"有值/没值"两套显示，第一版不折腾这个。
    #
    # 类型用的是 StrEnum 而不是 str：Pydantic 会拿它做校验，
    # 传个 P5 进来当场 422，不用等落到库里才发现有这么个优先级
    priority: WorkOrderPriority = WorkOrderPriority.P4


class WorkOrderAssignRequest(BaseModel):
    """分派工单时只传一个东西：派给谁。

    被派的那个人是不是存在、有没有被停用、是不是 ENGINEER —— 这些都不在这儿校验，
    得去 service 里查库。schema 只管"这个字段本身合不合法"（负数 id 直接 422），
    管不了"库里到底有没有这个人"。
    """

    assignee_id: int = Field(gt=0)


class WorkOrderRejectRequest(BaseModel):
    """驳回要带的东西：就一个原因。

    开始 / 完成 / 关闭这三个动作都不要请求体 —— 谁做的、什么时候做的服务端自己知道，
    前端传过来反而是白给它一个说谎的机会。

    只有驳回不行。驳回是一条"这活我不干了"的记录，三个月后翻流水，
    光看见一个 REJECTED 是不知道该找谁问为什么的。所以这儿必填。

    500 这个上限是照模型上 reason 那一列的长度写的（String(500)），
    在这儿挡住，前端当场拿到明确的 422，不用等写库才炸。
    """

    reason: str = Field(min_length=1, max_length=500)


class WorkOrderRecordRequest(BaseModel):
    """在工单下面留一条处理记录，也就是一句备注。"""

    # 2000 这个上限不是数据库的限制 —— 模型上那一列是 Text，能吃六万多字节。
    # 是我们自己定的：一条备注写到两千字还没写完，多半是该拆成几条，
    # 或者那些内容本来就该放到别的地方（工单描述、附件）。
    # 给个上限还有个好处：挡住"前端把整个日志文件糊进来"这种事
    content: str = Field(min_length=1, max_length=2000)


class WorkOrderRecordItem(BaseModel):
    """一条处理记录长什么样。

    这是全项目第一个"子资源"的返回体 —— 前面几个接口都是返回工单本身，
    这个不是。为什么单独给一个：加完备注之后，前端最需要的是
    "我这条加上了，长这样"，好直接往列表末尾追加一条；
    为了看清楚自己刚写的几个字再拉一次工单详情，纯属浪费。

    没带用户名。要带就得 JOIN 一次 users，而前端本来就有用户表、
    拿着 user_id 自己查得到。等真有页面需要"张三 5 分钟前说"这种展示，
    再考虑是后端 JOIN 还是前端查。
    """

    id: int
    work_order_id: int
    user_id: int | None
    content: str
    created_at: datetime
