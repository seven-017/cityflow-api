/**
 * 工单列表里的一行。
 *
 * 字段跟后端 schemas/work_orders.py 的 WorkOrderSummary 对齐 ——
 * 那边是个白名单，没写在那儿的字段前端根本收不到，
 * 所以这儿多写字段不会让代码报错，只会在运行时变成 undefined
 */
export interface WorkOrderSummary {
  id: number
  source_record_id: string
  data_source: string
  description: string
  /** 实测只有 JOB / IN / AA / PPM / STAT / MRC 这几种，也可能为空 */
  work_type: string | null
  status: string
  /** 官方数据里这一列缺 15%，所以列表上要能接受空值 */
  request_date: string | null
  completion_date: string | null
}

/** 六个状态的中文名。历史数据里只会出现其中三个（官方那批没走完整个流转） */
export const WORK_ORDER_STATUS_LABELS: Record<string, string> = {
  PENDING: '待处理',
  ASSIGNED: '已分派',
  IN_PROGRESS: '处理中',
  COMPLETED: '已完成',
  CLOSED: '已关闭',
  REJECTED: '已驳回',
}

/**
 * 状态对应的标签颜色。
 *
 * 只有一档"坏"的颜色（danger 给 REJECTED），其余按"进度越靠后越淡"排 ——
 * 全都上色的话，一屏花花绿绿的，反而看不出哪条有问题
 */
export const WORK_ORDER_STATUS_TAGS: Record<
  string,
  'primary' | 'success' | 'warning' | 'danger' | 'info'
> = {
  PENDING: 'warning',
  ASSIGNED: 'primary',
  IN_PROGRESS: 'primary',
  COMPLETED: 'success',
  CLOSED: 'info',
  REJECTED: 'danger',
}
