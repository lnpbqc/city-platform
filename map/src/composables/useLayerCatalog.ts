import { onBeforeUnmount, onMounted, ref } from 'vue'
import { getLayerCatalog, deleteLayer, saveCatalogMapState } from '../api.ts'
import {
  mapLayer,
  samples,
  samplesForCampus,
  type MapLayer,
  type LayerRecord,
  type LayerMapState,
} from '../types.ts'
import type { CampusKey } from '../campuses'
import { defaultCampus } from '../campuses.ts'
import type { MapController } from '../mapController'
import { moveTarget } from '../layerTree.ts'

export function useLayerCatalog(
  getController: () => MapController | undefined,
  notify: (message: string) => void,
) {
  const layers = ref<MapLayer[]>(
    samples.map((record) => mapLayer(record, true)),
  )
  const backend = ref<'loading' | 'online' | 'offline'>('loading')
  const catalogError = ref('')
  const deleting = ref('')
  const revision = ref(0)
  const mapStateErrors = ref<Record<string, string>>({})
  const ordering = ref(false)
  const orderError = ref('')
  type PendingState = {
    desired: LayerMapState
    dirty: boolean
    saving: boolean
    timer?: ReturnType<typeof setTimeout>
  }
  const pendingStates = new Map<string, PendingState>()
  const loadingLayers = new Map<string, Promise<void>>()
  let disposed = false
  let campus = defaultCampus.key
  let catalogLoaded = false
  let requestVersion = 0
  let catalogRequest: AbortController | undefined
  async function flushState(id: string) {
    const pending = pendingStates.get(id)
    if (!pending || pending.saving || !pending.dirty) return
    clearTimeout(pending.timer)
    pending.timer = undefined
    pending.saving = true
    pending.dirty = false
    let failed = false
    try {
      await saveCatalogMapState(id, { ...pending.desired }, campus)
      if (!disposed && pendingStates.get(id) === pending) delete mapStateErrors.value[id]
    } catch (cause) {
      failed = true
      pending.dirty = true
      if (!disposed && pendingStates.get(id) === pending)
        mapStateErrors.value[id] = cause instanceof Error ? cause.message : '无法保存地图状态'
    } finally {
      pending.saving = false
      if (!failed && pendingStates.get(id) === pending && pending.dirty && !pending.timer)
        void flushState(id)
    }
  }
  function persistState(layer: MapLayer, state: LayerMapState, debounce = false) {
    Object.assign(layer, state)
    if (layer.builtin && !catalogLoaded) return
    let pending = pendingStates.get(layer.id)
    if (!pending) {
      pending = { desired: state, dirty: true, saving: false }
      pendingStates.set(layer.id, pending)
    }
    pending.desired = state
    pending.dirty = true
    clearTimeout(pending.timer)
    pending.timer = undefined
    delete mapStateErrors.value[layer.id]
    if (debounce) pending.timer = setTimeout(() => {
      pending.timer = undefined
      void flushState(layer.id)
    }, 300)
    else void flushState(layer.id)
  }
  function stateFor(layer: MapLayer, attached = layer.map_attached ?? layer.attached): LayerMapState {
    return { map_attached: attached, map_visible: layer.visible, map_opacity: layer.opacity }
  }
  function forgetState(id: string) {
    clearTimeout(pendingStates.get(id)?.timer)
    pendingStates.delete(id)
    delete mapStateErrors.value[id]
  }
  function retryMapState(layer: MapLayer) {
    delete mapStateErrors.value[layer.id]
    void flushState(layer.id)
  }
  function loadResource(layer: MapLayer, visible: boolean) {
    const existing = loadingLayers.get(layer.id)
    if (layer.status === 'loading' && existing) return existing
    const loading = Promise.resolve(getController()?.load(layer))
    layer.visible = visible
    const finished: Promise<void> = loading.finally(() => {
      if (loadingLayers.get(layer.id) === finished) loadingLayers.delete(layer.id)
    })
    loadingLayers.set(layer.id, finished)
    return finished
  }
  async function restoreAttachedLayers() {
    const controller = getController()
    if (!controller || disposed || backend.value === 'loading') return
    await Promise.all(layers.value.filter((layer) => layer.map_attached && !layer.attached && layer.status === 'idle')
      .map(async (layer) => {
        const visible = layer.map_visible ?? true
        layer.opacity = layer.map_opacity ?? 1
        await loadResource(layer, visible)
      }))
  }
  async function controllerReady() {
    await restoreAttachedLayers()
  }
  async function joinLayer(layer: MapLayer) {
    layer.visible = true
    persistState(layer, stateFor(layer, true))
    const controller = getController()
    if (!controller) return
    if (!layer.attached || layer.status === 'error' || layer.status === 'loading')
      await loadResource(layer, true)
    else controller.appearance(layer)
  }
  function removeFromMap(layer: MapLayer) {
    getController()?.remove(layer)
    persistState(layer, stateFor(layer, false))
  }
  function changeOpacity(layer: MapLayer, value: number) {
    layer.opacity = value
    getController()?.appearance(layer)
    persistState(layer, stateFor(layer), true)
  }
  function flushPending() {
    for (const id of pendingStates.keys()) void flushState(id)
  }
  async function moveLayer(layer: MapLayer, direction: number) {
    const target = moveTarget(layers.value, layer, direction)
    if (ordering.value || target === null) return
    ordering.value = true
    orderError.value = ''
    try {
      await saveCatalogMapState(layer.id, { order: target }, campus)
      if (disposed) return
      await refreshCatalog()
      if (!disposed && backend.value === 'offline') orderError.value = `顺序已保存，目录刷新失败：${catalogError.value}。请刷新目录。`
    } catch (cause) {
      if (!disposed) orderError.value = `顺序未保存：${cause instanceof Error ? cause.message : '保存失败'}。可再次点击上移或下移重试。`
    } finally { ordering.value = false }
  }
  async function switchCampus(key: CampusKey) {
    if (campus === key) return
    campus = key
    await refreshCatalog()
  }
  async function refreshCatalog() {
    const version = ++requestVersion
    const requestedCampus = campus
    catalogRequest?.abort()
    catalogRequest = new AbortController()
    backend.value = 'loading'
    try {
      const records = await getLayerCatalog(requestedCampus, catalogRequest.signal)
      if (disposed || version !== requestVersion) return
      const ids = new Set(records.map((record) => record.id))
      for (const layer of layers.value)
        if (!ids.has(layer.id)) {
          if (layer.attached || layer.status === 'loading') getController()?.remove(layer)
          forgetState(layer.id)
        }
      const existing = new Map(
        layers.value
          .map((layer) => [layer.id, layer]),
      )
      layers.value = records.map((record) => {
          const mapped = mapLayer(record)
          const layer = existing.get(record.id)
          if (!layer) return mapped
          const sourceChanged = layer.url !== mapped.url || layer.type !== mapped.type
            || layer.asset_id !== mapped.asset_id || layer.asset_version !== mapped.asset_version
          if (sourceChanged) {
            getController()?.remove(layer)
            // Campus changes rebind the shared default state; custom source edits require an explicit join.
            if (!mapped.builtin) {
              layer.visible = record.map_visible ?? layer.visible
              layer.opacity = record.map_opacity ?? layer.opacity
              persistState(layer, stateFor(layer, false))
            }
          }
          const pending = pendingStates.get(record.id)
          const unsaved = pending && (pending.saving || pending.dirty || pending.timer)
          const { attached: _attached, status: _status, error: _error, visible: _visible, opacity: _opacity, ...metadata } = mapped
          Object.assign(layer, metadata, unsaved ? pending.desired : {})
          if (record.map_attached !== undefined || unsaved) {
            layer.visible = layer.map_visible ?? true
            layer.opacity = layer.map_opacity ?? 1
            if (!layer.map_attached && layer.attached) getController()?.remove(layer)
            else if (layer.attached) getController()?.appearance(layer)
          }
          return layer
        })
      catalogLoaded = true
      getController()?.syncOrder?.(layers.value)
      backend.value = 'online'
      catalogError.value = ''
      revision.value++
      await restoreAttachedLayers()
    } catch (cause) {
      if (!disposed && version === requestVersion) {
        backend.value = 'offline'
        catalogError.value =
          cause instanceof Error ? cause.message : '无法连接图层服务'
        if (!catalogLoaded) {
          for (const record of samplesForCampus(requestedCampus)) {
            const layer = layers.value.find((item) => item.builtin && item.id === record.id)
            if (!layer) continue
            if (layer.url !== record.url) getController()?.remove(layer)
            Object.assign(layer, record)
            layer.map_attached ??= record.id !== 'demo-buildings'
          }
          await restoreAttachedLayers()
        }
      }
    }
  }
  function toggleVisibility(layer: MapLayer) {
    if (!layer.attached || layer.status === 'error')
      void joinLayer(layer)
    else {
      layer.visible = !layer.visible
      getController()?.appearance(layer)
      persistState(layer, stateFor(layer))
    }
  }
  function saved(record: LayerRecord) {
    backend.value = 'online'
    let layer = layers.value.find((item) => item.id === record.id)
    if (layer) {
      if (layer.url !== record.url || layer.type !== record.type) {
        getController()?.remove(layer)
        persistState(layer, stateFor(layer, false))
        notify('登记已更新，数据地址或类型已变化，请重新加入地图')
      } else notify('图层登记已保存')
      const pending = pendingStates.get(layer.id)
      Object.assign(layer, record, pending && (pending.saving || pending.dirty) ? pending.desired : {})
    } else {
      layers.value.push(mapLayer(record))
      notify('图层登记已保存，可按需加入地图')
    }
    revision.value++
  }
  async function removeRecord(layer: MapLayer) {
    if (
      !window.confirm(`删除“${layer.name}”的登记记录？已上传的磁盘文件将保留。`)
    )
      return
    deleting.value = layer.id
    try {
      await deleteLayer(layer.id)
      getController()?.remove(layer)
      forgetState(layer.id)
      layers.value = layers.value.filter((item) => item.id !== layer.id)
      revision.value++
      notify('登记已删除，磁盘文件已保留')
    } catch (cause) {
      notify(cause instanceof Error ? cause.message : '删除失败')
    } finally {
      deleting.value = ''
    }
  }

  onMounted(refreshCatalog)
  if (typeof window !== 'undefined') window.addEventListener?.('pagehide', flushPending)
  onBeforeUnmount(() => {
    flushPending()
    if (typeof window !== 'undefined') window.removeEventListener?.('pagehide', flushPending)
    disposed = true
    ++requestVersion
    catalogRequest?.abort()
    for (const pending of pendingStates.values()) clearTimeout(pending.timer)
  })
  return {
    layers,
    backend,
    catalogError,
    deleting,
    revision,
    mapStateErrors,
    ordering,
    orderError,
    moveLayer,
    controllerReady,
    joinLayer,
    removeFromMap,
    changeOpacity,
    retryMapState,
    switchCampus,
    refreshCatalog,
    saved,
    removeRecord,
    toggleVisibility,
  }
}
