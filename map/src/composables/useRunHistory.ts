import { onBeforeUnmount, ref, shallowRef } from 'vue'
import { getRuns } from '../api.ts'
import type { RunQuery, RunRecord } from '../simulationTypes'

export function useRunHistory() {
  const items = shallowRef<RunRecord[]>([])
  const total = ref(0)
  const page = ref(1)
  const pageSize = ref(20)
  const query = shallowRef<Omit<RunQuery, 'page' | 'page_size'>>({})
  const loading = ref(false)
  const error = ref('')
  let alive = true
  let version = 0
  let controller: AbortController | undefined

  async function refresh() {
    if (!alive) return
    const current = ++version
    controller?.abort()
    controller = new AbortController()
    loading.value = true
    error.value = ''
    try {
      const result = await getRuns({ ...query.value, page: page.value, page_size: pageSize.value }, controller.signal)
      if (!alive || current !== version) return
      items.value = result.items
      total.value = result.total
      page.value = result.page
      pageSize.value = result.page_size
    } catch (cause) {
      if (!alive || current !== version) return
      items.value = []
      total.value = 0
      error.value = cause instanceof Error ? cause.message : '运行历史读取失败'
    } finally {
      if (alive && current === version) loading.value = false
    }
  }
  function setQuery(value: Omit<RunQuery, 'page' | 'page_size'>) {
    query.value = { ...value }
    page.value = 1
    return refresh()
  }
  function setPage(value: number) {
    page.value = Math.max(1, Math.trunc(value))
    return refresh()
  }
  onBeforeUnmount(() => { alive = false; ++version; controller?.abort() })
  return { items, total, page, pageSize, query, loading, error, refresh, setQuery, setPage }
}
