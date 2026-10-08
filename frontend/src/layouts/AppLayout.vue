<script setup lang="ts">
import { computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import { useAuthStore } from '@/stores/auth'
import { PERMISSIONS, ROLE_LABELS } from '@/types/auth'

const auth = useAuthStore()
const route = useRoute()
const router = useRouter()

interface MenuItem {
  path: string
  label: string
  /** 不写就是谁都能看（比如首页） */
  permission?: string
}

const menus: MenuItem[] = [
  { path: '/', label: '首页' },
  // 四个角色都有 dashboard:read，所以这一项谁登录都看得见
  { path: '/dashboard', label: '数据看板', permission: PERMISSIONS.DASHBOARD_READ },
  { path: '/work-orders', label: '工单', permission: PERMISSIONS.WORK_ORDER_READ },
]

// 按"有没有这个权限点"过滤，而不是按角色名判断。
// 角色是固定的四个，权限是活的 —— 哪天给某个角色补一个权限，
// 这儿的代码一行都不用改，菜单自己就冒出来了
//
// 说句老实话：眼下 admin / dispatcher / engineer / viewer 四个角色
// 全都有 work_order:read，所以这一层过滤现在看不出任何差别。
// 真正能看出效果的是下一步的按钮 —— viewer 没有 work_order:update，
// 详情页上改状态那个按钮就不该发给他
const visibleMenus = computed(() =>
  menus.filter((item) => !item.permission || auth.can(item.permission)),
)

const roleText = computed(() =>
  (auth.user?.role_codes ?? []).map((code) => ROLE_LABELS[code] ?? code).join(' / '),
)

function handleLogout() {
  auth.logout()
  router.push({ name: 'login' })
}
</script>

<template>
  <el-container class="layout">
    <el-aside width="200px" class="aside">
      <div class="brand">CityFlow</div>
      <el-menu :default-active="route.path" router>
        <el-menu-item v-for="menu in visibleMenus" :key="menu.path" :index="menu.path">
          {{ menu.label }}
        </el-menu-item>
      </el-menu>
    </el-aside>

    <el-container>
      <el-header class="header">
        <span class="who">
          {{ auth.user?.display_name }}
          <span v-if="roleText" class="role">{{ roleText }}</span>
        </span>
        <el-button link type="primary" @click="handleLogout">退出</el-button>
      </el-header>

      <el-main>
        <router-view />
      </el-main>
    </el-container>
  </el-container>
</template>

<style scoped>
.layout {
  height: 100vh;
}

.aside {
  border-right: 1px solid var(--el-border-color-light);
}

.brand {
  height: 60px;
  display: flex;
  align-items: center;
  padding: 0 20px;
  font-size: 16px;
  font-weight: 500;
}

.header {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 12px;
  border-bottom: 1px solid var(--el-border-color-light);
}

.who {
  font-size: 13px;
}

.role {
  margin-left: 6px;
  color: var(--el-text-color-secondary);
}
</style>
