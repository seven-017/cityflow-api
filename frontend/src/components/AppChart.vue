<script setup lang="ts">
import { BarChart, LineChart } from 'echarts/charts'
import { GridComponent, LegendComponent, TooltipComponent } from 'echarts/components'
import * as echarts from 'echarts/core'
import { CanvasRenderer } from 'echarts/renderers'
import { onBeforeUnmount, onMounted, ref, watch } from 'vue'

import type { EChartsOption } from 'echarts'

// 按需引，不 import 整个 echarts。
// 这个项目只用到柱状和折线两种图，全量引进来会白白多背几百 KB 用不上的代码。
// 跟后端那边「schema 只发用得上的字段」是一个思路，只是这边的白名单是组件
echarts.use([
  BarChart,
  LineChart,
  GridComponent,
  LegendComponent,
  TooltipComponent,
  CanvasRenderer,
])

const props = defineProps<{
  option: EChartsOption
  height?: string
}>()

const el = ref<HTMLDivElement | null>(null)
let chart: ReturnType<typeof echarts.init> | null = null

function handleResize() {
  // 窗口缩放、侧边栏收起都会改变容器宽度，不 resize 的话图还停在原来那个尺寸
  chart?.resize()
}

onMounted(() => {
  if (!el.value) return
  chart = echarts.init(el.value)
  chart.setOption(props.option)
  window.addEventListener('resize', handleResize)
})

/**
 * 数据是异步来的，option 会从「一张空图」换成「有数据的图」。
 *
 * 第二个参数传 true 是不合并、整个换掉。传 false 的话上一份 option 的残留会赖着不走 ——
 * 状态分布那六根柱子换成只有三根的图，剩下三根还在画布上站着
 */
watch(
  () => props.option,
  (next) => {
    chart?.setOption(next, true)
  },
)

onBeforeUnmount(() => {
  window.removeEventListener('resize', handleResize)
  // 不 dispose 的话来回切页面会攒下一堆实例，ECharts 会一直往控制台丢警告
  chart?.dispose()
  chart = null
})
</script>

<template>
  <div ref="el" class="app-chart" :style="{ height: height ?? '300px' }"></div>
</template>

<style scoped>
.app-chart {
  width: 100%;
}
</style>
