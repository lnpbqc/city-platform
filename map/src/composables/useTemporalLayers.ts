import { computed, onBeforeUnmount, ref, shallowRef, watch } from 'vue'
import { getLayerTimes, getTimeSeries } from '../api.ts'
import type { MapLayer } from '../types'
import type { MapController } from '../mapController'
import type { TimeLayerQuery, TimeSeriesRecord } from '../temporalTypes'
import { useTimeAxis } from './useTimeAxis.ts'

export function useTemporalLayers(getLayers: () => MapLayer[], getController: () => MapController | undefined) {
  const dynamicLayers = computed(() => getLayers().filter(layer => layer.attached && layer.static === false))
  const timesByLayer = shallowRef<Record<string, string[]>>({})
  const times = computed(() => [...new Set(Object.values(timesByLayer.value).flat())].sort())
  const axis = useTimeAxis(() => times.value)
  const frames = shallowRef<Record<string, TimeSeriesRecord>>({})
  const metadataLoading = ref(false), loading = ref(false)
  const metadataErrors = shallowRef<Record<string, string>>({}), dataErrors = shallowRef<Record<string, string>>({})
  const errors = computed(() => ({ ...metadataErrors.value, ...dataErrors.value }))
  const counts = computed(() => dynamicLayers.value.map(layer => {
    const frame = frames.value[layer.id]
    return { id: layer.id, name: layer.name, total: frame?.items.length ?? 0, missing: frame?.items.filter(item => item.missing).length ?? 0 }
  }))
  const allMissing = computed(() => !loading.value && dynamicLayers.value.length > 0 && counts.value.every(row => row.total > 0 && row.missing === row.total))
  const scope = computed(() => JSON.stringify(dynamicLayers.value.map(layer => [layer.id, layer.asset_id, layer.asset_version, layer.campus])))
  let alive = true, metadataVersion = 0, dataVersion = 0
  let metadataAbort: AbortController | undefined, dataAbort: AbortController | undefined
  const query = (layer: MapLayer): TimeLayerQuery => ({ asset_id: layer.asset_id || undefined, version: layer.asset_version || undefined, campus: layer.campus || undefined })
  const message = (cause: unknown) => cause instanceof Error ? cause.message : '时序数据读取失败'
  function paint() {
    for (const layer of dynamicLayers.value) getController()?.showTemporal(layer, frames.value[layer.id] ?? null)
  }
  async function refreshAvailability() {
    const version = ++metadataVersion
    metadataAbort?.abort()
    metadataAbort = new AbortController()
    const layers = [...dynamicLayers.value]
    timesByLayer.value = {}
    metadataErrors.value = {}
    metadataLoading.value = layers.length > 0
    const results = await Promise.allSettled(layers.map(layer => getLayerTimes(layer.id, query(layer), metadataAbort!.signal)))
    if (!alive || version !== metadataVersion) return
    const values: Record<string, string[]> = {}, failures: Record<string, string> = {}
    results.forEach((result, index) => {
      if (result.status === 'fulfilled') values[layers[index]!.id] = result.value
      else failures[layers[index]!.id] = message(result.reason)
    })
    timesByLayer.value = values
    metadataErrors.value = failures
    metadataLoading.value = false
  }
  async function refresh() {
    const version = ++dataVersion
    dataAbort?.abort()
    dataAbort = new AbortController()
    const layers = [...dynamicLayers.value], time = axis.time.value, resolution = axis.resolution.value
    frames.value = {}
    dataErrors.value = {}
    loading.value = !!time && layers.length > 0
    paint()
    if (!loading.value) return
    const results = await Promise.allSettled(layers.map(layer => getTimeSeries({ ...query(layer), layer_id: layer.id, time, resolution }, dataAbort!.signal)))
    if (!alive || version !== dataVersion) return
    const values: Record<string, TimeSeriesRecord> = {}, failures: Record<string, string> = {}
    results.forEach((result, index) => {
      if (result.status === 'fulfilled') values[layers[index]!.id] = result.value
      else failures[layers[index]!.id] = message(result.reason)
    })
    frames.value = values
    dataErrors.value = failures
    loading.value = false
    paint()
  }
  watch(scope, refreshAvailability, { immediate: true })
  watch([scope, axis.time, axis.resolution], refresh, { immediate: true })
  watch(() => dynamicLayers.value.map(layer => [layer.id, layer.status, layer.visible, layer.opacity]), paint)
  onBeforeUnmount(() => { alive = false; ++metadataVersion; ++dataVersion; metadataAbort?.abort(); dataAbort?.abort() })
  return { ...axis, dynamicLayers, times, timesByLayer, frames, metadataLoading, loading, errors, counts, allMissing, refresh, refreshAvailability, paint }
}
