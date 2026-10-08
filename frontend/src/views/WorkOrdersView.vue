<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'

import { ApiError } from '@/api/http'
import { listWorkOrders } from '@/api/workOrders'
import {
  WORK_ORDER_STATUS_LABELS,
  WORK_ORDER_STATUS_TAGS,
  type WorkOrderSummary,
} from '@/types/workOrder'

const PAGE_SIZE = 20

const items = ref<WorkOrderSummary[]>([])
// null 既是"还没翻过"，也正好是第一页该传的 after_id
const nextCursor = ref<number | null>(null)
const hasMore = ref(false)

const loading = ref(false)
// 首次加载和"加载更多"要分开：首次是整表压一层遮罩，
// 后面只是在按钮上转圈。混在一起的话，点"加载更多"时整个表格会闪一下
const initialized = ref(false)

async function loadMore() {
  // 按钮自己的 loading 挡不住快速连点，加一道自己的判断
  if (loading.value) {
    return
  }

  loading.value = true
  try {
    const isFirstPage = nextCursor.value === null
    const page = await listWorkOrders(nextCursor.value ?? undefined, PAGE_SIZE)

    // 第一页是替换（重新加载的场景），后面才是往末尾追加
    items.value = isFirstPage ? page.items : [...items.value, ...page.items]
    nextCursor.value = page.meta.next_cursor
    hasMore.value = page.meta.has_more
  } catch (error) {
    ElMessage.error(error instanceof ApiError ? error.message : '加载失败')
  } finally {
    loading.value = false
    initialized.value = true
  }
}

onMounted(loadMore)
</script>

<template>
  <el-card>
    <template #header>
      <div class="head">
        <span>工单列表</span>
        <!-- 只能报"已加载多少条"，报不出总数：后端不返回 total，
             而且那个数字要 300 毫秒才换得来 -->
        <span v-if="initialized" class="loaded">已加载 {{ items.length }} 条</span>
      </div>
    </template>

    <el-table v-loading="!initialized" :data="items" stripe>
      <el-table-column prop="id" label="ID" width="90" />

      <el-table-column prop="source_record_id" label="来源编号" width="130" show-overflow-tooltip />

      <el-table-column prop="description" label="描述" min-width="260" show-overflow-tooltip />

      <el-table-column label="类型" width="90">
        <!-- 历史数据里这一列有些是空的，空就显示一个短横，
             别让它变成一块莫名其妙的空白 -->
        <template #default="{ row }">{{ row.work_type ?? '—' }}</template>
      </el-table-column>

      <el-table-column label="状态" width="110">
        <template #default="{ row }">
          <el-tag :type="WORK_ORDER_STATUS_TAGS[row.status] ?? 'info'" size="small">
            {{ WORK_ORDER_STATUS_LABELS[row.status] ?? row.status }}
          </el-tag>
        </template>
      </el-table-column>

      <el-table-column label="报修日期" width="120">
        <template #default="{ row }">{{ row.request_date ?? '—' }}</template>
      </el-table-column>

      <el-table-column label="完成日期" width="120">
        <template #default="{ row }">{{ row.completion_date ?? '—' }}</template>
      </el-table-column>
    </el-table>

    <div class="footer">
      <el-button v-if="hasMore" :loading="loading" @click="loadMore">加载更多</el-button>
      <span v-else-if="initialized" class="end">没有更多了</span>
    </div>
  </el-card>
</template>

<style scoped>
.head {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
}

.loaded {
  font-size: 13px;
  color: var(--el-text-color-secondary);
}

.footer {
  margin-top: 16px;
  text-align: center;
}

.end {
  font-size: 13px;
  color: var(--el-text-color-placeholder);
}
</style>
