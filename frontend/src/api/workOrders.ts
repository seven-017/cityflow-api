import { get } from '@/api/http'
import type { CursorResponse } from '@/types/api'
import type { WorkOrderSummary } from '@/types/workOrder'

/**
 * 工单列表。
 *
 * 游标分页的用法：第一页不传 afterId，把返回的 meta.next_cursor
 * 留给下一页当 afterId 传回来。别自己拿 id 加减 ——
 * 游标是"上一页最后一条的位置"，不是页码
 */
export function listWorkOrders(
  afterId?: number,
  limit = 20,
): Promise<CursorResponse<WorkOrderSummary>> {
  // afterId 是 undefined 时 axios 不会把它拼进查询串，
  // 正好等于"不传这个参数"，不用自己拼字符串
  return get<CursorResponse<WorkOrderSummary>>('/work-orders', { after_id: afterId, limit })
}
