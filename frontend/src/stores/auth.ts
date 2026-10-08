import { defineStore } from 'pinia'
import { computed, ref } from 'vue'

import { fetchCurrentUser, login as loginRequest } from '@/api/auth'
import type { UserIdentity } from '@/types/auth'

const TOKEN_KEY = 'cityflow_token'

export const useAuthStore = defineStore('auth', () => {
  // 从 localStorage 起手，是为了刷新页面不用重新登录。
  // 代价也说清楚：token 放在浏览器里，页面上一旦有 XSS 就能被偷走。
  // 更稳的做法是 httpOnly cookie，但那要后端配合改，先记着这条
  const token = ref<string | null>(localStorage.getItem(TOKEN_KEY))
  const user = ref<UserIdentity | null>(null)

  const isLoggedIn = computed(() => token.value !== null)

  /** 查有没有某个权限码。界面上按钮灰不灰、菜单显不显示，都问它 */
  function can(permission: string): boolean {
    return user.value?.permissions.includes(permission) ?? false
  }

  async function login(username: string, password: string): Promise<void> {
    const result = await loginRequest(username, password)
    token.value = result.access_token
    localStorage.setItem(TOKEN_KEY, result.access_token)
    // 登录接口顺手把 user 也带回来了，直接存下，省一次 /auth/me
    user.value = result.user
  }

  /**
   * 刷新页面后 store 是空的，但 localStorage 里的 token 还在。
   * 拿它去问一次"我是谁"，问得到就说明这个 token 还有效。
   *
   * 失败不能往外抛：路由守卫里 await 它，抛出去会中断导航；
   * 而且 401 在拦截器里已经处理过了（清状态 + 跳登录页）
   */
  async function restore(): Promise<void> {
    if (!token.value || user.value) {
      return
    }
    try {
      user.value = await fetchCurrentUser()
    } catch {
      logout()
    }
  }

  function logout(): void {
    token.value = null
    user.value = null
    localStorage.removeItem(TOKEN_KEY)
  }

  return { token, user, isLoggedIn, can, login, restore, logout }
})
