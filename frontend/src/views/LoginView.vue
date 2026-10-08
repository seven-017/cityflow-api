<script setup lang="ts">
import { reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'

import { ApiError } from '@/api/http'
import { useAuthStore } from '@/stores/auth'

const auth = useAuthStore()
const route = useRoute()
const router = useRouter()

const form = reactive({ username: '', password: '' })
const loading = ref(false)

async function handleSubmit() {
  if (!form.username || !form.password) {
    ElMessage.warning('用户名和密码都要填')
    return
  }

  loading.value = true
  try {
    await auth.login(form.username, form.password)

    // 从哪被拦下来的就送回哪，没有就进首页
    const redirect = route.query.redirect
    await router.replace(typeof redirect === 'string' ? redirect : '/')
  } catch (error) {
    // 后端把失败原因放在 message 里，照原样显示就行，别自己另编一套话术
    ElMessage.error(error instanceof ApiError ? error.message : '登录失败，请稍后再试')
  } finally {
    // 放在 finally 里，成功失败都要把按钮恢复可点，
    // 否则一次失败之后按钮就永远转圈了
    loading.value = false
  }
}
</script>

<template>
  <div class="page">
    <el-card class="card">
      <h1 class="title">CityFlow</h1>
      <p class="subtitle">城市资产与维修工单管理平台</p>

      <el-form label-position="top">
        <el-form-item label="用户名">
          <el-input
            v-model="form.username"
            placeholder="请输入用户名"
            autocomplete="username"
            @keyup.enter="handleSubmit"
          />
        </el-form-item>

        <el-form-item label="密码">
          <el-input
            v-model="form.password"
            type="password"
            placeholder="请输入密码"
            autocomplete="current-password"
            show-password
            @keyup.enter="handleSubmit"
          />
        </el-form-item>

        <el-button type="primary" class="submit" :loading="loading" @click="handleSubmit">
          登录
        </el-button>
      </el-form>

      <p class="tip">本地开发的四个账号见 backend/README.md</p>
    </el-card>
  </div>
</template>

<style scoped>
.page {
  height: 100vh;
  display: flex;
  align-items: center;
  justify-content: center;
  background: var(--el-fill-color-light);
}

.card {
  width: 360px;
}

.title {
  margin: 0;
  font-size: 20px;
  font-weight: 500;
}

.subtitle {
  margin: 6px 0 24px;
  font-size: 13px;
  color: var(--el-text-color-secondary);
}

.submit {
  width: 100%;
}

.tip {
  margin: 16px 0 0;
  font-size: 12px;
  color: var(--el-text-color-placeholder);
  text-align: center;
}
</style>
