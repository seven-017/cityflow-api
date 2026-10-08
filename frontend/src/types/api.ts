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
