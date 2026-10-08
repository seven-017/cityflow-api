<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'

import { ApiError } from '@/api/http'
import { listUsers } from '@/api/system'
import {
  addWorkOrderRecord,
  assignWorkOrder,
  closeWorkOrder,
  completeWorkOrder,
  getWorkOrder,
  rejectWorkOrder,
  startWorkOrder,
} from '@/api/workOrders'
import { useAuthStore } from '@/stores/auth'
import { PERMISSIONS } from '@/types/auth'
import type { UserSummary } from '@/types/system'
import {
  ACTION_BUTTON_TYPES,
  ACTION_LABELS,
  ACTION_PERMISSIONS,
  DATA_SOURCE_LABELS,
  STATUS_ORIGIN_LABELS,
  WORK_ORDER_STATUS_LABELS,
  WORK_ORDER_STATUS_TAGS,
  allowedByRole,
  availableActions,
  type WorkOrderAction,
  type WorkOrderDetail,
} from '@/types/workOrder'

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()

// 路由参数进来那一刻就定死了，后面不会再变，所以不用 computed 包一层
const orderId = Number(route.params.id)

const order = ref<WorkOrderDetail | null>(null)
const loading = ref(true)
// 正在提交哪个动作。一次只可能点一个，所以一个变量就够，
// 剩下的按钮靠它来判断要不要先灰着
const acting = ref<WorkOrderAction | null>(null)

// ==================== 用户 id 换人名 ====================
//
// assigned_to_id 和流水里的 operator_id 都只是个数字，要显示成人名
// 就得去 /system/users 问一趟。那个接口要 user:manage，四个角色里只有 admin 有 ——
// 所以这儿是尽力而为：问到了就显示名字，问不到就退回去显示 #id。
// 为了一个显示字段把整页搞挂不值当
const userNames = ref<Record<number, string>>({})

async function loadUserNames() {
  try {
    const page = await listUsers()
    userNames.value = Object.fromEntries(page.items.map((u) => [u.id, u.display_name]))
  } catch {
    // 403 就 403，不是错误，顶多名字显示不出来
  }
}

function assigneeText(id: number | null): string {
  if (id === null) return '未分派'
  return userNames.value[id] ?? `#${id}`
}

function operatorText(id: number | null): string {
  if (id === null) return '—'
  return userNames.value[id] ?? `#${id}`
}

// ==================== 该摆哪几个按钮 ====================

/** 官方导入的数据后端一条都不许改。前端干脆别把按钮摆出来，点了也是白点 */
const readOnly = computed(() => order.value?.data_source !== 'SYNTHETIC_PLATFORM')

/**
 * 该摆哪几个按钮，三层过滤：
 *
 *   1. 状态机能走到哪几个状态
 *   2. 手上有没有对应的权限点
 *   3. 这个动作归不归你这个角色（工程师只能开始/完成）
 *
 * 后端还有第四层（工程师只能碰派给自己的单），前端故意不复制 ——
 * 那条要拿具体的单和当前用户去比，是数据级判断，前端提前判容易判错。
 * 万一真点出一个后端不认的，403 会在下面被接住并把话说清楚
 */
const actions = computed(() => {
  if (!order.value || readOnly.value) return []
  const roles = auth.user?.role_codes ?? []
  return availableActions(order.value.status).filter(
    (action) => auth.can(ACTION_PERMISSIONS[action]) && allowedByRole(action, roles),
  )
})

/** 加备注要的是 work_order:update，跟流转那四个同一档 */
const canAddRecord = computed(
  () => !readOnly.value && auth.can(PERMISSIONS.WORK_ORDER_UPDATE),
)

/** 一个按钮都没有的时候得说清楚为什么，别留一片空白让人纳闷 */
const noActionReason = computed(() => {
  if (!order.value || readOnly.value || actions.value.length > 0) return ''
  if (availableActions(order.value.status).length === 0) {
    return '这单已经走到头了，没有下一步'
  }
  return '接下来那几个动作都要权限，你手上没有'
})

// ==================== 加载 ====================

async function load() {
  loading.value = true
  try {
    order.value = await getWorkOrder(orderId)
  } catch (error) {
    ElMessage.error(error instanceof ApiError ? error.message : '加载失败')
  } finally {
    loading.value = false
  }
}

onMounted(() => {
  load()
  // 这趟纯粹为了把人名准备好，不等它 —— 名字晚半秒出来不影响别的
  loadUserNames()
})

// ==================== 流转动作 ====================

/**
 * 发一个流转请求，成了就把整张单换上。返回成功与否，给调用方决定弹窗关不关。
 *
 * 后端每次都会把改完之后的详情整个还回来（连带新的流水和记录），
 * 所以这儿不用再请求一次 —— 换上 order 页面上就全对了
 */
async function submit(
  action: WorkOrderAction,
  send: () => Promise<WorkOrderDetail>,
): Promise<boolean> {
  acting.value = action
  try {
    order.value = await send()
    ElMessage.success(`${ACTION_LABELS[action]}成功`)
    return true
  } catch (error) {
    // 403 是权限不够（包括"这单不是派给你的"），
    // 409 是状态对不上，或者有人抢先一步改了。后端给的 message 已经把话说全了
    ElMessage.error(error instanceof ApiError ? error.message : '操作失败')
    return false
  } finally {
    acting.value = null
  }
}

async function runAction(action: WorkOrderAction) {
  if (action === 'ASSIGN') {
    openAssign()
    return
  }
  if (action === 'REJECT') {
    openReject()
    return
  }

  // 剩下三个没有请求体，问一句就直接发
  try {
    await ElMessageBox.confirm(`确定要${ACTION_LABELS[action]}这张工单吗？`, '确认', {
      confirmButtonText: '确定',
      cancelButtonText: '取消',
    })
  } catch {
    // 点了取消。ElMessageBox 是拿 reject 报"用户没确认"的，这儿当没事发生
    return
  }

  if (action === 'START') {
    await submit(action, () => startWorkOrder(orderId))
  } else if (action === 'COMPLETE') {
    await submit(action, () => completeWorkOrder(orderId))
  } else {
    await submit(action, () => closeWorkOrder(orderId))
  }
}

// ==================== 分派弹窗 ====================

const assignVisible = ref(false)
const assignLoading = ref(false)
const assignFailed = ref(false)
const assignOptions = ref<UserSummary[]>([])
const assignTarget = ref<number | null>(null)

async function openAssign() {
  assignTarget.value = null
  assignFailed.value = false
  assignVisible.value = true
  assignLoading.value = true
  try {
    const page = await listUsers()
    // 只摆工程师。后端第三道闸门也是这么判的：存在 + 没停用 + 有 ENGINEER 角色。
    // 摆一堆管理员让人挑没意义，派过去后端也会怼回来
    assignOptions.value = page.items.filter(
      (user) => user.enabled && user.role_codes.includes('ENGINEER'),
    )
  } catch {
    // 多半是 403：这个接口要 user:manage，而 DISPATCHER 有 assign 却没这个，
    // 于是分派对他来说是半残的 —— 能点，但选不了人。
    // 这是后端两个权限点没配合上留下的缝，前端补不了，只能把话说清楚
    assignFailed.value = true
  } finally {
    assignLoading.value = false
  }
}

async function confirmAssign() {
  const target = assignTarget.value
  if (target === null) {
    ElMessage.warning('先选一个工程师')
    return
  }
  if (await submit('ASSIGN', () => assignWorkOrder(orderId, target))) {
    assignVisible.value = false
  }
}

// ==================== 驳回弹窗 ====================

const rejectVisible = ref(false)
const rejectReason = ref('')

function openReject() {
  rejectReason.value = ''
  rejectVisible.value = true
}

async function confirmReject() {
  const reason = rejectReason.value.trim()
  if (!reason) {
    ElMessage.warning('驳回得写个原因')
    return
  }
  if (await submit('REJECT', () => rejectWorkOrder(orderId, reason))) {
    rejectVisible.value = false
  }
}

// ==================== 加备注 ====================

const noteText = ref('')
const noteLoading = ref(false)

async function saveNote() {
  const content = noteText.value.trim()
  if (!content) {
    ElMessage.warning('写点什么再提交')
    return
  }

  noteLoading.value = true
  try {
    const record = await addWorkOrderRecord(orderId, content)
    // 后端只把这一条记录还回来，所以往本地列表末尾追加就够，不用把详情重拉一遍
    order.value?.processing_records.push(record)
    noteText.value = ''
    ElMessage.success('记下来了')
  } catch (error) {
    ElMessage.error(error instanceof ApiError ? error.message : '提交失败')
  } finally {
    noteLoading.value = false
  }
}

// ==================== 小工具 ====================

/** 后端给的是 ISO 串，页面上只要「哪天 几点几分」，秒和后面的都砍掉 */
function formatTime(value: string | null): string {
  if (!value) return '—'
  return value.replace('T', ' ').slice(0, 16)
}

function statusLabel(status: string): string {
  return WORK_ORDER_STATUS_LABELS[status] ?? status
}
</script>

<template>
  <div v-loading="loading" class="detail">
    <el-page-header @back="router.push({ name: 'work-orders' })">
      <template #content>
        <span class="title">工单 #{{ orderId }}</span>
        <el-tag
          v-if="order"
          :type="WORK_ORDER_STATUS_TAGS[order.status] ?? 'info'"
          class="status-tag"
        >
          {{ statusLabel(order.status) }}
        </el-tag>
      </template>
    </el-page-header>

    <template v-if="order">
      <!-- 描述 + 操作 -->
      <el-card class="block" shadow="never">
        <h2 class="desc">{{ order.description }}</h2>

        <el-alert
          v-if="readOnly"
          type="info"
          :closable="false"
          show-icon
          class="alert"
          title="官方导入的历史数据，只读"
          description="这批数据代表已经发生过的事，后端一条都不许改 —— 分派、流转、加备注全都会返 403。所以下面一个按钮都不摆。"
        />

        <div v-if="actions.length > 0 || noActionReason" class="actions">
          <el-button
            v-for="action in actions"
            :key="action"
            :type="ACTION_BUTTON_TYPES[action]"
            :loading="acting === action"
            :disabled="acting !== null && acting !== action"
            @click="runAction(action)"
          >
            {{ ACTION_LABELS[action] }}
          </el-button>
          <span v-if="noActionReason" class="hint">{{ noActionReason }}</span>
        </div>

        <el-descriptions :column="2" border class="info">
          <el-descriptions-item label="来源编号">
            {{ order.source_record_id }}
          </el-descriptions-item>
          <el-descriptions-item label="数据源">
            {{ DATA_SOURCE_LABELS[order.data_source] ?? order.data_source }}
          </el-descriptions-item>

          <el-descriptions-item label="工作类型">{{ order.work_type ?? '—' }}</el-descriptions-item>
          <el-descriptions-item label="工作分类">{{ order.work_class ?? '—' }}</el-descriptions-item>

          <el-descriptions-item label="状态来源">
            {{ STATUS_ORIGIN_LABELS[order.status_origin] ?? order.status_origin }}
          </el-descriptions-item>
          <el-descriptions-item label="原始状态">
            {{ order.source_status ?? '—' }}
          </el-descriptions-item>

          <el-descriptions-item label="优先级">{{ order.priority ?? '—' }}</el-descriptions-item>
          <el-descriptions-item label="SLA 截止">
            {{ formatTime(order.sla_deadline) }}
          </el-descriptions-item>

          <el-descriptions-item label="报修日期">
            {{ order.request_date ?? '—' }}
          </el-descriptions-item>
          <el-descriptions-item label="完成日期">
            {{ order.completion_date ?? '—' }}
          </el-descriptions-item>

          <el-descriptions-item label="指派人">
            {{ assigneeText(order.assigned_to_id) }}
          </el-descriptions-item>
          <el-descriptions-item label="创建时间">
            {{ formatTime(order.created_at) }}
          </el-descriptions-item>
        </el-descriptions>

        <p class="footnote">
          上面这些空格子不是没显示出来 —— 官方那批数据本来就大半是空的（资产关联、
          计划完成日期、优先级这些列从来没填过），平台自己录的单才有值。
        </p>
      </el-card>

      <!-- 状态流水 -->
      <el-card class="block" shadow="never">
        <template #header>状态流水</template>

        <el-empty
          v-if="order.status_history.length === 0"
          description="没有流水"
          :image-size="60"
        />

        <el-timeline v-else>
          <el-timeline-item
            v-for="item in order.status_history"
            :key="item.id"
            :timestamp="formatTime(item.created_at)"
            placement="top"
          >
            <span class="flow">
              {{ item.from_status ? statusLabel(item.from_status) : '建单' }}
              <span class="arrow">→</span>
              {{ statusLabel(item.to_status) }}
            </span>
            <span class="flow-who">{{ operatorText(item.operator_id) }}</span>
            <div v-if="item.reason" class="flow-reason">驳回原因：{{ item.reason }}</div>
          </el-timeline-item>
        </el-timeline>
      </el-card>

      <!-- 处理记录 -->
      <el-card class="block" shadow="never">
        <template #header>处理记录</template>

        <el-empty
          v-if="order.processing_records.length === 0"
          description="还没有人记过什么"
          :image-size="60"
        />

        <ul v-else class="notes">
          <li v-for="record in order.processing_records" :key="record.id" class="note">
            <div class="note-content">{{ record.content }}</div>
            <div class="note-meta">
              {{ operatorText(record.user_id) }} · {{ formatTime(record.created_at) }}
            </div>
          </li>
        </ul>

        <div v-if="canAddRecord" class="note-form">
          <el-input
            v-model="noteText"
            type="textarea"
            :rows="2"
            maxlength="2000"
            show-word-limit
            placeholder="记一句现场的情况，比如看了什么、缺什么配件"
          />
          <el-button
            type="primary"
            :loading="noteLoading"
            class="note-submit"
            @click="saveNote"
          >
            记一笔
          </el-button>
        </div>
      </el-card>
    </template>

    <!-- 分派 -->
    <el-dialog v-model="assignVisible" title="分派工单" width="440px">
      <el-alert
        v-if="assignFailed"
        type="warning"
        :closable="false"
        title="拿不到用户列表，选不了人"
        description="这个接口要 user:manage 权限。你有分派权限（work_order:assign），但没有用户管理权限 —— 后端这两个点没配合上。"
      />

      <el-select
        v-else
        v-model="assignTarget"
        :loading="assignLoading"
        placeholder="选一个工程师"
        class="assign-select"
      >
        <el-option
          v-for="user in assignOptions"
          :key="user.id"
          :label="user.display_name"
          :value="user.id"
        />
      </el-select>

      <template #footer>
        <el-button @click="assignVisible = false">取消</el-button>
        <el-button
          type="primary"
          :loading="acting === 'ASSIGN'"
          :disabled="assignFailed"
          @click="confirmAssign"
        >
          确定
        </el-button>
      </template>
    </el-dialog>

    <!-- 驳回 -->
    <el-dialog v-model="rejectVisible" title="驳回工单" width="440px">
      <p class="dialog-tip">驳回了这单就走到头了，不会再往下走。</p>
      <el-input
        v-model="rejectReason"
        type="textarea"
        :rows="3"
        maxlength="500"
        show-word-limit
        placeholder="为什么驳？三个月后翻流水的人只能看到你写的这一句"
      />

      <template #footer>
        <el-button @click="rejectVisible = false">取消</el-button>
        <el-button
          type="danger"
          :loading="acting === 'REJECT'"
          @click="confirmReject"
        >
          确定驳回
        </el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.detail {
  min-height: 200px;
}

.title {
  margin-right: 10px;
  font-size: 16px;
  font-weight: 500;
}

.status-tag {
  vertical-align: middle;
}

.block {
  margin-top: 16px;
}

.desc {
  margin: 0 0 12px;
  font-size: 18px;
  font-weight: 500;
  line-height: 1.5;
}

.alert {
  margin-bottom: 16px;
}

.actions {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 16px;
}

.hint {
  font-size: 13px;
  color: var(--el-text-color-secondary);
}

.footnote {
  margin: 12px 0 0;
  font-size: 12px;
  line-height: 1.7;
  color: var(--el-text-color-placeholder);
}

.flow {
  font-size: 14px;
}

.arrow {
  margin: 0 6px;
  color: var(--el-text-color-secondary);
}

.flow-who {
  margin-left: 10px;
  font-size: 13px;
  color: var(--el-text-color-secondary);
}

.flow-reason {
  margin-top: 4px;
  font-size: 13px;
  color: var(--el-color-danger);
}

.notes {
  margin: 0;
  padding: 0;
  list-style: none;
}

.note {
  padding: 10px 0;
  border-bottom: 1px solid var(--el-border-color-lighter);
}

.note:last-child {
  border-bottom: none;
}

.note-content {
  line-height: 1.7;
}

.note-meta {
  margin-top: 4px;
  font-size: 12px;
  color: var(--el-text-color-secondary);
}

.note-form {
  margin-top: 16px;
}

.note-submit {
  margin-top: 10px;
}

.assign-select {
  width: 100%;
}

.dialog-tip {
  margin: 0 0 12px;
  font-size: 13px;
  color: var(--el-text-color-secondary);
}
</style>
