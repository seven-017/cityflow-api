from sqlalchemy.orm import Session

from app.models import WorkOrderLabor
from app.repositories.labor import LaborRepository
from app.schemas.common import CursorMeta
from app.schemas.labor import LaborSummary


def labor_summary(row: WorkOrderLabor) -> LaborSummary:
    """把一条 WorkOrderLabor 搬成 LaborSummary。

    第四个搬运函数了（asset_summary / asset_detail / work_order_summary /
    work_order_detail / 这个）。规矩跟前几个一样：ORM 对象不能直接往外扔，
    得把要发的字段一个个搬过来。
    """
    return LaborSummary(
        id=row.id,
        source_record_id=row.source_record_id,
        data_source=row.data_source,
        work_order_id=row.work_order_id,
        source_work_order_record_id=row.source_work_order_record_id,
        action=row.action,
        work_date=row.work_date,
        trade=row.trade,
        operation_type=row.operation_type,
        hours=row.hours,
        rate=row.rate,
        cost=row.cost,
    )


class LaborService:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.labor = LaborRepository(db)

    def list_labor(
        self,
        *,
        after_id: int | None,
        limit: int,
        work_order_id: int | None = None,
    ) -> tuple[list[LaborSummary], CursorMeta]:
        """翻页查工时。

        跟 assets / work_orders 两个列表一个套路：仓库层多要一行探路，
        这儿看它到底有没有多给，多出来那行裁掉。

        没做的事，明说，免得以后有人以为是漏了：

        1. 没有 total。理由跟另两个列表完全一样，写在 schemas/common.py 的
           CursorMeta 上 —— 320 万行上算一次 COUNT 是纯浪费，而且游标分页
           本来也跳不了页，那个数字没人会用。

        2. 工单不存在时不报 404。传个不存在的 work_order_id 就是查到空列表 ——
           这是列表接口该有的行为，不是详情接口。前端拿空列表显示"暂无记录"，
           比甩个 404 让它单独处理一条分支要简单。而且"这单有没有工时"
           和"这单存不存在"是两回事，列表接口不该替详情接口回答第二个问题。

        3. 没做 keyword / trade / operation_type / asset_id / date_from / date_to
           这几个文档列出来的过滤条件。分两种说：

           没索引撑着的（keyword、date_from/date_to）——
           320 万行上做 LIKE '%xx%' 或者日期范围全扫，快不了。
           真要做，得先把索引加上、量过分页代价再说，不能先写接口后想性能。

           结构上就做不了的（asset_id）——
           文档 api.md 里 GET /labor 的参数列了 asset_id，但 work_order_labor
           这张表上压根没有 asset_id 这一列（表结构是从 AMPS 原始字段映射过来的，
           那些字段里就没有资产）。要按资产过滤只能 JOIN work_orders（222 万行）
           再拿 w.asset_id 比，那是一次跨 320 万和 222 万行的连接。
           而且资产那边要的是"统计"不是"明细"（api.md 里资产详情返回的是
           Labor 统计），统计该怎么算属于聚合接口的事，不该硬塞进列表。

           这就能看出一件事：文档和表结构不是永远对得上的。
           文档写参数的时候想的是"用户可能想按什么筛"，表结构说的是"手上有什么"。
           两边打架的时候，先看能不能做（asset_id 不能），再看值不值得做（keyword 不值），
           而不是照着文档把参数名抄一遍然后留个空实现。
        """
        # 仓库层故意多要了一行，这里看它到底有没有多给
        rows = self.labor.list_labor(
            after_id=after_id, limit=limit, work_order_id=work_order_id
        )
        has_more = len(rows) > limit
        # 多出来那一条只是用来探测"还有没有下一页"的，不能发给前端
        page_rows = rows[:limit]
        # 下一页从哪开始？就是这一页最后那条的 id。
        # has_more 为假的时候给 None，让前端一眼看出到底了
        next_cursor = page_rows[-1].id if has_more and page_rows else None
        items = [labor_summary(r) for r in page_rows]
        return items, CursorMeta(
            limit=limit,
            next_cursor=next_cursor,
            has_more=has_more,
        )
