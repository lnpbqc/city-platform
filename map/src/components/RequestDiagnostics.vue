<script setup lang="ts">
import { ref } from 'vue'
import type { ApiError } from '../api'
defineProps<{ error: ApiError | null }>()
const open = ref(false), message = ref('')
async function copy(error: ApiError) {
  try { await navigator.clipboard.writeText(JSON.stringify({ code: error.code, message: error.description, trace_id: error.traceId }, null, 2)); message.value = '诊断已复制' }
  catch { message.value = '可选中下方诊断文本复制' }
}
</script>
<template>
  <div v-if="error" class="request-diagnostics">
    <button class="diagnostic-trigger" :aria-expanded="open" aria-label="请求诊断" @click="open = !open">请求诊断</button>
    <section v-if="open" class="diagnostic-panel panel" aria-label="最近请求诊断"><strong>{{ error.code }}</strong><p>{{ error.description }}</p><p class="trace">trace_id：{{ error.traceId || '响应未提供' }}</p><button class="text-button" @click="copy(error)">复制诊断</button><p v-if="message" role="status">{{ message }}</p><textarea readonly aria-label="诊断文本" :value="JSON.stringify({code:error.code,message:error.description,trace_id:error.traceId},null,2)" @focus="($event.target as HTMLTextAreaElement).select()" /></section>
  </div>
</template>
<style scoped>
.diagnostic-trigger { color: #a56143; font-size: 11px; white-space: nowrap; }
.diagnostic-panel { position: absolute; right: 24px; top: 74px; width: 340px; max-width: calc(100vw - 32px); padding: 18px; font-size: 12px; overflow-wrap: anywhere; }
.diagnostic-panel p { line-height: 1.6; color: #6b7d91; }.trace, textarea { font-size: 10px; } textarea { width: 100%; height: 100px; margin-top: 12px; border: 1px solid var(--line); padding: 8px; border-radius: 5px; resize: vertical; }
</style>
