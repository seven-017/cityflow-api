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

/** 数据源。只有「平台录入」那种能改，官方导入的是只读的 */
export const DATA_SOURCE_LABELS: Record<string, string> = {
  REAL_PUBLIC: '官方导入',
  SYNTHETIC_PLATFORM: '平台录入',
}

/**
 * 状态是谁写上去的。
 *
 * 三个值都是从库里数出来的（2026-10-08）：
 *
 *     SOURCE_FIELD          2155012 条   97%  来源文件里那个 status 字段原样抄过来的
 *     DERIVED_FROM_SOURCE      65841 条    3%  来源没给现成的状态，是按规则推出来的
 *     PLATFORM                     6 条        平台自己流转出来的
 *
 * 前两个都不是人改的，界面上别让人误以为「有人把状态改成了这样」。
 *
 * 这儿一开始只写了 DERIVED_FROM_SOURCE —— 因为模型上那个 default 就是这个值。
 * 结果截图一看，97% 的单在详情页上直接裸着一个 SOURCE_FIELD。
 * 教训：常量表照代码抄不如照数据抄，代码里那个 default 只是"没写的时候填什么"，
 * 不代表库里真有什么
 */
export const STATUS_ORIGIN_LABELS: Record<string, string> = {
  SOURCE_FIELD: '来源字段原样',
  DERIVED_FROM_SOURCE: '来源数据推导',
  PLATFORM: '平台流转',
}

/** 一条状态流水：这单什么时候、被谁、从哪个状态推到了哪个状态 */
export interface WorkOrderStatusHistoryItem {
  id: number
  /** 建单那一条是 null —— 它不是从哪个状态过来的，是被造出来的，别当数据缺失 */
  from_status: string | null
  to_status: string
  operator_id: number | null
  /** 只有驳回会带原因，别的动作都是 null */
  reason: string | null
  created_at: string
}

/** 工单底下人留的一句备注 */
export interface WorkOrderRecordItem {
  id: number
  work_order_id: number
  user_id: number | null
  content: string
  created_at: string
}

/**
 * 详情页那条工单。字段跟后端 WorkOrderDetail 对齐，是挑过一轮的，
 * 不是把 WorkOrder 那 37 列抄一遍。
 *
 * 里面有不少字段在官方那批数据上永远是 null（asset_id、scheduled_end_date、
 * assigned_title、duration 这些），平台自己录的单才填得出来 ——
 * 所以详情页上都得按「可能没值」来显示。
 */
export interface WorkOrderDetail {
  id: number
  source_record_id: string
  data_source: string
  asset_id: number | null
  asset_source_record_id: string | null
  description: string
  work_type: string | null
  work_class: string | null
  status: string
  /** PLATFORM = 平台自己流转出来的；DERIVED_FROM_SOURCE = 从来源数据推的 */
  status_origin: string
  source_status: string | null
  request_date: string | null
  created_source_at: string | null
  completion_date: string | null
  scheduled_end_date: string | null
  assigned_title: string | null
  /** 派给谁了。官方那批永远是 null，平台录的单分派之后才有值 */
  assigned_to_id: number | null
  source_notes: string | null
  duration: string | null
  job_type: string | null
  source_update_count: number | null
  /** 下面三个一组，只有平台自己录的单才有值 */
  priority: string | null
  sla_deadline: string | null
  sla_source: string | null
  created_at: string
  updated_at: string
  /**
   * 两个子表。详情页跟列表页的区别就在这儿 ——
   * 列表一行一个工单，详情要把「这单经历过什么」一起端出来。
   * 都不分页：状态流水一单顶多几行，备注也就个位数到几十
   */
  status_history: WorkOrderStatusHistoryItem[]
  processing_records: WorkOrderRecordItem[]
}

/**
 * 能对工单做的五个流转动作。跟后端 WorkOrderAction 一对。
 *
 * 没有「创建」—— 创建是造出来一张新的，不是从哪个状态走过去，
 * 不归状态机管，所以这儿也不该有它
 */
export type WorkOrderAction = 'ASSIGN' | 'START' | 'COMPLETE' | 'CLOSE' | 'REJECT'

/** 动作的中文名，就是按钮上那几个字 */
export const ACTION_LABELS: Record<WorkOrderAction, string> = {
  ASSIGN: '分派',
  START: '开始处理',
  COMPLETE: '完成',
  CLOSE: '关闭',
  REJECT: '驳回',
}

/** 动作 -> 目标状态。跟后端 core/work_order_status.py 的 ACTION_TARGET 一对 */
export const ACTION_TARGET: Record<WorkOrderAction, string> = {
  ASSIGN: 'ASSIGNED',
  START: 'IN_PROGRESS',
  COMPLETE: 'COMPLETED',
  CLOSE: 'CLOSED',
  REJECT: 'REJECTED',
}

/**
 * 从某个状态出发允许走到哪几个状态。跟后端 ALLOWED_TRANSITIONS 一对。
 *
 * 这份是照抄后端来的，改那边就得改这边 —— 但两边管的事儿不一样：
 * 后端那张是「判不判得动」，这张只是「按钮摆不摆出来」。
 * 前端写错了顶多是按钮多一个少一个，真正拦住的是后端，
 * 它那边判不过会甩 409（状态对不上）或者 403（数据源不对、不是你的单）。
 *
 * 两个空数组不是漏写：REJECTED 和 CLOSED 是死胡同，哪儿也去不了。
 * 留成空数组而不是把这俩键删掉，是因为「去不了任何地方」和
 * 「压根没这个状态」是两回事，后者只会让人以为是自己漏填了
 */
export const ALLOWED_TRANSITIONS: Record<string, string[]> = {
  PENDING: ['ASSIGNED', 'REJECTED'],
  ASSIGNED: ['IN_PROGRESS', 'REJECTED'],
  IN_PROGRESS: ['COMPLETED'],
  COMPLETED: ['CLOSED'],
  REJECTED: [],
  CLOSED: [],
}

/** 当前状态能做哪几个动作。判法跟后端 resolve_transition 完全一致：看目标状态在不在允许表里 */
export function availableActions(status: string): WorkOrderAction[] {
  const allowed = ALLOWED_TRANSITIONS[status] ?? []
  return (Object.keys(ACTION_TARGET) as WorkOrderAction[]).filter((action) =>
    allowed.includes(ACTION_TARGET[action]),
  )
}

/**
 * 这个角色能不能做这个动作。跟后端 ENGINEER_ALLOWED_ACTIONS 一对。
 *
 * ADMIN / DISPATCHER 不挑动作；其余角色（实际就是 ENGINEER）只放行
 * 开始和完成 —— 「开始」「完成」是干活的人干完自己那摊活，
 * 「驳回」「关闭」是这张单接下来怎么走，归调度和管理。
 *
 * 一开始这儿是空的，光靠权限点过滤，结果是工程师看一张别人的待处理单，
 * 上面会摆一个「驳回」出来，点了必然 403。补这一层是因为它判断依据只有
 * 「我是谁」，跟权限点同一层，属于该摆什么按钮的范畴。
 *
 * 但再往下那层「工程师只能碰派给自己的单」前端没做，故意的 ——
 * 那条要拿具体的单和当前用户去比，是数据级判断，
 * 让它落到后端，判不过会甩 403，把话说清楚就行
 */
export function allowedByRole(action: WorkOrderAction, roleCodes: string[]): boolean {
  if (roleCodes.includes('ADMIN') || roleCodes.includes('DISPATCHER')) return true
  return action === 'START' || action === 'COMPLETE'
}

/**
 * 每个动作要哪个权限点。
 *
 * 分派单独一个 work_order:assign（ADMIN / DISPATCHER 有，ENGINEER / VIEWER 没有），
 * 其余四个共用 work_order:update。
 *
 * 注意这只是第一层闸门。后端还有第二层，前端故意不复制：
 * 「工程师只能开始/完成派给自己的单」那条要拿具体的单和当前用户去比，
 * 是数据级的判断 —— 前端提前判反而容易判错，让它落到后端，
 * 判不过会甩 403，前端把话说清楚就行
 */
export const ACTION_PERMISSIONS: Record<WorkOrderAction, string> = {
  ASSIGN: 'work_order:assign',
  START: 'work_order:update',
  COMPLETE: 'work_order:update',
  CLOSE: 'work_order:update',
  REJECT: 'work_order:update',
}

/** 按钮颜色。只有驳回那一档是红的，别的都往中性靠 */
export const ACTION_BUTTON_TYPES: Record<
  WorkOrderAction,
  'primary' | 'success' | 'info' | 'danger'
> = {
  ASSIGN: 'primary',
  START: 'primary',
  COMPLETE: 'success',
  CLOSE: 'info',
  REJECT: 'danger',
}
