/**
 * 登录成功后后端给的东西。
 * user 一并带回来了，所以登录那一刻不用再问一次"我是谁"。
 */
export interface LoginResult {
  access_token: string
  token_type: string
  expires_in: number
  user: UserIdentity
}

/**
 * 后端眼里的"我是谁"。
 *
 * role_codes 决定界面上显示什么角色；
 * permissions 是扁平的权限码列表 —— 后端直接算好了给前端，
 * 前端不用再自己维护一张"哪个角色能干什么"的表
 */
export interface UserIdentity {
  id: number
  username: string
  display_name: string
  email: string | null
  enabled: boolean
  role_codes: string[]
  permissions: string[]
  last_login_at: string | null
}

/**
 * 13 个权限点，跟后端 core/permissions.py 那个枚举一一对应。
 *
 * 抄成常量而不是到处写裸字符串，是为了拼错时 TypeScript 当场报错。
 * 裸字符串写错不会报错，只会安静地变成"没这个权限"，按钮莫名其妙就灰了
 */
export const PERMISSIONS = {
  ASSET_READ: 'asset:read',
  WORK_ORDER_READ: 'work_order:read',
  WORK_ORDER_CREATE: 'work_order:create',
  WORK_ORDER_UPDATE: 'work_order:update',
  WORK_ORDER_ASSIGN: 'work_order:assign',
  LABOR_READ: 'labor:read',
  LABOR_CREATE: 'labor:create',
  TRANSACTION_READ: 'transaction:read',
  DASHBOARD_READ: 'dashboard:read',
  ANALYTICS_READ: 'analytics:read',
  USER_MANAGE: 'user:manage',
  ROLE_MANAGE: 'role:manage',
  OPERATION_LOG_READ: 'operation_log:read',
} as const

/** 角色码对应的中文名。库里存的是 ADMIN 这种，界面上要显示"管理员" */
export const ROLE_LABELS: Record<string, string> = {
  ADMIN: '管理员',
  DISPATCHER: '调度员',
  ENGINEER: '工程师',
  VIEWER: '访客',
}
