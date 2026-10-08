<script setup lang="ts">
import { computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import { useAuthStore } from '@/stores/auth'
import { ROLE_LABELS } from '@/types/auth'

const auth = useAuthStore()
const route = useRoute()
const router = useRouter()

// 侧边栏菜单。先只有首页，后面每做一个模块往这儿加一条
const menus = [{ path: '/', label: '首页' }]

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
        <el-menu-item v-for="menu in menus" :key="menu.path" :index="menu.path">
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
