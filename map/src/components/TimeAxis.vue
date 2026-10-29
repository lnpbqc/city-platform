<script setup lang="ts">
import { computed } from 'vue'
import { Play, Pause, SkipBack, SkipForward, RotateCcw, RefreshCw, LoaderCircle } from '@lucide/vue'
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
const inputTime = computed(() => props.time ? timeLabel(props.time).replace(' ', 'T') : '')
const missingCount = computed(() => props.counts.reduce((sum, row) => sum + row.missing, 0))
function select(event: Event) { const value = localTime((event.target as HTMLInputElement).value); if (value) emit('select', value) }
</script>

<template>
  <section class="time-axis panel" :aria-label="label ?? '专题时间轴'">
    <header><div><span class="eyebrow">TIME</span><h2>{{ label ?? '专题时间轴' }}</h2></div><output aria-label="当前专题时间">{{ timeLabel(time, resolution) }}<small>北京时间 · {{ resolution === 'day' ? '日均' : '小时' }}</small></output><button :disabled="metadataLoading || loading" aria-label="刷新时序数据" @click="emit('refresh')"><RefreshCw :size="14" /></button></header>
    <div class="time-slider"><span>{{ times[0] ? timeLabel(times[0], resolution) : '暂无时次' }}</span><input type="range" min="0" :max="maximum || 1" step="1" :value="position" :disabled="!times.length" aria-label="专题时间进度" @input="emit('seek', Number(($event.target as HTMLInputElement).value))"><span>{{ times.at(-1) ? timeLabel(times.at(-1)!, resolution) : '' }}</span></div>
    <div class="time-controls">
      <div class="time-transport">
      <button :disabled="!maximum" :aria-label="playing ? '暂停时间轴' : '播放时间轴'" @click="playing ? emit('pause') : emit('play')"><Pause v-if="playing" :size="16" /><Play v-else :size="16" /></button>
      <button aria-label="上一个专题时次" :disabled="!times.length || position <= 0" @click="emit('step', -1)"><SkipBack :size="15" /></button>
      <button aria-label="下一个专题时次" :disabled="!times.length || position >= maximum" @click="emit('step', 1)"><SkipForward :size="15" /></button>
      <button aria-label="复位时间轴" :disabled="!times.length" @click="emit('seek', 0)"><RotateCcw :size="14" /></button>
      </div>
      <div class="time-settings">
      <label>时次<select :value="resolution" aria-label="专题时次分辨率" @change="emit('update:resolution', ($event.target as HTMLSelectElement).value as TimeResolution)"><option value="hour">逐小时</option><option value="day">逐日</option></select></label>
      <label>速率<select :value="rate" aria-label="时间轴速率" @change="emit('update:rate', Number(($event.target as HTMLSelectElement).value))"><option v-for="speed in [1, 2, 5]" :key="speed" :value="speed">{{ speed }}×</option></select></label>
      </div>
      <label class="time-picker">时间<input :value="inputTime" type="datetime-local" step="3600" aria-label="选择专题北京时间" :disabled="!times.length" @change="select"></label>
    </div>
    <p v-if="metadataLoading || loading" class="time-message" role="status"><LoaderCircle :size="12" class="spin" />{{ metadataLoading ? '正在读取可用时次…' : '正在读取当前专题值…' }}</p>
    <p v-else-if="!counts.length" class="time-message">加入时序专题后显示可用时间范围。</p>
    <p v-else-if="allMissing" class="time-missing" role="status">该时次缺测 / 未覆盖</p>
    <p v-else class="time-message"><span v-for="row in counts" :key="row.id">{{ row.name }} {{ row.total - row.missing }}/{{ row.total }}</span><strong v-if="missingCount">{{ missingCount }} 个对象缺测</strong><span>{{ resolution === 'day' ? '当天已有小时值均值' : '每秒推进一个小时 × 速率' }}</span></p>
    <p v-for="(message, id) in errors" :key="id" class="time-error" role="alert">{{ counts.find(row => row.id === id)?.name }}：{{ message }}</p>
  </section>
</template>

<style scoped>
.time-axis { position: absolute; z-index: 3; bottom: 42px; left: 380px; right: 78px; padding: 16px 20px; container-type: inline-size; }
header, .time-controls, .time-transport, .time-settings, .time-slider, .time-message { display: flex; align-items: center; gap: 12px; }
header { display: grid; grid-template-columns: minmax(0, 1fr) auto 30px; }
h2 { font-size: 13px; font-weight: 550; margin: 3px 0 0; }
output { font-size: 14px; color: #29405a; text-align: right; font-variant-numeric: tabular-nums; overflow-wrap: anywhere; }
output small { display: block; font-size: 10px; color: #8c9aab; margin-top: 4px; }
button { display: grid; place-items: center; color: var(--blue); width: 30px; height: 30px; padding: 0; border-radius: 5px; flex-shrink: 0; }
button:hover:not(:disabled) { background: #edf3fc; }
button:disabled { opacity: .35; cursor: default; }
.time-slider { margin: 14px 0; gap: 10px; }
.time-slider > input { flex: 1; min-width: 20px; accent-color: var(--blue); }
.time-slider > span { font-size: 10px; color: #8c9aab; max-width: 120px; }
.time-controls { flex-wrap: wrap; gap: 10px 16px; }
.time-transport { gap: 3px; flex-wrap: wrap; }
.time-settings { gap: 12px; flex-wrap: wrap; }
label { display: flex; align-items: center; gap: 6px; font-size: 11px; color: #65788e; min-width: 0; }
select, input[type=datetime-local] { height: 30px; padding: 4px 6px; border: 1px solid var(--line); border-radius: 5px; background: white; font-size: 11px; color: #52657d; min-width: 0; }
.time-picker { margin-left: auto; }
.time-picker input { flex: 1; width: 170px; }
.time-message, .time-missing, .time-error { font-size: 11px; line-height: 1.7; margin: 12px 0 0; color: #7b8ba0; flex-wrap: wrap; gap: 4px 12px; }
.time-message > span { overflow-wrap: anywhere; }
.time-message strong, .time-missing { color: #a16b31; font-weight: 500; }
.time-error { color: #b94e46; overflow-wrap: anywhere; }
@container (max-width: 560px) {
  .time-picker { flex-basis: 100%; margin-left: 0; }
  .time-slider > span { display: none; }
}
@container (max-width: 300px) {
  header { grid-template-columns: minmax(0, 1fr) 30px; gap: 10px; }
  header > button { grid-column: 2; grid-row: 1; }
  output { grid-column: 1 / -1; text-align: left; font-size: 12px; }
  .time-controls { gap: 8px; }
  .time-settings { gap: 8px; }
  .time-picker { flex-wrap: wrap; }
  .time-picker input { width: 100%; flex-basis: 100%; }
}
@media (max-width: 900px) { .time-axis { left: 308px; } }
@media (max-width: 600px) { .time-axis { left: 12px; right: 64px; bottom: 38px; padding: 12px; max-height: calc(100svh - 260px); overflow-y: auto; scrollbar-width: thin; } }
</style>
