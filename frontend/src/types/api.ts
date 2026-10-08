/**
 * 后端所有接口的返回壳子：code 为 0 才算成功，东西全在 data 里。
 *
 * 这么包一层的好处是前端只需要一套判断逻辑 ——
 * 看 code，而不是挨个接口去猜它成功时返回的是对象、数组还是空。
 */
export interface ApiResponse<T> {
  code: number
  message: string
  data: T
}

/**
 * 游标分页的说明书。
 *
 * 注意它没有 total，也没有 page / pages —— 后端真的不返回这些。
 * 所以列表页做不出"第 3 页 / 共 50 页"这种页码条，
 * 只能做"加载更多"。这不是前端偷懒，是分页方式决定的
 */
export interface CursorMeta {
  limit: number
  /** 下一页的起点。把它原样当作下次请求的 after_id 传回去就行。到底了是 null */
  next_cursor: number | null
  has_more: boolean
}

export interface CursorResponse<T> {
  items: T[]
  meta: CursorMeta
}

/**
 * 页码分页的说明书。跟游标那套正相反 —— 它真给总数。
 *
 * 项目里两套并存不是历史遗留：工单和资产那种百万级大表走游标，
 * 因为算一次总数要几百毫秒；用户这种一共四行的表走页码，
 * 算总数不心疼，而且「第 1 页 / 共 1 页」对看的人更直观
 */
export interface PageMeta {
  page: number
  page_size: number
  total: number
  pages: number
}

export interface PageResponse<T> {
  items: T[]
  meta: PageMeta
}
