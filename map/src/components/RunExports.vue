<script setup lang="ts">
import { onBeforeUnmount, ref } from 'vue'
import { Download, LoaderCircle } from '@lucide/vue'
import { downloadRun } from '../api'

const props = defineProps<{ identity: string }>()
const downloading = ref('')
const error = ref('')
const abort = new AbortController()
onBeforeUnmount(() => abort.abort())
async function download(format: 'json' | 'geojson') {
  if (downloading.value) return
  downloading.value = format
  error.value = ''
  try {
    const identity = props.identity
    const blob = await downloadRun(identity, format, abort.signal)
    if (abort.signal.aborted) return
    const url = URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = url
    link.download = `run-${identity}.${format}`
    document.body.appendChild(link)
    link.click()
    link.remove()
    setTimeout(() => URL.revokeObjectURL(url), 0)
  } catch (cause) { error.value = cause instanceof Error ? cause.message : '结果下载失败' }
  finally { downloading.value = '' }
}
</script>

<template>
  <div class="run-exports">
    <button v-for="format in ['json', 'geojson'] as const" :key="format" :aria-label="`下载结果${format.toUpperCase()}`" :disabled="!!downloading" @click="download(format)"><LoaderCircle v-if="downloading === format" :size="12" class="spin" /><Download v-else :size="12" />{{ format.toUpperCase() }}</button>
    <span v-if="error" role="alert">{{ error }}</span>
  </div>
</template>

<style scoped>
.run-exports { display: flex; align-items: center; gap: 13px; }
button { display: flex; align-items: center; gap: 5px; color: var(--blue); font-size: 10px; }
button:disabled { opacity: .5; cursor: default; }
span { color: #b94e46; font-size: 11px; overflow-wrap: anywhere; }
</style>
