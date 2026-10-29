import { computed, onBeforeUnmount, ref, watch } from 'vue'
import type { TimeResolution } from '../temporalTypes'
import { dayTime, localDay, normalizedTime } from '../temporal.ts'

export function useTimeAxis(getTimes: () => string[]) {
  const time = ref('')
  const resolution = ref<TimeResolution>('hour')
  const rate = ref(1)
  const playing = ref(false)
  const range = computed(() => {
    const values = getTimes().map(value => resolution.value === 'day' ? localDay(value) : Date.parse(value)).filter(Number.isFinite)
    return values.length ? { first: Math.min(...values), last: Math.max(...values), step: resolution.value === 'day' ? 86400000 : 3600000 } : null
  })
  const maximum = computed(() => range.value ? Math.floor((range.value.last - range.value.first) / range.value.step) : 0)
  const position = computed(() => {
    const selected = time.value ? resolution.value === 'day' ? localDay(time.value) : Date.parse(time.value) : 0
    return range.value ? Math.max(0, Math.min(maximum.value, (selected - range.value.first) / range.value.step)) : 0
  })
  let frame: number | undefined
  let previous = 0, accumulated = 0
  function pause() { playing.value = false; if (frame !== undefined) cancelAnimationFrame(frame); frame = undefined; accumulated = 0 }
  function at(value: number) {
    if (!range.value) return ''
    const coordinate = range.value.first + Math.round(value) * range.value.step
    return resolution.value === 'day' ? dayTime(coordinate) : new Date(coordinate).toISOString()
  }
  function setTime(value: string) {
    pause()
    if (!value || !Number.isFinite(Date.parse(value))) return
    time.value = normalizedTime(value, resolution.value)
  }
  function seek(value: number) { pause(); time.value = at(Math.max(0, Math.min(maximum.value, value))) }
  function step(direction: number) { seek(Math.floor(position.value) + direction) }
  function advance(now: number) {
    frame = undefined
    if (!playing.value) return
    accumulated += (now - previous) / 1000 * rate.value
    previous = now
    const steps = Math.floor(accumulated)
    if (steps) {
      accumulated -= steps
      const next = Math.min(maximum.value, Math.floor(position.value) + steps)
      time.value = at(next)
      if (next >= maximum.value) { pause(); return }
    }
    frame = requestAnimationFrame(advance)
  }
  function play() {
    if (playing.value || !maximum.value) return
    if (position.value >= maximum.value) time.value = at(0)
    playing.value = true
    previous = performance.now()
    accumulated = 0
    frame = requestAnimationFrame(advance)
  }
  watch(() => JSON.stringify([resolution.value, getTimes()]), () => {
    pause()
    if (!time.value && range.value) time.value = at(0)
    else if (time.value) time.value = normalizedTime(time.value, resolution.value)
  }, { immediate: true })
  onBeforeUnmount(pause)
  return { time, resolution, rate, playing, range, maximum, position, setTime, seek, step, play, pause }
}
