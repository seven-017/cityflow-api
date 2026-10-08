import { createRouter, createWebHistory } from 'vue-router'

import { useAuthStore } from '@/stores/auth'

// 给 meta 补一个 public 字段的类型声明。
// 没有它的话 to.meta.public 会被 TS 当成 unknown，写起来到处要断言
declare module 'vue-router' {
  interface RouteMeta {
    public?: boolean
  }
}

const router = createRouter({
  history: createWebHistory(),
  routes: [
    {
      path: '/login',
      name: 'login',
      component: () => import('@/views/LoginView.vue'),
      meta: { public: true },
    },
    {
      path: '/',
      component: () => import('@/layouts/AppLayout.vue'),
      children: [
        {
          path: '',
          name: 'home',
          component: () => import('@/views/HomeView.vue'),
        },
      ],
    },
    // 地址输错不要给一片空白，送回首页
    { path: '/:pathMatch(.*)*', redirect: '/' },
  ],
})

router.beforeEach(async (to) => {
  const auth = useAuthStore()

  // 只有标了 public 的页面能免登录进。反过来写（标 private）的话，
  // 以后加新页面忘了登记，就会变成一个任何人都能进的页面
  if (to.meta.public) {
    return true
  }

  if (!auth.isLoggedIn) {
    // 记住本来想去哪，登录完直接送过去，而不是一律丢回首页
    return { name: 'login', query: { redirect: to.fullPath } }
  }

  // 刷新页面时 token 还在，但 store 里的用户信息没了，补一次
  await auth.restore()

  // restore 发现 token 已经失效时会把自己清掉，所以要再判一次，
  // 否则会带着一个空的 user 进到页面里
  if (!auth.isLoggedIn) {
    return { name: 'login', query: { redirect: to.fullPath } }
  }

  return true
})

export default router
