import { computed, onScopeDispose, ref, shallowRef, watch } from 'vue'
import { matchDisplayRegion, type DisplayRegion } from '../map/displayRegions.ts'
import { automaticWeather, noWeather, type WeatherMode, type WeatherPoint, type WeatherReading, type WeatherSnapshot, type WeatherStatus } from '../map/weather.ts'

const settleDelay = 600
const queryInterval = 5_000
const cacheTime = 600_000
const referenceTime = 1_800_000
const failureDelay = 60_000
const mode = ref<WeatherMode>('auto')
const cache = new Map<string, { reading: WeatherReading; expires: number; regionId: string }>()
const retryAt = new Map<string, number>()
let lastQuery = -Infinity
let limitedUntil = 0

function sample(region: DisplayRegion) {
  const latitude = Number(region.latitude.toFixed(2))
  const longitude = Number(region.longitude.toFixed(2))
  return { latitude, longitude, cell: `${latitude},${longitude}` }
}

function retryDelay(response: Response) {
  const header = response.headers.get('Retry-After')
  const seconds = header === null ? NaN : Number(header)
  return Number.isFinite(seconds) && seconds >= 0 ? Math.max(1_000, seconds * 1_000)
    : response.status === 429 ? cacheTime : failureDelay
}

export function useWeatherView(getPoint: () => WeatherPoint | null, enabled: () => boolean,
  regions: () => readonly DisplayRegion[] | null) {
  const reading = shallowRef<WeatherReading | null>(null)
  const reference = shallowRef<WeatherReading | null>(null)
  const region = shallowRef<DisplayRegion | null>(null)
  const state = ref<WeatherStatus>('hidden')
  const cameraMoving = ref(false)
  const status = computed<WeatherStatus>(() => cameraMoving.value ? 'hidden' : state.value)
  const display = computed<WeatherSnapshot>(() => {
    if (!enabled()) return noWeather
    if (mode.value !== 'auto') return { source: 'manual', effect: mode.value }
    return !cameraMoving.value && reading.value ? automaticWeather(reading.value) : noWeather
  })
  let timer: ReturnType<typeof setTimeout> | undefined
  let referenceTimer: ReturnType<typeof setTimeout> | undefined
  let request: AbortController | undefined
  let currentCell = ''
  const automatic = () => enabled() && mode.value === 'auto' && !cameraMoving.value

  function stopTimer() {
    clearTimeout(timer)
    timer = undefined
  }

  function clearReference() {
    clearTimeout(referenceTimer)
    reference.value = null
  }

  function cancel() {
    stopTimer()
    clearReference()
    request?.abort()
    request = undefined
    currentCell = ''
    region.value = null
    reading.value = null
    state.value = 'hidden'
  }

  function moving() {
    cameraMoving.value = true
    stopTimer()
  }

  function schedule(delay: number) {
    if (!automatic()) return
    timer = setTimeout(() => {
      timer = undefined
      if (automatic()) update()
    }, Math.min(delay, 2_147_483_647))
  }

  function showFailure(limited: boolean, delay: number) {
    state.value = limited ? 'limited' : 'unavailable'
    const previous = cache.get(currentCell)
    clearReference()
    if (previous && previous.regionId === region.value?.id) {
      const remaining = Date.parse(previous.reading.valid_at) + referenceTime - Date.now()
      if (remaining > 0) {
        reference.value = previous.reading
        referenceTimer = setTimeout(clearReference, remaining)
      }
    }
    schedule(delay)
  }

  function update(debounce = 0) {
    const selected = region.value
    if (!selected || request) return
    const { latitude, longitude, cell } = sample(selected)
    const now = Date.now()
    const cached = cache.get(cell)
    if (cached && cached.expires > now) {
      reading.value = cached.reading
      state.value = 'ready'
      clearReference()
      schedule(cached.expires - now)
      return
    }
    reading.value = null
    const retry = Math.max(limitedUntil, retryAt.get(cell) ?? 0)
    if (retry > now) {
      showFailure(limitedUntil > now, retry - now)
      return
    }
    clearReference()
    state.value = 'loading'
    const delay = Math.max(debounce, lastQuery + queryInterval - now)
    if (delay > 0) { schedule(delay); return }
    for (const [key, entry] of cache) {
      if (entry.expires <= now && Date.parse(entry.reading.valid_at) + referenceTime <= now) cache.delete(key)
    }
    for (const [key, until] of retryAt) if (until <= now) retryAt.delete(key)
    lastQuery = now
    void query({ latitude, longitude }, cell, selected.id)
  }

  async function query({ latitude, longitude }: WeatherPoint, cell: string, regionId: string) {
    const pending = request = new AbortController()
    try {
      const response = await fetch(`/api/weather/current?lat=${latitude}&lon=${longitude}`, { signal: pending.signal })
      if (request !== pending) return
      if (!response.ok) {
        const delay = retryDelay(response)
        const limited = response.status === 429
        if (limited) limitedUntil = Math.max(limitedUntil, Date.now() + delay)
        else retryAt.set(cell, Date.now() + delay)
        showFailure(limited, delay)
        return
      }
      const value: WeatherReading = await response.json()
      if (request !== pending) return
      cache.set(cell, { reading: value, expires: Date.now() + cacheTime, regionId })
      reading.value = value
      state.value = 'ready'
      schedule(cacheTime)
    } catch {
      if (request === pending) {
        retryAt.set(cell, Date.now() + failureDelay)
        showFailure(false, failureDelay)
      }
    } finally {
      if (request === pending) request = undefined
    }
  }

  function resized() {
    if (!automatic()) return
    const point = getPoint()
    const catalog = regions()
    const selected = catalog && matchDisplayRegion(point, catalog)
    if (!selected) {
      cancel()
      if (point && catalog) state.value = 'outside'
      return
    }
    const { cell } = sample(selected)
    if (region.value?.id === selected.id && currentCell === cell) {
      region.value = selected
      if (!timer && !request) update(settleDelay)
      return
    }
    cancel()
    region.value = selected
    currentCell = cell
    update(settleDelay)
  }

  function settled() {
    cameraMoving.value = false
    resized()
  }

  watch([enabled, mode], () => {
    cancel()
    resized()
  }, { immediate: true, flush: 'sync' })
  watch(regions, resized, { flush: 'sync' })
  onScopeDispose(cancel)
  return { mode, status, display, region, reference, moving, settled, resized }
}
