<script setup lang="ts">
import { useAuthStore } from '@/stores/auth'

const auth = useAuthStore()
</script>

<template>
  <el-card>
    <template #header>当前登录状态</template>

    <el-descriptions :column="2" border>
      <el-descriptions-item label="用户名">{{ auth.user?.username }}</el-descriptions-item>
      <el-descriptions-item label="姓名">{{ auth.user?.display_name }}</el-descriptions-item>
      <el-descriptions-item label="角色">
        {{ auth.user?.role_codes.join('、') }}
      </el-descriptions-item>
      <el-descriptions-item label="最近登录">
        {{ auth.user?.last_login_at }}
      </el-descriptions-item>
    </el-descriptions>

    <p class="hint">后端给的权限点。界面上按钮灰不灰、菜单显不显示，判断依据就是它。</p>
    <el-tag v-for="code in auth.user?.permissions" :key="code" class="perm" type="info">
      {{ code }}
    </el-tag>
  </el-card>
</template>

<style scoped>
.hint {
  margin: 20px 0 10px;
  font-size: 13px;
  color: var(--el-text-color-secondary);
}

.perm {
  margin: 0 6px 6px 0;
}
</style>
