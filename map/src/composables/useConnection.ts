import { onBeforeUnmount, onMounted, ref, shallowRef } from 'vue'
import { ApiError } from '../api.ts'
import { subscribeApiEvents } from '../apiEvents.ts'

export function useConnection(onRecovered: () => void) {
  const status = ref<'checking' | 'online' | 'retrying'>('checking')
  const lastError = shallowRef<ApiError | null>(null)
  const retryIn = ref(0)
  const delays = [1000, 2000, 5000, 10000, 30000]
  let disposed = false, failed = false, attempt = 0, version = 0
  let timer: ReturnType<typeof setTimeout> | undefined
  let pending: AbortController | undefined
  let unsubscribe: (() => void) | undefined
  function schedule(delay: number) {
    clearTimeout(timer)
    if (disposed) return
    retryIn.value = delay / 1000
    timer = setTimeout(probe, delay)
  }
  function connected() {
    status.value = 'online'
    attempt = 0
    retryIn.value = 0
    if (failed) { failed = false; onRecovered() }
  }
  function interrupted(error?: ApiError) {
    status.value = 'retrying'
    failed = true
    if (error) lastError.value = error
  }
  async function probe() {
    if (disposed || pending) return
    retryIn.value = 0
    const current = ++version
    const abort = new AbortController()
    pending = abort
    const timeout = setTimeout(() => abort.abort(), 5000)
    try {
      const response = await fetch('/api/health', { signal: abort.signal, cache: 'no-store' })
      if (!response.ok) throw new ApiError('数据服务健康检查失败', response.status, null, 'HEALTH_CHECK_FAILED', response.headers.get('X-Trace-ID') || `client-${crypto.randomUUID()}`)
      if (!disposed && current === version) connected()
    } catch (cause) {
      if (!disposed && current === version) interrupted(cause instanceof ApiError ? cause : new ApiError('无法连接数据服务', 0, null, 'NETWORK_ERROR', `client-${crypto.randomUUID()}`))
    } finally {
      clearTimeout(timeout)
      pending = undefined
      if (!disposed) schedule(status.value === 'online' ? 10000 : delays[Math.min(attempt++, delays.length - 1)]!)
    }
  }
  function retry() {
    if (!pending) { clearTimeout(timer); void probe() }
  }
  function online() { retry() }
  function offline() { interrupted(); retry() }
  onMounted(() => {
    unsubscribe = subscribeApiEvents(event => {
      if (event.error) lastError.value = event.error
      if (event.reachable) {
        if (event.error && event.error.status >= 500) return
        if (status.value !== 'online') {
          ++version
          pending?.abort()
          connected()
          if (!pending) schedule(10000)
        }
      } else if (event.reachable === false) {
        const retrying = status.value === 'retrying'
        interrupted(event.error)
        if (!pending && !retrying) schedule(0)
      }
    })
    window.addEventListener('online', online)
    window.addEventListener('offline', offline)
    void probe()
  })
  onBeforeUnmount(() => {
    disposed = true; ++version; clearTimeout(timer); pending?.abort(); unsubscribe?.()
    window.removeEventListener('online', online)
    window.removeEventListener('offline', offline)
  })
  return { status, lastError, retryIn, retry }
}
