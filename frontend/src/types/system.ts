/**
 * 系统那边的用户。跟后端 schemas/system.py 的 UserSummary 对齐。
 *
 * 注意里头没有 password_hash —— schema 就是一张白名单，
 * 没写上去的字段后端一个都不会发出来。
 */
export interface UserSummary {
  id: number
  username: string
  display_name: string
  email: string | null
  enabled: boolean
  role_codes: string[]
  last_login_at: string | null
}
