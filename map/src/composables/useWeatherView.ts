import { computed, onScopeDispose, ref, shallowRef, watch } from 'vue'
import { automaticWeather, noWeather, type WeatherMode, type WeatherPoint, type WeatherReading, type WeatherSnapshot, type WeatherStatus } from '../map/weather.ts'

const settleDelay = 600
const queryInterval = 5_000
const cacheTime = 600_000
const mode = ref<WeatherMode>('auto')
const cache = new Map<string, { reading: WeatherReading; expires: number }>()
let lastQuery = -Infinity

export function useWeatherView(getPoint: () => WeatherPoint | null, enabled: () => boolean) {
  const reading = shallowRef<WeatherReading | null>(null)
  const status = ref<WeatherStatus>('hidden')
  const display = computed<WeatherSnapshot>(() => {
    if (!enabled()) return noWeather
    if (mode.value !== 'auto') return { source: 'manual', effect: mode.value }
    return reading.value ? automaticWeather(reading.value) : noWeather
  })
  let timer: ReturnType<typeof setTimeout> | undefined
  let request: AbortController | undefined
  let currentCell = ''
  let cameraMoving = false
  const automatic = () => enabled() && mode.value === 'auto' && !cameraMoving

  function cancel() {
    clearTimeout(timer)
    timer = undefined
    request?.abort()
    request = undefined
    currentCell = ''
  }

  function moving() {
    cameraMoving = true
    cancel()
    reading.value = null
    status.value = 'hidden'
  }

  function schedule(point: WeatherPoint, cell: string, delay: number) {
    timer = setTimeout(() => {
      timer = undefined
      if (!automatic() || cell !== currentCell) return
      update(point, cell)
    }, delay)
  }

  function update(point: WeatherPoint, cell: string, debounce = 0) {
    const now = Date.now()
    const cached = cache.get(cell)
    if (cached && cached.expires > now) {
      reading.value = cached.reading
      status.value = 'ready'
      schedule(point, cell, cached.expires - now)
      return
    }
    reading.value = null
    status.value = 'loading'
    const delay = Math.max(debounce, lastQuery + queryInterval - now)
    if (delay > 0) { schedule(point, cell, delay); return }
    for (const [key, entry] of cache) if (entry.expires <= now) cache.delete(key)
    lastQuery = now
    void query(point, cell)
  }

  async function query({ latitude, longitude }: WeatherPoint, cell: string) {
    const pending = request = new AbortController()
    try {
      const response = await fetch(`/api/weather/current?lat=${latitude}&lon=${longitude}`, { signal: pending.signal })
      if (!response.ok) throw new Error('当前天气暂不可用')
      const value: WeatherReading = await response.json()
      if (request !== pending) return
      cache.set(cell, { reading: value, expires: Date.now() + cacheTime })
      reading.value = value
      status.value = 'ready'
    } catch {
      if (request === pending) status.value = 'unavailable'
    } finally {
      if (request === pending) {
        request = undefined
        schedule({ latitude, longitude }, cell, cacheTime)
      }
    }
  }

  function resized() {
    if (!automatic()) return
    const point = getPoint()
    if (!point) {
      cancel()
      reading.value = null
      status.value = 'hidden'
      return
    }
    const latitude = Number(point.latitude.toFixed(2))
    const longitude = Number(point.longitude.toFixed(2))
    const cell = `${latitude},${longitude}`
    if (cell === currentCell) return
    cancel()
    currentCell = cell
    update({ latitude, longitude }, cell, settleDelay)
  }

  function settled() {
    cameraMoving = false
    resized()
  }

  watch([enabled, mode], () => {
    cancel()
    reading.value = null
    status.value = 'hidden'
    resized()
  }, { immediate: true, flush: 'sync' })
  onScopeDispose(cancel)
  return { mode, status, display, moving, settled, resized }
}
