<script setup lang="ts">
import { computed, ref, useId } from 'vue'
import { Play, Pause, SkipBack, SkipForward, RotateCcw, RefreshCw, ChevronDown, ChevronUp } from '@lucide/vue'
import type { TimeResolution } from '../temporalTypes'
import { localTime, timeLabel } from '../temporal'

const props = defineProps<{
  time: string; resolution: TimeResolution; rate: number; playing: boolean; maximum: number; position: number
  times: string[]; loading: boolean; metadataLoading: boolean; allMissing: boolean
  counts: { id: string; name: string; total: number; missing: number }[]; errors: Record<string, string>
  label?: string
}>()
const emit = defineEmits<{ seek: [value: number]; step: [direction: number]; select: [time: string]; play: []; pause: []; refresh: []
  'update:resolution': [value: TimeResolution]; 'update:rate': [value: number] }>()
const expanded = ref(false)
const detailsId = useId()
const inputTime = computed(() => props.time ? timeLabel(props.time).replace(' ', 'T') : '')
const missingCount = computed(() => props.counts.reduce((sum, row) => sum + row.missing, 0))
const errorCount = computed(() => Object.keys(props.errors).length)
const statusText = computed(() => {
  if (errorCount.value) return `${errorCount.value} 个图层加载失败，展开查看`
  if (props.metadataLoading) return '正在读取可用时次…'
  if (props.loading) return '正在读取当前专题值…'
  if (props.allMissing) return '该时次缺测 / 未覆盖'
  if (missingCount.value) return `${missingCount.value} 个对象缺测`
  return ''
})
function select(event: Event) { const value = localTime((event.target as HTMLInputElement).value); if (value) emit('select', value) }
</script>

<template>
  <section class="time-axis panel" :aria-label="label ?? '专题时间轴'">
    <div class="time-bar">
      <div class="time-current"><span>{{ label ?? '专题时间' }}</span><output aria-label="当前专题时间">{{ time ? timeLabel(time, resolution).slice(0, resolution === 'day' ? 10 : 16) : '暂无时次' }}</output><small>北京时间 · {{ resolution === 'day' ? '日均' : '小时' }}</small></div>
      <div class="time-transport">
        <button aria-label="上一个专题时次" :disabled="!times.length || position <= 0" @click="emit('step', -1)"><SkipBack :size="15" /></button>
        <button :disabled="!maximum" :aria-label="playing ? '暂停时间轴' : '播放时间轴'" @click="playing ? emit('pause') : emit('play')"><Pause v-if="playing" :size="16" /><Play v-else :size="16" /></button>
        <button aria-label="下一个专题时次" :disabled="!times.length || position >= maximum" @click="emit('step', 1)"><SkipForward :size="15" /></button>
      </div>
      <input class="time-progress" type="range" min="0" :max="maximum || 1" step="1" :value="position" :disabled="!times.length" aria-label="专题时间进度" @input="emit('seek', Number(($event.target as HTMLInputElement).value))">
      <button class="time-expand" :aria-expanded="expanded" :aria-controls="detailsId" :aria-label="expanded ? '收起时间设置' : '展开时间设置'" @click="expanded = !expanded"><ChevronUp v-if="expanded" :size="15" /><ChevronDown v-else :size="15" /><span>{{ expanded ? '收起' : '展开' }}</span></button>
      <p v-if="statusText" class="time-status" :class="{ 'time-error': errorCount }" :role="errorCount ? 'alert' : 'status'">
        <button v-if="errorCount" class="status-action" :aria-controls="detailsId" @click="expanded = true">{{ statusText }}</button><span v-else>{{ statusText }}</span>
      </p>
    </div>
    <div v-show="expanded" :id="detailsId" class="time-details">
      <div class="time-controls">
        <label>时间<input :value="inputTime" type="datetime-local" step="3600" aria-label="选择专题北京时间" :disabled="!times.length" @change="select"></label>
        <label>时次<select :value="resolution" aria-label="专题时次分辨率" @change="emit('update:resolution', ($event.target as HTMLSelectElement).value as TimeResolution)"><option value="hour">逐小时</option><option value="day">逐日</option></select></label>
        <label>速率<select :value="rate" aria-label="时间轴速率" @change="emit('update:rate', Number(($event.target as HTMLSelectElement).value))"><option v-for="speed in [1, 2, 5]" :key="speed" :value="speed">{{ speed }}×</option></select></label>
        <button aria-label="复位时间轴" :disabled="!times.length" @click="emit('seek', 0)"><RotateCcw :size="14" /></button>
        <button :disabled="metadataLoading || loading" aria-label="刷新时序数据" @click="emit('refresh')"><RefreshCw :size="14" /></button>
      </div>
      <p class="time-message">范围：{{ times[0] ? timeLabel(times[0], resolution) : '暂无时次' }} — {{ times.at(-1) ? timeLabel(times.at(-1)!, resolution) : '暂无时次' }}</p>
      <p v-if="!counts.length" class="time-message">加入时序专题后显示可用时间范围。</p>
      <p v-else class="time-message"><span v-for="row in counts" :key="row.id">{{ row.name }} {{ row.total - row.missing }}/{{ row.total }}</span><span>{{ resolution === 'day' ? '当天已有小时值均值' : '每秒推进一个小时 × 速率' }}</span></p>
      <p v-for="(message, id) in errors" :key="id" class="time-error" role="alert">{{ counts.find(row => row.id === id)?.name ?? id }}：{{ message }}</p>
    </div>
  </section>
</template>

<style scoped>
.time-axis { position: absolute; z-index: 3; bottom: 42px; left: 380px; right: 78px; padding: 8px 12px; container-type: inline-size; max-height: max(56px, calc(100svh - 230px)); display: flex; flex-direction: column; }
.time-bar { display: grid; grid-template-columns: auto auto minmax(60px, 1fr) auto; align-items: center; gap: 8px 12px; flex-shrink: 0; }
.time-current { display: grid; grid-template-columns: auto auto; align-items: baseline; gap: 2px 8px; }
.time-current > span { font-size: 11px; color: #52657d; }
output { font-size: 13px; color: #29405a; font-variant-numeric: tabular-nums; white-space: nowrap; }
.time-current small { grid-column: 1 / -1; font-size: 10px; color: #65788e; }
.time-transport { display: flex; align-items: center; }
button { display: inline-flex; align-items: center; justify-content: center; color: var(--blue); min-width: 32px; min-height: 36px; padding: 0 5px; border-radius: 5px; flex-shrink: 0; }
button:hover:not(:disabled) { background: #edf3fc; }
button:focus-visible, input:focus-visible, select:focus-visible { outline: 2px solid var(--blue); outline-offset: 2px; }
button:disabled { opacity: .35; cursor: default; }
.time-expand { gap: 3px; font-size: 11px; }
.time-progress { width: 100%; min-width: 0; margin: 0; accent-color: var(--blue); }
.time-status { grid-column: 1 / -1; margin: 0; font-size: 11px; line-height: 1.6; color: #8b632b; overflow-wrap: anywhere; }
.time-status .status-action { min-height: 24px; padding: 0; text-align: left; color: inherit; font: inherit; text-decoration: underline; }
.time-details { min-height: 0; max-height: 38svh; overflow-y: auto; scrollbar-width: thin; margin-top: 8px; padding-top: 12px; border-top: 1px solid var(--line); }
.time-controls { display: flex; align-items: center; flex-wrap: wrap; gap: 8px 12px; }
label { display: flex; align-items: center; flex-wrap: wrap; gap: 6px; font-size: 11px; color: #52657d; min-width: 0; }
select, input[type=datetime-local] { max-width: 100%; min-height: 34px; padding: 4px 6px; border: 1px solid var(--line); border-radius: 5px; background: white; font-size: 12px; color: #52657d; min-width: 0; }
.time-message, .time-error { font-size: 11px; line-height: 1.7; margin: 8px 0 0; color: #65788e; overflow-wrap: anywhere; }
.time-message { display: flex; flex-wrap: wrap; gap: 4px 12px; }
.time-error { color: #b94e46; }
@container (max-width: 560px) {
  .time-bar { grid-template-columns: auto minmax(40px, 1fr) auto; gap: 6px 8px; }
  .time-current { grid-column: 1 / 3; }
  .time-expand { grid-column: 3; grid-row: 1; }
  .time-transport { grid-column: 1; grid-row: 2; }
  .time-progress { grid-column: 2 / 4; grid-row: 2; }
}
@container (max-width: 240px) {
  .time-current { grid-template-columns: 1fr; }
  output { font-size: 13px; }
}
@media (max-width: 900px) { .time-axis { left: 308px; } }
@media (max-width: 600px) { .time-axis { left: 12px; right: 64px; bottom: 52px; max-height: max(110px, calc(100svh - 200px)); } button { min-height: 40px; min-width: 36px; } }
</style>
