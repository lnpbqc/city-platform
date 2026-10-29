<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, shallowRef, watch } from 'vue'
import { Play, Pause, RotateCcw, SkipBack, SkipForward } from '@lucide/vue'
import type { NetworkRecord, RunResult } from '../simulationTypes'
import { replayTimeline } from '../simulationReplay'
import { useReplay } from '../composables/useReplay'

const props = defineProps<{ network: NetworkRecord; result: RunResult; active: boolean }>()
const emit = defineEmits<{ position: [value: { baseline: number[] | null; blocked: number[] | null }] }>()
const timeline = shallowRef<ReturnType<typeof replayTimeline> | null>(null)
const error = ref('')
watch(() => [props.network, props.result], () => {
  try { timeline.value = replayTimeline(props.network, props.result); error.value = '' }
  catch (cause) { timeline.value = null; error.value = cause instanceof Error ? cause.message : '回放路径不可用' }
}, { immediate: true })
const { seconds, rate, playing, duration, positions, play, pause, seek, step, reset } = useReplay(() => timeline.value)
const hasPath = computed(() => !!timeline.value?.baseline || !!timeline.value?.blocked)
watch(positions, value => emit('position', value), { immediate: true })
watch(() => props.active, active => { if (!active) pause() })
function visibility() { if (document.hidden) pause() }
onMounted(() => document.addEventListener('visibilitychange', visibility))
onBeforeUnmount(() => { document.removeEventListener('visibilitychange', visibility); emit('position', { baseline: null, blocked: null }) })
</script>

<template>
  <section class="replay" aria-label="路径回放">
    <div class="replay-heading"><h3>预计时间回放</h3><output aria-label="回放时间">{{ seconds.toFixed(1) }} / {{ duration.toFixed(1) }} 秒</output></div>
    <input :value="seconds" type="range" min="0" :max="duration || 1" step="0.1" :disabled="!duration" aria-label="回放进度" @input="seek(Number(($event.target as HTMLInputElement).value))">
    <div class="replay-actions">
      <button :disabled="!duration" :aria-label="playing ? '暂停回放' : '播放回放'" @click="playing ? pause() : play()"><Pause v-if="playing" :size="15" /><Play v-else :size="15" /></button>
      <button aria-label="上一步回放" :disabled="!duration || seconds <= 0" @click="step(-1)"><SkipBack :size="15" /></button>
      <button aria-label="下一步回放" :disabled="!duration || seconds >= duration" @click="step(1)"><SkipForward :size="15" /></button>
      <button aria-label="复位回放" :disabled="!hasPath" @click="reset"><RotateCcw :size="14" /></button>
      <label>速率<select v-model.number="rate" aria-label="回放速率"><option v-for="speed in [0.5, 1, 2, 4, 8]" :key="speed" :value="speed">{{ speed }}×</option></select></label>
      <span v-if="!hasPath">没有可回放路径</span><span v-else-if="!duration">起终点相同</span><span v-else>按边预计时间插值，节点步进</span>
    </div>
    <p v-if="error" role="alert">{{ error }}</p>
  </section>
</template>

<style scoped>
.replay { border-top: 1px solid var(--line); margin-top: 16px; padding-top: 14px; }
.replay-heading, .replay-actions { display: flex; align-items: center; gap: 12px; }
.replay-heading { justify-content: space-between; }
h3, output { margin: 0; font-size: 11px; color: #65788e; font-weight: 500; }
input[type=range] { width: 100%; margin: 12px 0; accent-color: var(--blue); }
button { color: var(--blue); display: grid; place-items: center; min-width: 26px; min-height: 26px; }
button:disabled { opacity: .35; cursor: default; }
label { display: flex; align-items: center; gap: 7px; font-size: 11px; color: #65788e; }
select { padding: 4px 6px; border: 1px solid var(--line); border-radius: 4px; background: white; }
.replay-actions > span { margin-left: auto; font-size: 10px; color: #8c9aab; }
p { color: #b94e46; font-size: 11px; }
@media (max-width: 900px) { .replay-actions { gap: 7px; flex-wrap: wrap; } .replay-actions > span { width: 100%; margin-left: 0; } }
</style>
