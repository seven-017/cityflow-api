import type { WorkOrderDetail } from '@/types/workOrder'

/**
 * Dashboard 首页那十个指标。
 *
 * 三个金额/工时字段是**字符串**不是数字 —— 后端用 Decimal 算的，
 * 序列化出来就是带引号的 "19794050.87"。这是故意的，金额过 float 会掉精度。
 *
 * 所以前端这儿分两种用法：
 *   要往图上画，得自己 Number() 一下（这个量级在 double 安全范围内，不会掉）
 *   要显示给人看，直接当字符串用，顺手加个千分位就行
 */
export interface DashboardMetrics {
  asset_count: number
  work_order_count: number
  /** 待处理 / 已分派 / 处理中 */
  unfinished_work_order_count: number
  /** 已完成 / 已关闭 */
  finished_work_order_count: number
  /** 驳回那条岔路。单独占一个桶，不让它落到别处去 */
  rejected_work_order_count: number
  labor_record_count: number
  labor_total_hours: string | null
  labor_total_cost: string | null
  transaction_count: number
  transaction_detail_count: number
}

/** 状态分布图的一根柱子。status 用 str 是后端的决定，说库里有枚举外的值也要照原样画出来 */
export interface StatusDistribution {
  status: string
  work_order_count: number
}

/** 工单类型分布。work_type 可空 —— 平台自己建的工单不填它 */
export interface WorkTypeDistribution {
  work_type: string | null
  work_order_count: number
}

/** 资产类型分布。这一项后端不补零，只报库里现有的 */
export interface AssetTypeDistribution {
  asset_type: string | null
  asset_count: number
}

/** 高维护资产榜的一条。名次就是数组下标 + 1，后端没给 rank 字段 */
export interface HighMaintenanceAsset {
  asset_id: number
  asset_type: string | null
  description: string
  work_order_count: number
}

/**
 * 平均处理周期。不是一个图，是一个数加两句限定。
 *
 * window_months 和 sample_count 必须跟着一起显示 —— 21.87 天是
 * 「最近 12 个月」还是「全历史」算的，含义能差一倍多（实测全历史 50.72 天）。
 * 光甩一个天数出去，看的人只能瞎猜，那还不如不显示
 */
export interface ResolutionSummary {
  average_days: string | null
  sample_count: number
  window_months: number
}

export interface WorkOrderTrendPoint {
  /** 'YYYY-MM'。不是日期对象，后端说它本来就是给横轴当标签用的 */
  month: string
  work_order_count: number
}

/**
 * 工时趋势的一个点。比另外两个趋势多两个数，都可空。
 *
 * 提醒一句（不是这儿的问题，是数据本身）：2026-08 那个点会特别高，
 * 因为那边有一条 hours=1929817 的脏数据（算下来 220 年）。
 * 图上那根擎天柱不是 bug，是数据真的长这样
 */
export interface LaborTrendPoint {
  month: string
  record_count: number
  total_hours: string | null
  total_cost: string | null
}

export interface TransactionTrendPoint {
  month: string
  transaction_count: number
}

/**
 * 最近工单列表里的一条。
 *
 * 可以复用工单详情那边的字段名，所以干脆从 WorkOrderDetail 里 Pick ——
 * 手抄一遍的话，哪天那边改了名这边不会报错
 */
export type RecentWorkOrder = Pick<
  WorkOrderDetail,
  'id' | 'status' | 'description' | 'work_type' | 'request_date' | 'completion_date'
> & { asset_id: number | null }

export interface DashboardCharts {
  status_distribution: StatusDistribution[]
  work_type_distribution: WorkTypeDistribution[]
  asset_type_distribution: AssetTypeDistribution[]
  high_maintenance_assets: HighMaintenanceAsset[]
  resolution_summary: ResolutionSummary
  work_order_trend: WorkOrderTrendPoint[]
  labor_trend: LaborTrendPoint[]
  transaction_trend: TransactionTrendPoint[]
  recent_work_orders: RecentWorkOrder[]
}

export interface DashboardOverview {
  metrics: DashboardMetrics
  charts: DashboardCharts
}
