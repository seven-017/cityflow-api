<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'

import { getDashboardOverview } from '@/api/dashboard'
import { ApiError } from '@/api/http'
import AppChart from '@/components/AppChart.vue'
import { WORK_ORDER_STATUS_LABELS, WORK_ORDER_STATUS_TAGS } from '@/types/workOrder'
import type { DashboardOverview } from '@/types/dashboard'
import type { EChartsOption } from 'echarts'

const data = ref<DashboardOverview | null>(null)
const loading = ref(true)
const errorText = ref('')
// 这次请求花了几毫秒。摆出来不是为了好看 ——
// 冷启动十几秒、之后两百多毫秒，这个对比就是这个接口为什么要缓存
const elapsedMs = ref(0)

async function load() {
  loading.value = true
  errorText.value = ''
  const startedAt = performance.now()
  try {
    data.value = await getDashboardOverview()
  } catch (error) {
    errorText.value = error instanceof ApiError ? error.message : '加载失败'
  } finally {
    elapsedMs.value = Math.round(performance.now() - startedAt)
    loading.value = false
  }
}

onMounted(load)

/** 冷启动和走缓存差 50 倍，得让人知道这次是哪种 */
const coldStart = computed(() => elapsedMs.value > 1000)

const elapsedText = computed(() => (elapsedMs.value / 1000).toFixed(2) + ' 秒')

// ==================== 数字怎么显示 ====================

/** 给大数字加千分位 */
function group(value: number): string {
  return value.toLocaleString('zh-CN')
}

/**
 * 后端那些 Decimal 字段是字符串过来的（防掉精度）。
 * 显示的时候转成数字只为加个千分位 —— 这个量级（最大四亿多）远在 double 的安全范围内
 */
function decimal(value: string | null): string {
  if (value === null) return '—'
  return Number(value).toLocaleString('zh-CN', {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })
}

/**
 * 柱子上那种短标签，比如 206.6万。
 * 状态分布那几个数差着八十倍，写全了柱子就剩一根高的，别的全是数字挤在一块
 */
function shortNumber(value: number): string {
  if (value >= 10000) return (value / 10000).toFixed(1) + '万'
  return String(value)
}

/** '2025-10' 横轴上写成 '25/10'。十三个点，写全了挤成一团 */
function shortMonth(month: string): string {
  return month.slice(2).replace('-', '/')
}

// ==================== 指标卡片 ====================

interface MetricCard {
  label: string
  value: string
  hint?: string
}

const metricCards = computed<MetricCard[]>(() => {
  const m = data.value?.metrics
  if (!m) return []
  return [
    { label: '资产总数', value: group(m.asset_count) },
    { label: '工单总数', value: group(m.work_order_count) },
    {
      label: '未完结工单',
      value: group(m.unfinished_work_order_count),
      hint: '待处理 / 已分派 / 处理中',
    },
    {
      label: '已完成工单',
      value: group(m.finished_work_order_count),
      hint: '已完成 / 已关闭',
    },
    {
      label: '已退回工单',
      value: group(m.rejected_work_order_count),
      hint: '走到岔路上停住了',
    },
    { label: '工时记录', value: group(m.labor_record_count) },
    { label: '工时合计', value: decimal(m.labor_total_hours), hint: '小时' },
    { label: '工时成本', value: decimal(m.labor_total_cost) },
    { label: '交易单数', value: group(m.transaction_count) },
    {
      label: '交易明细',
      value: group(m.transaction_detail_count),
      hint: '一张单平均三行多',
    },
  ]
})

// ==================== 九张图 ====================

// 跟 Element Plus 的主色对齐，不然图和界面看着像两家人做的
const BAR_COLOR = '#409eff'
const LINE_COLOR = '#409eff'
const LINE_COLOR_2 = '#e6a23c'

/** 柱状图/折线图都要的那几样公共设置，写一次省得抄九遍 */
const COMMON_GRID = { left: 8, right: 20, top: 24, bottom: 8, containLabel: true }

const statusOption = computed<EChartsOption>(() => {
  const rows = data.value?.charts.status_distribution ?? []
  return {
    tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' } },
    grid: COMMON_GRID,
    xAxis: {
      type: 'category',
      data: rows.map((row) => WORK_ORDER_STATUS_LABELS[row.status] ?? row.status),
    },
    yAxis: { type: 'value' },
    series: [
      {
        type: 'bar',
        barMaxWidth: 48,
        itemStyle: { color: BAR_COLOR },
        // 每个柱子自己带着标签文本，这样就不用写 formatter 回调了
        data: rows.map((row) => ({
          value: row.work_order_count,
          label: { formatter: shortNumber(row.work_order_count) },
        })),
        label: { show: true, position: 'top' },
      },
    ],
  }
})

const workTypeOption = computed<EChartsOption>(() => {
  // 逆序：类目轴是从下往上画的，不翻一下最大的 JOB 会跑到最底下去
  const rows = [...(data.value?.charts.work_type_distribution ?? [])].reverse()
  return {
    tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' } },
    grid: { ...COMMON_GRID, right: 64 },
    xAxis: { type: 'value', axisLabel: { formatter: shortNumber } },
    yAxis: {
      type: 'category',
      data: rows.map((row) => row.work_type ?? '（未填）'),
    },
    series: [
      {
        type: 'bar',
        barMaxWidth: 24,
        itemStyle: { color: BAR_COLOR },
        data: rows.map((row) => ({
          value: row.work_order_count,
          label: { formatter: shortNumber(row.work_order_count) },
        })),
        label: { show: true, position: 'right' },
      },
    ],
  }
})

const assetTypeOption = computed<EChartsOption>(() => {
  const rows = data.value?.charts.asset_type_distribution ?? []
  return {
    tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' } },
    grid: COMMON_GRID,
    xAxis: {
      type: 'category',
      data: rows.map((row) => row.asset_type ?? '（未填）'),
    },
    yAxis: { type: 'value', axisLabel: { formatter: shortNumber } },
    series: [
      {
        type: 'bar',
        barMaxWidth: 32,
        itemStyle: { color: BAR_COLOR },
        data: rows.map((row) => ({
          value: row.asset_count,
          label: { formatter: shortNumber(row.asset_count) },
        })),
        label: { show: true, position: 'top' },
      },
    ],
  }
})

const highMaintenanceOption = computed<EChartsOption>(() => {
  const rows = [...(data.value?.charts.high_maintenance_assets ?? [])].reverse()
  return {
    tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' } },
    grid: { ...COMMON_GRID, right: 64 },
    xAxis: { type: 'value', axisLabel: { formatter: shortNumber } },
    yAxis: {
      type: 'category',
      data: rows.map((row) => row.description),
      // 描述实测最长八十来个字符，全写出来会把图挤没，截断交给 tooltip 补
      axisLabel: { width: 150, overflow: 'truncate' },
    },
    series: [
      {
        type: 'bar',
        barMaxWidth: 20,
        itemStyle: { color: BAR_COLOR },
        data: rows.map((row) => ({
          value: row.work_order_count,
          label: { formatter: String(row.work_order_count) },
        })),
        label: { show: true, position: 'right' },
      },
    ],
  }
})

/** 三个趋势图的壳子长得一样，只有 y 轴和序列不同，所以把重复那段抽出来 */
function trendBase(months: string[]) {
  return {
    tooltip: { trigger: 'axis' as const },
    grid: { ...COMMON_GRID, top: 36 },
    xAxis: {
      type: 'category' as const,
      boundaryGap: false,
      data: months.map(shortMonth),
    },
  }
}

const workOrderTrendOption = computed<EChartsOption>(() => {
  // 末尾那两个月会明显往下掉，不是数据坏了：横轴上最后那格是「当月」，
  // 只统计到当天为止，前面十几个点都是过完了的整月。
  // 这是数据的样貌，前端照原样画，不做补全也不裁掉
  const rows = data.value?.charts.work_order_trend ?? []
  return {
    ...trendBase(rows.map((row) => row.month)),
    yAxis: { type: 'value', axisLabel: { formatter: shortNumber } },
    series: [
      {
        name: '工单数',
        type: 'line',
        smooth: true,
        itemStyle: { color: LINE_COLOR },
        areaStyle: { opacity: 0.12 },
        data: rows.map((row) => row.work_order_count),
      },
    ],
  }
})

const transactionTrendOption = computed<EChartsOption>(() => {
  const rows = data.value?.charts.transaction_trend ?? []
  return {
    ...trendBase(rows.map((row) => row.month)),
    yAxis: { type: 'value', axisLabel: { formatter: shortNumber } },
    series: [
      {
        name: '交易单数',
        type: 'line',
        smooth: true,
        itemStyle: { color: LINE_COLOR },
        areaStyle: { opacity: 0.12 },
        data: rows.map((row) => row.transaction_count),
      },
    ],
  }
})

const laborTrendOption = computed<EChartsOption>(() => {
  const rows = data.value?.charts.labor_trend ?? []
  return {
    ...trendBase(rows.map((row) => row.month)),
    legend: { data: ['工时合计', '成本合计'], top: 0 },
    // 两个轴：工时两三万，成本一百多万，搁一个轴上工时那条会贴死在底部
    yAxis: [
      { type: 'value', name: '小时', axisLabel: { formatter: shortNumber } },
      { type: 'value', name: '成本', axisLabel: { formatter: shortNumber } },
    ],
    series: [
      {
        name: '工时合计',
        type: 'line',
        smooth: true,
        yAxisIndex: 0,
        itemStyle: { color: LINE_COLOR },
        data: rows.map((row) => (row.total_hours === null ? null : Number(row.total_hours))),
      },
      {
        name: '成本合计',
        type: 'line',
        smooth: true,
        yAxisIndex: 1,
        itemStyle: { color: LINE_COLOR_2 },
        // 画成虚线。成本跟工时基本成正比，两个轴的刻度又会被自动对齐，
        // 于是两条实线严丝合缝叠在一起，看着像只有一条线。
        // 虚线至少让人数得出这是两根
        lineStyle: { type: 'dashed' },
        data: rows.map((row) => (row.total_cost === null ? null : Number(row.total_cost))),
      },
    ],
  }
})
</script>

<template>
  <div
    v-loading="loading"
    class="dashboard"
    :element-loading-text="
      loading
        ? '头一回要等十几秒 —— 后端在跑五个聚合，算完会缓存五分钟，之后就是毫秒级'
        : ''
    "
  >
    <div v-if="errorText" class="error">
      <el-alert type="error" :closable="false" :title="errorText" />
      <el-button class="retry" @click="load">重试</el-button>
    </div>

    <template v-if="data">
      <!-- 指标 -->
      <div class="metrics">
        <div v-for="card in metricCards" :key="card.label" class="metric">
          <div class="metric-label">{{ card.label }}</div>
          <div class="metric-value">{{ card.value }}</div>
          <div v-if="card.hint" class="metric-hint">{{ card.hint }}</div>
        </div>
      </div>

      <!-- 这次请求花了多久 -->
      <div class="timing">
        <span>这次加载花了 {{ elapsedText }}</span>
        <span v-if="coldStart" class="timing-note">
          （后端是现算的：五个聚合跑一遍十几秒。五分钟内再进这个页面就是毫秒级）
        </span>
        <span v-else class="timing-note">（命中了后端缓存，数据库一下都没碰）</span>
      </div>

      <!-- 平均处理周期 -->
      <el-card class="block" shadow="never">
        <div class="resolution">
          <div class="resolution-value">
            {{ decimal(data.charts.resolution_summary.average_days) }}
            <span class="resolution-unit">天</span>
          </div>
          <div class="resolution-desc">
            平均处理周期 —— 取最近
            {{ data.charts.resolution_summary.window_months }} 个月，
            样本 {{ group(data.charts.resolution_summary.sample_count) }} 张单。
            <br />
            <span class="resolution-warn">
              这个天数必须连着窗口一起看：全历史算出来是 50 天出头，
              近一年只有二十来天。光甩一个数字出来是会误导人的。
            </span>
          </div>
        </div>
      </el-card>

      <!-- 图 -->
      <div class="charts">
        <el-card class="chart-card" shadow="never">
          <template #header>工单状态分布</template>
          <AppChart :option="statusOption" height="280px" />
        </el-card>

        <el-card class="chart-card" shadow="never">
          <template #header>工单类型分布</template>
          <AppChart :option="workTypeOption" height="280px" />
        </el-card>

        <el-card class="chart-card" shadow="never">
          <template #header>资产类型分布</template>
          <AppChart :option="assetTypeOption" height="280px" />
        </el-card>

        <el-card class="chart-card" shadow="never">
          <template #header>高维护资产榜</template>
          <AppChart :option="highMaintenanceOption" height="280px" />
        </el-card>

        <el-card class="chart-card" shadow="never">
          <template #header>工单趋势（按月）</template>
          <AppChart :option="workOrderTrendOption" height="280px" />
        </el-card>

        <el-card class="chart-card" shadow="never">
          <template #header>交易趋势（按月）</template>
          <AppChart :option="transactionTrendOption" height="280px" />
        </el-card>

        <el-card class="chart-card wide" shadow="never">
          <template #header>工时趋势（按月）</template>
          <AppChart :option="laborTrendOption" height="280px" />
        </el-card>
      </div>

      <!-- 最近工单 -->
      <el-card class="block" shadow="never">
        <template #header>最近工单</template>
        <el-table :data="data.charts.recent_work_orders" stripe>
          <el-table-column prop="id" label="ID" width="100" />
          <el-table-column prop="description" label="描述" min-width="260" show-overflow-tooltip />
          <el-table-column label="类型" width="90">
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
      </el-card>
    </template>
  </div>
</template>

<style scoped>
.dashboard {
  min-height: 300px;
}

.metrics {
  display: grid;
  /* 240px 不是随手定的：宽屏下正好一行五个，十张卡整整齐齐摆两行。
     写 180 会挤成七个一行、第二行剩三个，看着像没排完 */
  grid-template-columns: repeat(auto-fill, minmax(240px, 1fr));
  gap: 12px;
}

.metric {
  padding: 14px 16px;
  border: 1px solid var(--el-border-color-light);
  border-radius: 6px;
  background: var(--el-bg-color);
}

.metric-label {
  font-size: 13px;
  color: var(--el-text-color-secondary);
}

.metric-value {
  margin-top: 6px;
  font-size: 22px;
  font-weight: 500;
  line-height: 1.2;
}

.metric-hint {
  margin-top: 4px;
  font-size: 12px;
  color: var(--el-text-color-placeholder);
}

.timing {
  margin-top: 12px;
  font-size: 12px;
  color: var(--el-text-color-secondary);
}

.timing-note {
  margin-left: 4px;
  color: var(--el-text-color-placeholder);
}

.block {
  margin-top: 16px;
}

.charts {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 16px;
  margin-top: 16px;
}

/* 工时那张有两条线两个轴，横着铺满看着舒服点 */
.chart-card.wide {
  grid-column: 1 / -1;
}

.chart-card {
  margin: 0;
}

.error {
  display: flex;
  align-items: center;
  gap: 12px;
}

.retry {
  flex: none;
}

.resolution {
  display: flex;
  align-items: center;
  gap: 24px;
}

.resolution-value {
  flex: none;
  font-size: 40px;
  font-weight: 500;
  line-height: 1;
}

.resolution-unit {
  font-size: 16px;
  color: var(--el-text-color-secondary);
}

.resolution-desc {
  font-size: 13px;
  line-height: 1.8;
  color: var(--el-text-color-secondary);
}

.resolution-warn {
  color: var(--el-text-color-placeholder);
}
</style>
