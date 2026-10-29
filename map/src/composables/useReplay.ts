import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { replayPosition, replayStep, type replayTimeline } from '../simulationReplay.ts'

export function useReplay(getTimeline: () => ReturnType<typeof replayTimeline> | null) {
  const seconds = ref(0)
  const rate = ref(1)
  const playing = ref(false)
  const duration = computed(() => getTimeline()?.duration ?? 0)
  const positions = computed(() => ({ baseline: replayPosition(getTimeline()?.baseline ?? null, seconds.value),
    blocked: replayPosition(getTimeline()?.blocked ?? null, seconds.value) }))
  let frame: number | undefined
  let previous = 0

  function pause() {
    playing.value = false
    if (frame !== undefined) cancelAnimationFrame(frame)
    frame = undefined
  }
  function advance(now: number) {
    frame = undefined
    if (!playing.value) return
    seconds.value = Math.min(duration.value, seconds.value + (now - previous) / 1000 * rate.value)
    previous = now
    if (seconds.value >= duration.value) playing.value = false
    else frame = requestAnimationFrame(advance)
  }
  function play() {
    if (playing.value || duration.value <= 0) return
    if (seconds.value >= duration.value) seconds.value = 0
    previous = performance.now()
    playing.value = true
    frame = requestAnimationFrame(advance)
  }
  function seek(value: number) { pause(); seconds.value = Math.min(duration.value, Math.max(0, value)) }
  function reset() { seek(0) }
  function step(direction: number) { seek(replayStep(getTimeline()?.ticks ?? [0], seconds.value, direction)) }
  watch(getTimeline, reset)
  onBeforeUnmount(pause)
  return { seconds, rate, playing, duration, positions, play, pause, seek, step, reset }
}
