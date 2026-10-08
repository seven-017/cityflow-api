import { get } from '@/api/http'
import type { PageResponse } from '@/types/api'
import type { UserSummary } from '@/types/system'

/**
 * 用户列表。
 *
 * 它要的是 user:manage，四个角色里只有 ADMIN 拿得到 ——
 * 也就是说 DISPATCHER 虽然能分派工单（有 work_order:assign），
 * 却看不到该派给谁。这是后端两个权限点没配合上留下来的缝，
 * 前端补不了。所以调它的地方都得做好收 403 的准备，不能让它把页面搞挂
 *
 * page_size 默认给满 100：这张表一共就四个人，多翻一页纯属浪费
 */
export function listUsers(page = 1, pageSize = 100): Promise<PageResponse<UserSummary>> {
  return get<PageResponse<UserSummary>>('/system/users', { page, page_size: pageSize })
}
