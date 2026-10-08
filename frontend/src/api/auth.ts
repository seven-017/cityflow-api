import { get, post } from '@/api/http'
import type { LoginResult, UserIdentity } from '@/types/auth'

/** 登录换 token。用户名密码走请求体，不放 URL 上（URL 会被记进访问日志） */
export function login(username: string, password: string): Promise<LoginResult> {
  return post<LoginResult>('/auth/login', { username, password })
}

/** 我是谁。刷新页面之后靠它恢复登录状态 */
export function fetchCurrentUser(): Promise<UserIdentity> {
  return get<UserIdentity>('/auth/me')
}
