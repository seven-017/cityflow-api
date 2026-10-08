import axios, { type AxiosError } from 'axios'

import { useAuthStore } from '@/stores/auth'
import type { ApiResponse } from '@/types/api'

/**
 * 后端报错时抛出来的东西，比普通的 Error 多带一个业务错误码。
 *
 * 为什么非要有 code：HTTP 409 底下有两种完全不同的情形 ——
 * 40900 是"这个动作在当前状态下不允许"（该刷新页面看看到哪一步了），
 * 40901 是"两个人同时改同一行，你慢了一步"（重试一下可能就成了）。
 * 只看 message 分不出这两种，前端也就没法分别提示
 */
export class ApiError extends Error {
  readonly code: number
  readonly status: number | undefined

  constructor(code: number, message: string, status?: number) {
    super(message)
    this.name = 'ApiError'
    this.code = code
    this.status = status
  }
}

const http = axios.create({
  baseURL: '/api/v1',
  // 默认是 0，也就是"永不超时"，不太靠谱；
  // 但常见那档 10 秒也不合适 —— Dashboard 冷启动要跑十几秒的聚合，
  // 10 秒会把一个正常请求误杀掉。60 秒是给那个接口留的余量
  timeout: 60000,
})

http.interceptors.request.use((config) => {
  const token = useAuthStore().token
  if (token) {
    config.headers.Authorization = `Bearer ${token}`
  }
  return config
})

http.interceptors.response.use(
  (response) => response,
  (error: AxiosError<ApiResponse<null>>) => {
    const body = error.response?.data
    const status = error.response?.status
    // 网络断了、后端没起来这类情况，连 response 都没有，只能退回 axios 自己的话
    const code = body?.code ?? 0
    const message = body?.message ?? error.message

    // 401 说明 token 无效、过期，或者账号被停用了。
    // 统一在这儿处理，是因为每个接口都可能撞上，
    // 挨个页面去判断一定会漏掉几个
    if (status === 401) {
      useAuthStore().logout()
      // 这里用 location 跳转而不是 router.push，
      // 否则本模块要反过来 import router，跟 router 里 import store 绕成一个环
      if (!window.location.pathname.startsWith('/login')) {
        window.location.href = '/login'
      }
    }

    return Promise.reject(new ApiError(code, message, status))
  },
)

/** 把 {code, message, data} 那层壳剥掉，调用方拿到的直接是 data */
async function unwrap<T>(request: Promise<{ data: ApiResponse<T>; status: number }>): Promise<T> {
  const response = await request
  const body = response.data

  // 后端报错时 HTTP 状态码也是 4xx/5xx，走的是上面那个错误分支，到不了这儿。
  // 留着这道判断是防万一：哪天某个接口忘了设状态码，
  // 也不会把一次失败当成成功返回
  if (body.code !== 0) {
    throw new ApiError(body.code, body.message, response.status)
  }

  return body.data
}

export function get<T>(url: string, params?: Record<string, unknown>): Promise<T> {
  return unwrap<T>(http.get(url, { params }))
}

export function post<T>(url: string, body?: unknown): Promise<T> {
  return unwrap<T>(http.post(url, body))
}
