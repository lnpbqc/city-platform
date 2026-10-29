import { onBeforeUnmount, ref, shallowRef, watch } from 'vue'
import { getObject, getObjects, selectObjects } from '../api.ts'
import type { GeometryDocument, MapLayer, ObjectQuery, ObjectRecord } from '../types'
import type { CampusKey } from '../campuses'
import type { TemporalContext } from '../temporalTypes'

export function useObjects(getLayers: () => MapLayer[], getTime: () => TemporalContext | null = () => null) {
  const activeLayerId = ref('')
  const items = shallowRef<ObjectRecord[]>([])
  const total = ref(0)
  const page = ref(1)
  const pageSize = ref(20)
  const loading = ref(false)
  const error = ref('')
  const type = ref('')
  const q = ref('')
  const selectedId = ref('')
  const selected = shallowRef<ObjectRecord | null>(null)
  const detailLoading = ref(false)
  const detailError = ref('')
  const areaGeometry = shallowRef<GeometryDocument | null>(null)
  const areaIds = shallowRef<string[]>([])
  const selectionProgress = shallowRef<{ loaded: number; total: number } | null>(null)
  let areaItems: ObjectRecord[] | null = null
  let alive = true
  let listVersion = 0
  let detailVersion = 0
  let listAbort: AbortController | undefined
  let detailAbort: AbortController | undefined
  let context = ''
  const failure = (cause: unknown) => cause instanceof Error ? cause.message : '对象请求失败'
  const activeLayer = () => getLayers().find(layer => layer.id === activeLayerId.value && layer.id !== 'basemap' && layer.attached)
  const contextFor = (layer?: MapLayer) => layer ? JSON.stringify([layer.id, layer.asset_id, layer.asset_version, layer.campus]) : ''

  function cancelList() {
    ++listVersion
    listAbort?.abort()
    loading.value = false
    selectionProgress.value = null
  }
  function clearSelection() {
    ++detailVersion
    detailAbort?.abort()
    selectedId.value = ''
    selected.value = null
    detailLoading.value = false
    detailError.value = ''
  }
  function resetArea() {
    areaGeometry.value = null
    areaIds.value = []
    areaItems = null
    selectionProgress.value = null
  }
  function queryFor(layer: MapLayer): ObjectQuery {
    return {
      ...(layer.static === false ? getTime() : null),
      asset_id: layer.asset_id || undefined,
      version: layer.asset_version || undefined,
      layer_id: layer.id,
      campus: (layer.campus || undefined) as CampusKey | undefined,
      type: type.value,
      q: q.value,
      page: page.value,
      page_size: pageSize.value,
    }
  }
  function showAreaPage() {
    total.value = areaItems?.length ?? 0
    page.value = Math.min(page.value, Math.max(1, Math.ceil(total.value / pageSize.value)))
    items.value = (areaItems ?? []).slice((page.value - 1) * pageSize.value, page.value * pageSize.value)
  }
  async function refresh() {
    if (!alive) return
    if (areaGeometry.value) return selectArea(areaGeometry.value)
    cancelList()
    const layer = activeLayer()
    items.value = []
    total.value = 0
    error.value = ''
    if (!layer) return
    const version = listVersion
    listAbort = new AbortController()
    loading.value = true
    try {
      const result = await getObjects(queryFor(layer), listAbort.signal)
      if (!alive || version !== listVersion) return
      items.value = result.items
      total.value = result.total
      page.value = result.page
    } catch (cause) {
      if (alive && version === listVersion) error.value = failure(cause)
    } finally {
      if (alive && version === listVersion) loading.value = false
    }
  }
  function resetLayer(id: string, pageNumber = 1) {
    cancelList()
    clearSelection()
    resetArea()
    activeLayerId.value = id
    context = contextFor(activeLayer())
    type.value = ''
    q.value = ''
    page.value = Math.max(1, Math.trunc(pageNumber) || 1)
    items.value = []
    total.value = 0
    error.value = ''
  }
  async function setLayer(id: string) {
    if (id === activeLayerId.value && context === contextFor(activeLayer())) return
    resetLayer(id)
    await refresh()
  }
  async function setPage(value: number) {
    page.value = Math.max(1, Math.trunc(value) || 1)
    if (areaItems !== null) showAreaPage()
    else await refresh()
  }
  async function applyFilters() {
    page.value = 1
    clearSelection()
    await refresh()
  }
  async function select(id: string) {
    clearSelection()
    if (!id || !alive) return
    selectedId.value = id
    const version = detailVersion
    const layer = activeLayer()
    detailAbort = new AbortController()
    detailLoading.value = true
    try {
      const result = await getObject(id, detailAbort.signal, layer?.static === false ? getTime() : null)
      if (!alive || version !== detailVersion) return
      if (layer?.asset_id && result.asset.asset_id !== layer.asset_id
        || layer?.asset_version && result.asset.version !== layer.asset_version)
        throw new Error('对象不属于当前图层资产版本')
      selected.value = result
    } catch (cause) {
      if (alive && version === detailVersion) detailError.value = failure(cause)
    } finally {
      if (alive && version === detailVersion) detailLoading.value = false
    }
  }
  async function showPicked(id: string, layerId: string, pageNumber: number) {
    resetLayer(layerId, pageNumber)
    if (!activeLayer()) return
    await Promise.all([refresh(), select(id)])
  }
  async function selectArea(geometry: GeometryDocument) {
    if (!alive) return
    cancelList()
    clearSelection()
    resetArea()
    areaGeometry.value = structuredClone(geometry)
    page.value = 1
    items.value = []
    total.value = 0
    error.value = ''
    const layer = activeLayer()
    if (!layer) return
    const version = listVersion
    listAbort = new AbortController()
    const signal = listAbort.signal
    const query = { ...queryFor(layer), page_size: 100 }
    const mask = areaGeometry.value
    loading.value = true
    selectionProgress.value = { loaded: 0, total: 0 }
    try {
      const collected: ObjectRecord[] = []
      let expected = 0
      for (let currentPage = 1; currentPage === 1 || collected.length < expected; currentPage++) {
        const result = await selectObjects({ ...query, page: currentPage }, mask, signal)
        if (!alive || version !== listVersion) return
        if (currentPage === 1) expected = result.total
        if (result.total !== expected || (result.items.length === 0 && collected.length < expected))
          throw new Error('区域选择结果已变化，请重新选择')
        collected.push(...result.items)
        selectionProgress.value = { loaded: collected.length, total: expected }
      }
      if (collected.length !== expected || new Set(collected.map(item => item.object_id)).size !== expected)
        throw new Error('区域选择结果不完整，请重新选择')
      areaItems = collected
      areaIds.value = collected.map(item => item.object_id)
      showAreaPage()
    } catch (cause) {
      if (alive && version === listVersion) {
        areaItems = null
        areaIds.value = []
        error.value = failure(cause)
      }
    } finally {
      if (alive && version === listVersion) {
        loading.value = false
        selectionProgress.value = null
      }
    }
  }
  async function clearArea() {
    cancelList()
    resetArea()
    clearSelection()
    page.value = 1
    await refresh()
  }

  watch(() => getLayers().map(layer => [layer.id, layer.attached, layer.asset_id, layer.asset_version, layer.campus]), () => {
    const layer = activeLayer() ?? getLayers().find(item => item.attached && item.id !== 'basemap')
    if (contextFor(layer) === context) return
    resetLayer(layer?.id ?? '')
    void refresh()
  }, { immediate: true })
  watch(() => activeLayer()?.static === false ? JSON.stringify(getTime()) : '', () => {
    if (activeLayer()?.static !== false) return
    const identity = selectedId.value
    void refresh()
    if (identity) void select(identity)
  })
  onBeforeUnmount(() => {
    alive = false
    cancelList()
    clearSelection()
  })
  return {
    activeLayerId, items, total, page, pageSize, loading, error, type, q,
    selectedId, selected, detailLoading, detailError, areaGeometry, areaIds, selectionProgress,
    refresh, setLayer, setPage, applyFilters, select, showPicked, selectArea, clearArea, clearSelection,
  }
}
