<script setup lang="ts">
import { computed, ref } from 'vue'
import type { RenderDescriptor } from '../types'
import { retryRender } from '../api'

const props = defineProps<{ render?: RenderDescriptor | null; assetId?: string | null; version?: string | null; category?: string }>()
const emit = defineEmits<{ updated: [render: RenderDescriptor] }>()
const busy = ref(false)
const error = ref('')
const phase = computed(() => {
  const stages: Record<string, string> = { download: '正在接收数据', 'waiting-source': '等待数据传输',
    preprocess: '正在精简显示数据', tiling: '正在生成显示数据', audit: '正在验证显示数据',
    packaging: '正在整理显示数据' }
  const states = { queued: '等待处理显示数据', running: '正在处理显示数据', succeeded: '显示数据已就绪',
    failed: '显示数据处理失败，地图仍可浏览', cancelled: '已取消处理，地图仍可浏览' }
  return props.render ? stages[props.render.stage ?? ''] ?? states[props.render.status] : ''
})
async function retry() {
  if (!props.assetId || !props.version || busy.value) return
  busy.value = true; error.value = ''
  const category = props.category ?? (props.render?.profile === 'roads' ? '道路' : props.render?.profile === 'poi' ? 'POI' : '')
  try { emit('updated', await retryRender(props.assetId, props.version, category)) }
  catch (cause) { error.value = cause instanceof Error ? cause.message : '重试失败' }
  finally { busy.value = false }
}
</script>

<template>
  <div v-if="render" class="render-state" aria-live="polite">
    <span>{{ phase }}</span>
    <button v-if="render.status === 'failed' || render.status === 'cancelled'" :disabled="busy" @click="retry">{{ busy ? '正在重试' : '重试处理' }}</button>
    <details v-if="render.error"><summary>查看处理记录</summary><p>{{ render.error }}</p></details>
    <p v-if="render.source_state === 'expired'">原文件已到期清理，可导出 GeoJSON</p>
    <p v-else-if="render.source_expires_at">原文件保留至 {{ new Date(render.source_expires_at).toLocaleString('zh-CN', { timeZone: 'Asia/Shanghai' }) }}（北京时间）</p>
    <p v-if="error" role="alert">{{ error }}</p>
  </div>
</template>

<style scoped>
.render-state { margin: 6px 0; font-size: 11px; color: #64748b; overflow-wrap: anywhere; }
.render-state p { margin: 3px 0; }
.render-state button { margin-left: 8px; color: #2563eb; }
</style>
