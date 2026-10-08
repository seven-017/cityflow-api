import { get, post } from '@/api/http'
import type { CursorResponse } from '@/types/api'
import type {
  WorkOrderDetail,
  WorkOrderRecordItem,
  WorkOrderSummary,
} from '@/types/workOrder'

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

/** 一张工单的详情，连带它的状态流水和处理记录一起回来了 */
export function getWorkOrder(id: number): Promise<WorkOrderDetail> {
  return get<WorkOrderDetail>(`/work-orders/${id}`)
}

/**
 * 分派：把这单派给某个工程师。
 *
 * 只能派给「启用的、有 ENGINEER 角色的人」—— 这是后端三道闸门里的最后一道。
 * 前端下拉也按这个筛，但筛完不代表一定派得成，真正的判在后端，
 * 它不认会甩 400 回来
 */
export function assignWorkOrder(id: number, assigneeId: number): Promise<WorkOrderDetail> {
  return post<WorkOrderDetail>(`/work-orders/${id}/assign`, { assignee_id: assigneeId })
}

// 下面三个没有请求体：谁点的、什么时候点的服务端自己知道，
// 前端传过去反而白给它一个说谎的机会
export function startWorkOrder(id: number): Promise<WorkOrderDetail> {
  return post<WorkOrderDetail>(`/work-orders/${id}/start`)
}

export function completeWorkOrder(id: number): Promise<WorkOrderDetail> {
  return post<WorkOrderDetail>(`/work-orders/${id}/complete`)
}

export function closeWorkOrder(id: number): Promise<WorkOrderDetail> {
  return post<WorkOrderDetail>(`/work-orders/${id}/close`)
}

/**
 * 驳回。四个动作里只有它要请求体 ——
 * 驳回是一条"这活我不干了"的记录，三个月后翻流水，
 * 光看见一个 REJECTED 是不知道该找谁问为什么的
 */
export function rejectWorkOrder(id: number, reason: string): Promise<WorkOrderDetail> {
  return post<WorkOrderDetail>(`/work-orders/${id}/reject`, { reason })
}

/**
 * 在工单底下留一句备注。
 *
 * 返回的是那条记录本身，不是整张工单 —— 这样加完直接往列表末尾追加就行，
 * 不用为了看自己刚写的几个字再把详情整个拉一遍
 */
export function addWorkOrderRecord(id: number, content: string): Promise<WorkOrderRecordItem> {
  return post<WorkOrderRecordItem>(`/work-orders/${id}/records`, { content })
}
