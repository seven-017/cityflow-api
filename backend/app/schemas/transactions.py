from datetime import date, datetime

from pydantic import BaseModel

from app.schemas.common import CursorMeta


class TransactionLineItem(BaseModel):
    """交易明细里的一行：领了什么料、几个、什么单位。

    这张表（transaction_details，229 万行）的字段是 2026-10-02 按 NULL 占比挑的，
    但跟挑 labor 那次不一样 —— 这回「有一条是靠"冗余比对"砍掉的」，
    光看 NULL 占比看不出来：

        detail_type   0% NULL，一个空值都没有，6 种值，按老判据该留下。
                      可是跟头表比过：2290091 行里，它跟
                      transactions.transaction_type 不等的有 0 行。
                      也就是说这一列是头的类型原样抄了一份。
                      ⇒ 砍了。留着就是"同一件事有两个字段"，早晚会不一致 ——
                      而这两个字段的不一致没人会去查，只会有人踩。

    反过来，有一列看着像冗余、其实不是：

        transaction_date  0% NULL。第一反应是"明细的日期不就是头的日期吗"。
                          量了一下：「2290091 行里有 89989 行（3.9%）跟头的不一样。」
                          ⇒ 留着。那 3.9% 就是它存在的理由；
                          要是真的一样，它就该跟 detail_type 一起被砍掉。

    砍掉的那几列（NULL 占比太高，跟当初砍 work_orders.route(95%) 一个口径）：
        action                90.07%
        event_source_record_id 64.76%
        requested_line        55.81%

    没带 transaction_id：明细只在交易详情里出现，外面那层已经说了是哪张单。
    （跟 18e 那条备注不一样 —— 那条备注有"加备注"和"看详情"两个返回口，
    所以留着 work_order_id 让两边形状一致。明细只有这一个口，没有第二个消费方。）
    """

    id: int
    source_record_id: str
    # 原始 TRL_TRANS，跟 labor 那边的 source_work_order_record_id 是一回事：
    # 外键解析之前先留一手
    transaction_source_record_id: str | None
    # 单内行号。实测是 '2865' '301' 这种字符串，不是数字 —— 所以 schema 里也是 str
    line_number: str | None
    # 96.1% 跟头的日期一样，但剩下 3.9% 不一样，所以留着
    transaction_date: date | None
    # 物料编码。14400 种，是明细这一层的主键语义
    part_code: str | None
    # 物料名，比如 'Pipe, Wall Bend, Chrome, 1 1/4'。这一列是给人看的
    part_description: str | None
    # 物料分类，213 种
    part_class: str | None
    # 计量单位，24 种，比如 'EA'（each，按个）
    part_uom: str | None


class TransactionDetail(BaseModel):
    """交易详情：头 + 一页明细 + 明细的翻页说明。

    头那 16 个字段：
        0% NULL 的 11 个，加上 work_order_id / source_work_order_record_id（各 33.04% 空）、
        to_entity / to_code（各 3.64% 空）。

    砍掉一个：request_number，78.63% 是 NULL。
    跟当初砍 work_orders.route（95% 空）是同一个判据：一列快八成都是空的，
    列表和详情上它都是一片空白，留着只是让 schema 长一点。

    有一处跟 labor 那边对比很明显，值得记一笔：
        work_order_id 在这个表上缺 33.04%（248712 行），而 work_order_labor 只缺 0.41%。
        也就是说「物料移动里三分之一压根不挂工单」（例行的收发料不属于任何一张维修单），
        而工时几乎总是挂着的（那是人工填的，填的时候就必须选单）。
        所以详情页上这一列显示成空是正常的，不是数据缺了。

    没带 created_at / updated_at：这张表全是导入数据，那两列只是"我们什么时候导进来的",
    对看数据的人没意义。跟 AssetDetail 一个口径（AssetDetail 也没带）。
    （WorkOrderDetail 带，是因为平台自己建的工单需要那两列。）

    details / detail_meta 为什么会有：
        文档说这个接口"返回交易头信息和逐行物料明细"，读起来像要一次全给。
        没照做 —— 实测有单子的明细多达 3628 行，序列化成 JSON 是 812932 字节，
        而 20 行只有 4393 字节。理由和数字写在 repositories/transactions.py 里。
        所以这儿的结构是「头 + 一页明细 + 一个游标」。
    """

    id: int
    # 官方数据集里那串交易号（TRA_CODE），跟 assets 的 source_record_id 是一个来路
    source_record_id: str
    data_source: str
    # 33.04% 是空的 —— 物料移动本来就不一定挂工单，理由见类注释
    work_order_id: int | None
    source_work_order_record_id: str | None
    description: str | None
    # 6 种值（RECV / STTK / I ...）。码什么意思文档里没给，不翻译，原样发出去
    transaction_type: str | None
    transaction_date: date | None
    # 3 种值，样例里见过 'A'
    status: str | None
    # 下面四列要一起看，它们说的是同一件事：这批料从哪到哪。
    # from_entity / to_entity 是"对象类型"（2 种值），各带一个具体编码。
    # 文档里管 to_entity + to_code 叫 polymorphic target lookup —— 目标是多态的，
    # 所以必须两列一起才说得清"去了哪儿"，光看 to_code = 'M-TS' 不知道 M-TS 是什么
    from_entity: str | None
    from_code: str | None
    to_entity: str | None
    to_code: str | None
    # 导入时"这条源记录被更新过几次"（11 种值）。
    # 对看数据的人没什么意义，但它是 ETL 挑"保留哪个版本"的依据 ——
    # 排障时能从这儿看出这条是第几版
    source_update_count: int | None
    source_created_at: datetime | None
    source_updated_at: datetime | None

    # 一页明细。跟 18f 给工单详情加 status_history 一样，是平铺在头字段旁边的，
    # 不另起一层 {"header": {...}, "details": [...]} —— 前端少剥一层
    details: list[TransactionLineItem]
    # 明细的翻页说明。复用 CursorMeta，形状跟别的列表接口一模一样：
    # 前端拿 detail_meta.next_cursor 当下一次的 detail_after_id 传回来
    detail_meta: CursorMeta
