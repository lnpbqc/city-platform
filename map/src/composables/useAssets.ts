import { onBeforeUnmount, ref, shallowRef } from 'vue'
import {
  ApiError,
  deleteAsset,
  getAsset,
  getAssetPage,
  getStats,
  reconcileAssets,
} from '../api.ts'
import type { AssetDetail, AssetRecord, AssetFilters, AssetReference, StatsOverview } from '../types'

export function useAssets() {
  const assets = shallowRef<AssetRecord[]>([])
  const page = ref(1)
  const pageSize = ref(20)
  const total = ref(0)
  const stats = shallowRef<StatsOverview | null>(null)
  const statsLoading = ref(false)
  const statsError = ref('')
  const query = shallowRef<AssetFilters>({})
  const loading = ref(false)
  const scanning = ref(false)
  const error = ref('')
  const message = ref('')
  const detail = shallowRef<AssetDetail | null>(null)
  const detailId = ref('')
  const detailLoading = ref(false)
  const detailError = ref('')
  const pendingDelete = shallowRef<AssetRecord | null>(null)
  const deleting = ref(false)
  const deleteError = ref('')
  const conflicts = shallowRef<AssetReference[]>([])
  let alive = true
  let listVersion = 0
  let statsVersion = 0
  let detailVersion = 0
  const failure = (cause: unknown) =>
    cause instanceof Error ? cause.message : '请求失败，请检查后端服务'

  async function refreshStats() {
    if (!alive) return
    const version = ++statsVersion
    statsLoading.value = true
    statsError.value = ''
    stats.value = null
    try {
      const result = await getStats()
      if (alive && version === statsVersion) stats.value = result
    } catch (cause) {
      if (alive && version === statsVersion) statsError.value = failure(cause)
    } finally {
      if (alive && version === statsVersion) statsLoading.value = false
    }
  }
  async function refreshList() {
    if (!alive) return
    const version = ++listVersion
    loading.value = true
    error.value = ''
    try {
      const result = await getAssetPage({ ...query.value, page: page.value, page_size: pageSize.value })
      if (!alive || version !== listVersion) return
      const lastPage = Math.max(1, Math.ceil(result.total / result.page_size))
      if (result.page > lastPage) {
        page.value = lastPage
        await refreshList()
        return
      }
      assets.value = result.items
      page.value = result.page
      pageSize.value = result.page_size
      total.value = result.total
    } catch (cause) {
      if (alive && version === listVersion) {
        assets.value = []
        total.value = 0
        error.value = failure(cause)
      }
    } finally {
      if (alive && version === listVersion) loading.value = false
    }
  }
  async function refresh() { await Promise.all([refreshList(), refreshStats()]) }
  function setQuery(filters: AssetFilters) {
    query.value = { ...filters }
    page.value = 1
    return refresh()
  }
  function setPage(value: number) {
    page.value = Math.max(1, Math.trunc(value))
    return refresh()
  }
  async function scan() {
    scanning.value = true
    message.value = ''
    error.value = ''
    try {
      const result = await reconcileAssets()
      if (!alive) return
      message.value = `扫描完成，补录 ${result.discovered} 份文件资产`
      await refresh()
    } catch (cause) {
      if (alive) error.value = failure(cause)
    } finally {
      if (alive) scanning.value = false
    }
  }
  async function openDetail(id: string) {
    const version = ++detailVersion
    detailId.value = id
    detail.value = null
    detailLoading.value = true
    detailError.value = ''
    try {
      const result = await getAsset(id)
      if (alive && version === detailVersion) detail.value = result
    } catch (cause) {
      if (alive && version === detailVersion) detailError.value = failure(cause)
    } finally {
      if (alive && version === detailVersion) detailLoading.value = false
    }
  }
  function closeDetail() {
    ++detailVersion
    detailId.value = ''
    detail.value = null
    detailError.value = ''
  }
  function askDelete(asset: AssetRecord) {
    if (deleting.value) return
    pendingDelete.value = asset
    deleteError.value = ''
    conflicts.value = []
  }
  function cancelDelete() {
    if (deleting.value) return
    pendingDelete.value = null
    deleteError.value = ''
    conflicts.value = []
  }
  async function confirmDelete() {
    const asset = pendingDelete.value
    if (!asset || deleting.value || conflicts.value.length) return
    deleting.value = true
    deleteError.value = ''
    conflicts.value = []
    try {
      await deleteAsset(asset.id)
      if (!alive) return
      pendingDelete.value = null
      message.value = asset.source_kind === 'external' ? '外部资产登记已移除' : '文件资产已彻底删除'
      if (detailId.value === asset.id) closeDetail()
      await refresh()
    } catch (cause) {
      if (!alive) return
      deleteError.value = failure(cause)
      if (
        cause instanceof ApiError &&
        cause.status === 409 &&
        cause.detail &&
        typeof cause.detail === 'object' &&
        'references' in cause.detail
      ) {
        const references = cause.detail.references
        if (Array.isArray(references)) {
          conflicts.value = references.filter(
            (item): item is AssetReference =>
              !!item &&
              typeof item.id === 'string' &&
              typeof item.name === 'string',
          )
        }
      }
      await refresh()
    } finally {
      if (alive) deleting.value = false
    }
  }
  onBeforeUnmount(() => {
    alive = false
    ++listVersion
    ++statsVersion
    ++detailVersion
  })
  return {
    assets,
    page,
    pageSize,
    total,
    stats,
    statsLoading,
    statsError,
    query,
    setQuery,
    setPage,
    loading,
    scanning,
    error,
    message,
    refresh,
    refreshStats,
    scan,
    detail,
    detailId,
    detailLoading,
    detailError,
    openDetail,
    closeDetail,
    pendingDelete,
    deleting,
    deleteError,
    conflicts,
    askDelete,
    cancelDelete,
    confirmDelete,
  }
}
