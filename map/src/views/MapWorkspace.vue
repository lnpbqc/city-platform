<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, shallowRef, watch } from 'vue'
import MapCanvas from '../components/map/MapCanvas.vue'
import LayerPanel from '../components/layers/LayerPanel.vue'
import RegionPicker from '../components/map/RegionPicker.vue'
import DisplayRegionPanel from '../components/map/DisplayRegionPanel.vue'
import BookmarkPanel from '../components/map/BookmarkPanel.vue'
import MapToolbar from '../components/map/MapToolbar.vue'
import BasemapSwitcher from '../components/map/BasemapSwitcher.vue'
import { vectorBasemapConfigured } from '../map/basemapSetting'
import WeatherControl from '../components/map/WeatherControl.vue'
import { useWeatherView } from '../composables/useWeatherView'
import { useDisplayRegions } from '../composables/useDisplayRegions'
import type { DisplayRegion } from '../map/displayRegions'
import ObjectPanel from '../components/map/ObjectPanel.vue'
import PoiEditor from '../components/map/PoiEditor.vue'
import TilesCalibrationPanel from '../components/map/TilesCalibrationPanel.vue'
import PoiDetails from '../components/map/PoiDetails.vue'
import NearbyPoiPanel from '../components/map/NearbyPoiPanel.vue'
import { calibrateTiles, getNearbyPois } from '../api/api'
import type { NearbyPoi } from '../layers/types'
import MapLegend from '../components/map/MapLegend.vue'
import MapStatus from '../components/map/MapStatus.vue'
import TimeAxis from '../components/common/TimeAxis.vue'
import WorkspaceFeedback from '../components/common/WorkspaceFeedback.vue'
import { campusRegions, demoRegion, resolveRegionTarget, type RegionTarget } from '../map/regions'
import type { MapController, MapPoint } from '../map/mapController'
import type { TilesCalibrationOffsets } from '../map/tilesCalibrationTypes'
import type { BoundaryState } from '../map/regionBoundary'
import type { LayerRecord, MapLayer, Selection, ObjectRecord } from '../layers/types'
import { editablePoi } from '../map/poi'
import type { SceneRecord } from '../simulation/simulationTypes'
import type { CameraState } from '../map/mapNavigation'
import type { WorkspaceAddress, WorkspaceCapture } from '../router/workspaceState'
import { captureLayers, prepareSceneLayers } from '../simulation/sceneLayers'
import { moveTarget, orderedLayers } from '../layers/layerTree'
import type { CampusKey } from '../map/campuses'
import { readMapView, saveMapView, type NavigationReading } from '../map/mapNavigation'
import type { TemporalContext } from '../temporal/temporalTypes'
import { useObjects } from '../composables/useObjects'
import { useTemporalLayers } from '../composables/useTemporalLayers'

const props = defineProps<{
  active: boolean
  layers: MapLayer[]
  backend: 'loading' | 'online' | 'offline'
  catalogError: string
  mapStateErrors: Record<string, string>
  ordering: boolean
  orderError: string
  recovery?: number
}>()
const emit = defineEmits<{
  campus: [key: CampusKey]
  ready: [controller: MapController]
  add: []
  refresh: []
  toggle: [layer: MapLayer]
  load: [layer: MapLayer]
  remove: [layer: MapLayer]
  opacity: [layer: MapLayer, value: number]
  roadMaxLevel: [layer: MapLayer, value: number]
  retryMapState: [layer: MapLayer]
  move: [layer: MapLayer, direction: number]
  sceneMode: [active: boolean]
  exitScene: []
  poiSaved: [record: LayerRecord, reveal: boolean]
}>()
const sidebar = ref(true)
const timeAxis = ref<InstanceType<typeof TimeAxis> | null>(null)
const timeAxisHeight = ref(0)
watch(timeAxis, (axis, _previous, onCleanup) => {
  timeAxisHeight.value = 0
  if (!axis) return
  const observer = new ResizeObserver(([entry]) => {
    if (entry) timeAxisHeight.value = entry.target.getBoundingClientRect().height
  })
  observer.observe(axis.$el)
  onCleanup(() => observer.disconnect())
}, { flush: 'post' })
const filter = ref<'all' | 'mine'>('all')
const selection = ref<Selection | null>(null)
const objectsOpen = ref(false)
const nearbyOpen = ref(false)
const nearbyItems = ref<NearbyPoi[]>([])
const nearbyLoading = ref(false)
const nearbyError = ref('')
const nearbyUnavailable = ref<string[]>([])
const nearbyPoint = ref<MapPoint | null>(null)
let nearbyVersion = 0
let nearbyAbort: AbortController | undefined
const drawing = ref<'box' | 'polygon' | null>(null)
let controller: MapController | undefined
const basemapController = shallowRef<MapController>()
const vectorAvailable = vectorBasemapConfigured({ VITE_TIANDITU_KEY: import.meta.env?.VITE_TIANDITU_KEY })
const sceneLayers = ref<MapLayer[] | null>(null)
const sceneRecord = ref<SceneRecord | null>(null)
let plainView: { camera: CameraState; time: string; resolution: TemporalContext['resolution'] } | undefined
const viewLayers = computed(() => sceneLayers.value ?? props.layers)
let restoreVersion = 0
let restoreAbort: AbortController | undefined
const displayRegions = useDisplayRegions(() => props.active && props.backend === 'online', () => props.recovery)
const { regions: projectRegions, loading: displayRegionsLoading, loadError: displayRegionsError } = displayRegions
const selectedDisplayId = ref('')
const selectedDisplay = computed(() => projectRegions.value?.find(region => region.id === selectedDisplayId.value))
const weather = useWeatherView(() => controller?.getWeatherPoint() ?? null, () => props.active, () => projectRegions.value)
const { mode: weatherMode, status: weatherStatus, display: shownWeather, region: weatherRegion, reference: weatherReference } = weather
let cameraInMotion = false
function cameraMoving() {
  cameraInMotion = true
  weather.moving()
}
const temporal = useTemporalLayers(() => viewLayers.value, () => controller)
const { time, resolution, rate, playing, maximum, position, times, loading: timeLoading, metadataLoading,
  counts: timeCounts, errors: timeErrors, allMissing, dynamicLayers } = temporal
const temporalContext = computed(() => time.value ? { time: time.value, resolution: resolution.value } : null)
const {
  activeLayerId, items: objectItems, total: objectTotal, page: objectPage, pageSize: objectPageSize,
  loading: objectsLoading, error: objectsError, type: objectType, q: objectQuery,
  selectedId, selected: objectDetail, detailLoading, detailError, areaGeometry, areaIds, areaSummary, selectionProgress,
  refresh: refreshObjects, setLayer: setObjectLayer, setPage: setObjectPage, applyFilters,
  select: selectObject, showPicked, selectArea, clearArea, clearSelection, returnToResults,
} = useObjects(() => viewLayers.value, () => temporalContext.value)
const queryLayers = computed(() => viewLayers.value.filter(layer => layer.id !== 'basemap' && layer.attached))
const drawingScope = computed(() => {
  const layer = queryLayers.value.find(layer => layer.id === activeLayerId.value)
  return layer ? JSON.stringify([layer.id, layer.asset_id, layer.asset_version, layer.campus]) : ''
})
const inspectedSelection = computed<Selection | null>(() => {
  if (!selectedId.value && !selection.value) return null
  const raw = selection.value && (!selectedId.value || selection.value.objectId === selectedId.value) ? selection.value : null
  const layer = queryLayers.value.find(layer => layer.id === (raw?.layerId || activeLayerId.value))
  if (!layer || raw?.asset && (raw.asset.asset_id !== layer.asset_id || raw.asset.version !== layer.asset_version)) return null
  const object = objectDetail.value
  const resourceType = raw?.resourceType ?? layer.type
  return {
    title: object?.name ?? raw?.title ?? (resourceType === '3dtiles' ? '三维对象' : '对象详情'),
    layerName: queryLayers.value.find(layer => layer.id === activeLayerId.value)?.name ?? raw?.layerName ?? '图层未提供',
    properties: raw?.properties ?? object?.properties ?? {},
    resourceType,
    objectId: selectedId.value || raw?.objectId,
    layerId: activeLayerId.value || raw?.layerId,
    asset: object?.asset ?? raw?.asset,
    object: object ?? undefined,
    detailLoading: detailLoading.value,
    detailError: detailError.value,
  }
})
const poiAllowed = computed(() => props.backend === 'online' && !sceneLayers.value)
const calibration = shallowRef<{ layer: MapLayer; id: string; version: string; revision: number } | null>(null)
const calibrationBusy = ref(false)
const calibrationError = ref('')
const calibrationNotice = ref('')
const refreshingCalibration = ref<{ id: string; revision: number } | null>(null)
const blockedTilesAsset = computed(() => calibration.value?.id ?? refreshingCalibration.value?.id)
const emptyOffsets = (): TilesCalibrationOffsets => ({ east: 0, north: 0, up: 0, yaw: 0, pitch: 0, roll: 0 })
const calibrationOffsets = ref<Record<keyof TilesCalibrationOffsets, number | ''>>(emptyOffsets())
const calibrationMatrix = shallowRef<number[] | null>(null)
const calibrationChanged = ref(false)
const calibrationSaveReady = computed(() => !!calibrationMatrix.value && calibrationChanged.value)
const canPickCalibrationPivot = computed(() => !!calibrationMatrix.value && Object.values(calibrationOffsets.value).every(value => value === 0))
const allowCalibration = computed(() => poiAllowed.value && !calibration.value && !calibrationBusy.value && !refreshingCalibration.value)

function previewCalibration() {
  const values = calibrationOffsets.value
  calibrationMatrix.value = Object.values(values).every(value => typeof value === 'number' && Number.isFinite(value))
    ? controller?.updateTilesCalibration(values as TilesCalibrationOffsets) ?? null
    : null
  calibrationChanged.value = !!calibrationMatrix.value && !!controller?.hasTilesCalibrationChanges()
}

function cancelCalibration() {
  if (!calibration.value || calibrationBusy.value) return
  calibration.value = null
  calibrationMatrix.value = null
  controller?.endTilesCalibration()
}

function startCalibration(layer: MapLayer) {
  if (!allowCalibration.value || !controller || !layer.tiles_calibration_allowed || !layer.asset_id || !layer.asset_version) return
  if (is2D.value) { notice.value = '请切换到三维视图后校准模型。'; return }
  if (poiDraft.value) return
  closeObjects()
  calibrationOffsets.value = emptyOffsets()
  calibrationChanged.value = false
  calibrationNotice.value = ''
  calibrationError.value = ''
  const draft = { layer, id: layer.asset_id, version: layer.asset_version, revision: layer.tiles_revision ?? 0 }
  calibration.value = draft
  if (!controller.beginTilesCalibration(layer, {
    moved(east, north) {
      if (calibration.value !== draft || calibrationBusy.value) return
      Object.assign(calibrationOffsets.value, { east, north })
      previewCalibration()
    },
    invalidated() {
      if (calibration.value !== draft) return
      calibration.value = null
      calibrationMatrix.value = null
      if (!calibrationBusy.value) notice.value = '模型已移除或发生变化，校准预览已结束。'
    },
    notice(message) {
      if (calibration.value !== draft) return
      calibrationNotice.value = message
      if (!message && !calibrationBusy.value) previewCalibration()
    },
  })) {
    calibration.value = null
    notice.value = calibrationNotice.value || '模型尚未就绪，暂时无法校准。'
    return
  }
  previewCalibration()
}

function changeCalibration(key: keyof TilesCalibrationOffsets, value: number | '') {
  if (!calibration.value || calibrationBusy.value) return
  calibrationOffsets.value[key] = value
  previewCalibration()
}

function pickCalibrationPivot(kind: 'pivot' | 'ground' = 'pivot') {
  if (calibrationBusy.value || !(kind === 'pivot' ? canPickCalibrationPivot.value : calibrationMatrix.value)) return
  controller?.pickTilesCalibrationPivot(kind)
  previewCalibration()
}

async function publishCalibration(mode: 'update' | 'copy', name = '') {
  const draft = calibration.value
  if (!draft || !calibrationSaveReady.value || calibrationBusy.value) return
  name = name.trim()
  if (mode === 'copy' && !name) return
  calibrationBusy.value = true
  calibrationError.value = ''
  calibrationNotice.value = '正在采样调整后落点的地形…'
  try {
    const placement = await controller?.prepareTilesCalibration()
    if (calibration.value !== draft) return
    if (!placement) throw new Error('校准预览已变化，请重试。')
    calibrationNotice.value = mode === 'copy' ? '正在复制并保存新资产…' : '正在更新原资产…'
    const version = await calibrateTiles(draft.id, {
      ...placement, base_version: draft.version, base_revision: draft.revision,
      ...(mode === 'copy' ? { mode, name } : { mode }),
    })
    if (mode === 'update') refreshingCalibration.value = { id: draft.id, revision: version.revision ?? draft.revision + 1 }
    calibration.value = null
    calibrationMatrix.value = null
    controller?.endTilesCalibration()
    notice.value = mode === 'copy' ? `已另存「${name}」，可在「我的数据」中登记到地图。` : '原资产已更新，正在刷新引用图层。'
    emit('refresh')
  } catch (error) {
    const message = error instanceof Error ? error.message : '无法保存校准，请重试。'
    if (calibration.value === draft) calibrationError.value = message
    else notice.value = message
  } finally {
    calibrationBusy.value = false
    calibrationNotice.value = ''
  }
}

watch(() => props.layers.map(layer => [layer.asset_id, layer.tiles_revision]), () => {
  const published = refreshingCalibration.value
  if (published && !props.layers.some(layer => layer.asset_id === published.id
    && (layer.tiles_revision ?? 0) < published.revision)) refreshingCalibration.value = null
})
const poiLayers = computed(() => viewLayers.value.filter(editablePoi))
const inspectedPoiLayer = computed(() => queryLayers.value.find(layer => layer.id === inspectedSelection.value?.layerId && layer.category === 'POI'))
const inspectedPoiDistance = computed(() => nearbyItems.value.find(item => item.object_id === inspectedSelection.value?.objectId)?.distance_m)
const nearbyScope = computed(() => JSON.stringify(viewLayers.value.filter(layer => layer.category === 'POI' && layer.attached && layer.visible)
  .map(layer => [layer.id, layer.asset_id, layer.asset_version, layer.campus]).sort((a, b) => String(a[0]).localeCompare(String(b[0])))))
function closeNearby() {
  nearbyVersion++
  nearbyAbort?.abort()
  nearbyOpen.value = false
  nearbyLoading.value = false
  nearbyItems.value = []
  nearbyPoint.value = null
}
async function queryNearby(point: MapPoint) {
  if (!props.active || poiDraft.value || drawing.value) return
  const layers = viewLayers.value.filter(layer => layer.attached && layer.visible && layer.category === 'POI')
  if (!layers.length) { closeNearby(); return }
  closeNearby()
  clearObjectSelection()
  nearbyPoint.value = point
  nearbyOpen.value = true
  objectsOpen.value = true
  nearbyLoading.value = true
  nearbyError.value = ''
  nearbyUnavailable.value = layers.filter(layer => !layer.asset_id || !layer.asset_version).map(layer => layer.id)
  nearbyAbort = new AbortController()
  const version = nearbyVersion
  try {
    const result = await getNearbyPois({ longitude: point.longitude, latitude: point.latitude, radius_m: 1000, limit: 20,
      layers: layers.filter(layer => layer.asset_id && layer.asset_version).map(layer => ({ layer_id: layer.id,
        asset_id: layer.asset_id!, version: layer.asset_version!, ...(layer.campus ? { campus: layer.campus } : {}) })) }, nearbyAbort.signal)
    if (version !== nearbyVersion) return
    nearbyItems.value = result.items
    nearbyUnavailable.value = [...new Set([...nearbyUnavailable.value, ...result.unavailable_layers])]
  } catch (cause) {
    if (version === nearbyVersion) nearbyError.value = cause instanceof Error ? cause.message : '附近 POI 查询失败'
  } finally { if (version === nearbyVersion) nearbyLoading.value = false }
}
async function selectNearby(item: NearbyPoi) {
  const version = nearbyVersion
  selection.value = null
  await showPicked(item.object_id, item.layer_id!)
  if (version === nearbyVersion && objectDetail.value?.object_id === item.object_id)
    await controller?.focusObject(item.layer_id!, objectDetail.value)
}
watch(nearbyScope, () => { if (nearbyOpen.value) { closeNearby(); clearObjectSelection(); objectsOpen.value = false } })
const poiSelectionLayer = computed(() => {
  const selection = inspectedSelection.value
  const object = selection?.object
  if (!poiAllowed.value || object?.geometry?.type !== 'Point' || object.feature_index == null) return
  return poiLayers.value.find(layer => layer.id === selection?.layerId &&
    layer.asset_id === object.asset.asset_id && layer.asset_version === object.asset.version)
})
const poiDraft = ref<{ layer?: MapLayer; object?: ObjectRecord; coordinates?: number[] } | null>(null)
const poiPicking = ref(false)
const poiEditor = ref<InstanceType<typeof PoiEditor> | null>(null)

function pickPoiPosition() {
  if (!controller || !poiDraft.value || poiEditor.value?.busy) return
  cancelDraw()
  poiPicking.value = true
  const draft = poiDraft.value
  controller.beginPointPicking(point => {
    if (poiDraft.value !== draft) return
    draft.coordinates = [point.longitude, point.latitude]
    poiPicking.value = false
  })
}
function startPoi(edit = false) {
  if (!controller || !poiAllowed.value || poiDraft.value) return
  if (edit) {
    if (!poiSelectionLayer.value || !inspectedSelection.value?.object) return
    poiDraft.value = { layer: poiSelectionLayer.value, object: inspectedSelection.value.object }
  } else {
    poiDraft.value = {}
    pickPoiPosition()
  }
}
function cancelPoi(force = false) {
  if (!poiDraft.value || (!force && poiEditor.value?.busy)) return
  controller?.cancelPointPicking()
  poiPicking.value = false
  poiDraft.value = null
}
function savePoi(record: LayerRecord) {
  const reveal = !poiDraft.value?.object
  cancelPoi(true)
  clearObjectSelection()
  emit('poiSaved', record, reveal)
}
watch([poiAllowed, () => props.active], ([allowed, active]) => {
  if (!allowed || !active) cancelPoi()
  if (!active) closeNearby()
})
const storedView = (() => { try { return readMapView(window.localStorage) } catch { return null } })()
const selectedRegion = ref<RegionTarget>(storedView?.region ?? demoRegion)
const boundaryEnabled = ref(true)
const boundaryState = ref<BoundaryState>({ status: 'idle' })
const notice = ref('')
const fatal = ref('')
const is2D = ref(storedView?.camera.scene_mode === '2d')
const navigation = ref<NavigationReading | null>(null)
function cancelDraw() { controller?.cancelAreaSelection(); drawing.value = null }
function clearObjectSelection() { selection.value = null; void returnToResults() }
function closeObjects() { cancelDraw(); closeNearby(); clearObjectSelection(); objectsOpen.value = false }
function toggleObjects() { if (objectsOpen.value) closeObjects(); else objectsOpen.value = true }
async function onMapSelection(value: Selection | null) {
  if (value) closeNearby()
  selection.value = value
  if (!value) { void returnToResults(); return }
  objectsOpen.value = true
  if (value.objectId && value.layerId) {
    await showPicked(value.objectId, value.layerId)
  } else {
    clearSelection()
    if (value.layerId) await setObjectLayer(value.layerId)
  }
}
async function onListSelection(item: ObjectRecord) {
  selection.value = null
  await selectObject(item.object_id)
  if (objectDetail.value?.object_id === item.object_id) await controller?.focusObject(activeLayerId.value, objectDetail.value)
}
function changeObjectLayer(id: string) { cancelDraw(); selection.value = null; void setObjectLayer(id) }
function beginDraw(mode: 'box' | 'polygon') {
  if (!controller || !drawingScope.value || poiDraft.value) return
  const scope = drawingScope.value
  clearObjectSelection()
  drawing.value = mode
  controller.beginAreaSelection(mode, geometry => {
    if (drawingScope.value === scope) void selectArea(geometry)
  }, () => { drawing.value = null })
}
watch(drawingScope, () => {
  if (drawing.value) cancelDraw()
  const raw = selection.value
  if (!raw) return
  const layer = queryLayers.value.find(layer => layer.id === raw.layerId)
  if (!layer || layer.id !== activeLayerId.value
    || raw.asset && (raw.asset.asset_id !== layer.asset_id || raw.asset.version !== layer.asset_version)) selection.value = null
})
function applyObjectFilters() { selection.value = null; void applyFilters() }
function clearObjectArea() { cancelDraw(); selection.value = null; void clearArea() }
function zoomMap(direction: number) { cancelDraw(); controller?.zoom(direction) }
function northMap() { cancelDraw(); controller?.north() }
function tiltMap() { cancelDraw(); controller?.tilt() }
function onEscape(event: KeyboardEvent) {
  if (!props.active || event.key !== 'Escape') return
  if (calibration.value) cancelCalibration()
  else if (poiDraft.value) cancelPoi()
  else if (drawing.value) cancelDraw()
}
function onVisibility() { if (document.hidden) temporal.pause() }
onMounted(() => { window.addEventListener('keydown', onEscape); document.addEventListener('visibilitychange', onVisibility) })
onBeforeUnmount(() => { cancelCalibration(); closeNearby(); ++restoreVersion; restoreAbort?.abort(); window.removeEventListener('keydown', onEscape); document.removeEventListener('visibilitychange', onVisibility) })
watch([objectsOpen, activeLayerId, selectedId, areaIds, () => selection.value?.resourceType === '3dtiles', () => props.active], () => {
  // The indexed ID identifies the whole asset; the controller owns the actual map pick.
  if (selection.value?.resourceType === '3dtiles' && objectsOpen.value) return
  if (selection.value && !selection.value.objectId && objectsOpen.value) return
  if (!objectsOpen.value || !props.active) { controller?.highlightObjects(null, []); return }
  const ids = areaGeometry.value ? areaIds.value : selectedId.value ? [selectedId.value] : []
  controller?.highlightObjects(activeLayerId.value || null, ids, selectedId.value || undefined)
})
watch([objectDetail, objectsOpen, () => props.active, () => inspectedPoiLayer.value?.visible], () => {
  controller?.showSelectedPoi?.(objectsOpen.value && props.active && inspectedPoiLayer.value ? inspectedPoiLayer.value.id : null,
    objectsOpen.value && props.active ? objectDetail.value : null)
})
function getController() {
  return controller
}

function onMapReady(value: MapController) {
  controller = value
  basemapController.value = value
  controller.initialize(selectedRegion.value, storedView?.camera)
  weather.resized()
  if (selectedRegion.value.sampleKey) emit('campus', selectedRegion.value.sampleKey)
  emit('ready', value)
  temporal.paint()
}
function onNavigation(value: NavigationReading, settled: boolean) {
  navigation.value = value
  is2D.value = value.camera.scene_mode === '2d'
  if (settled) {
    cameraInMotion = false
    weather.settled()
    try { saveMapView(window.localStorage, { camera: value.camera, region: selectedRegion.value }) } catch { /* Browser storage may be disabled. */ }
  }
}
function selectRegion(region: RegionTarget) {
  cancelDraw()
  closeNearby()
  if (region.sampleKey) emit('campus', region.sampleKey)
  selectedDisplayId.value = ''
  selectedRegion.value = region
  clearObjectSelection()
  is2D.value = false
  controller?.goToRegion(region)
  updateBoundary(true)
}
function captureDisplayView() {
  if (!controller || cameraInMotion) return null
  const extent = controller.getDisplayRegionExtent()
  return extent ? { ...extent, camera: controller.getCamera() } : null
}
function openDisplayRegion(region: DisplayRegion) {
  if (!controller) return false
  cancelDraw()
  controller.cancelPointPicking()
  closeNearby()
  clearObjectSelection()
  selectedDisplayId.value = region.id
  const campus = campusRegions.find(item => item.id === region.id)
  if (campus?.sampleKey) {
    selectedRegion.value = campus
    emit('campus', campus.sampleKey)
  }
  updateBoundary()
  return controller.flyToCamera(region.camera)
}
function selectPoint(point: MapPoint) {
  cancelDraw()
  closeNearby()
  clearObjectSelection()
  selectedDisplayId.value = ''
  is2D.value = false
  controller?.goToPoint(point)
}
function updateBoundary(frame = false) {
  void controller?.setRegionBoundary(
    boundaryEnabled.value && !selectedDisplay.value ? selectedRegion.value.id : null,
    frame,
  )
}
watch(boundaryEnabled, () => updateBoundary())
watch(projectRegions, () => {
  if (selectedDisplayId.value && !selectedDisplay.value) {
    selectedDisplayId.value = ''
    updateBoundary()
  }
})
watch(
  () => props.active,
  async (active) => {
    if (active) {
      await nextTick()
      controller?.resume()
    } else { cancelDraw(); temporal.pause() }
  },
)
function home() {
  if (selectedDisplay.value) { openDisplayRegion(selectedDisplay.value); return }
  cancelDraw()
  closeNearby()
  clearObjectSelection()
  is2D.value = false
  controller?.home()
}
function toggleMode() {
  if (calibrationBusy.value) return
  cancelCalibration()
  cancelDraw()
  is2D.value = !is2D.value
  controller?.setMode(is2D.value)
}
function retryState(id: string) {
  const layer = props.layers.find(item => item.id === id)
  if (layer) emit('retryMapState', layer)
}
function changeLayer(layer: MapLayer, action: 'toggle' | 'load' | 'remove') {
  if (!sceneLayers.value) {
    if (action === 'toggle') emit('toggle', layer)
    else if (action === 'load') emit('load', layer)
    else emit('remove', layer)
    return
  }
  if (action === 'remove') { controller?.remove(layer); layer.map_attached = false }
  else if (action === 'load') {
    layer.map_attached = true
    const visible = layer.visible
    void controller?.load(layer).then(() => { layer.visible = visible; controller?.appearance(layer); temporal.paint() })
  } else { layer.visible = !layer.visible; controller?.appearance(layer) }
}
function setOpacity(layer: MapLayer, value: number) {
  if (!sceneLayers.value) { emit('opacity', layer, value); return }
  layer.opacity = value
  controller?.appearance(layer)
}
function setRoadMaxLevel(layer: MapLayer, value: number) {
  if (!sceneLayers.value) { emit('roadMaxLevel', layer, value); return }
  controller?.setRoadMaxLevel(layer, value)
}
function move(layer: MapLayer, direction: number) {
  if (!sceneLayers.value) { emit('move', layer, direction); return }
  const target = moveTarget(sceneLayers.value, layer, direction)
  if (target === null) return
  const ordered = orderedLayers(sceneLayers.value)
  ordered.splice(ordered.indexOf(layer), 1)
  ordered.splice(target, 0, layer)
  ordered.forEach((item, index) => { item.order = index })
  controller?.syncOrder(sceneLayers.value)
}
function clearScene() {
  ++restoreVersion
  restoreAbort?.abort()
  temporal.pause()
  closeObjects()
  if (sceneLayers.value) for (const layer of sceneLayers.value) controller?.remove(layer)
  sceneLayers.value = null
  sceneRecord.value = null
  emit('sceneMode', false)
  if (plainView) {
    resolution.value = plainView.resolution
    time.value = plainView.time
    controller?.setCamera(plainView.camera)
    plainView = undefined
  }
}
async function restoreWorkspace(scene: SceneRecord | null, address: WorkspaceAddress) {
  const version = ++restoreVersion
  restoreAbort?.abort()
  restoreAbort = new AbortController()
  let region: RegionTarget | undefined
  if (address.region_id) {
    try { region = await resolveRegionTarget(address.region_id, restoreAbort.signal) }
    catch { if (version === restoreVersion) notice.value = '链接中的地区无法读取，已按相机定位。' }
  }
  const prepared = scene ? await prepareSceneLayers(scene.layers, props.layers, restoreAbort.signal) : null
  if (version !== restoreVersion || !controller) return
  cancelCalibration()
  closeObjects()
  temporal.pause()
  if (prepared) {
    if (!sceneLayers.value) plainView = { camera: controller.getCamera(), time: time.value, resolution: resolution.value }
    emit('sceneMode', true)
    for (const layer of viewLayers.value) controller.remove(layer)
    sceneRecord.value = scene
    sceneLayers.value = prepared
    await nextTick()
    await Promise.all(sceneLayers.value.filter(layer => layer.map_attached).map(async layer => {
      const visible = layer.visible
      await controller?.load(layer)
      if (version !== restoreVersion) return
      layer.visible = visible
      controller?.appearance(layer)
    }))
    if (version !== restoreVersion) return
    controller.syncOrder(sceneLayers.value)
  }
  resolution.value = address.resolution
  await nextTick()
  const instant = address.time ?? scene?.current_time
  if (instant) temporal.setTime(instant)
  else if (address.region_id) temporal.seek(0)
  selectedDisplayId.value = ''
  const camera = address.camera ?? scene?.camera
  if (region && camera) {
    selectedRegion.value = region
    if (region.sampleKey) emit('campus', region.sampleKey)
    controller.initialize(region, camera)
    updateBoundary()
  } else if (camera) controller.setCamera(camera)
  temporal.paint()
  controller.resume()
}
function captureWorkspace(): WorkspaceCapture {
  if (!controller) throw new Error('地图尚未就绪')
  const camera = controller.getCamera()
  const current_time = time.value || null
  return { page: 'map', camera, time: current_time, resolution: resolution.value, run_id: null,
    scene: { name: sceneRecord.value?.name ?? '地图画面', camera, current_time, run_id: null,
      layers: captureLayers(viewLayers.value.filter(layer => layer.map_attached ?? layer.attached)), network: null, origin: null, destination: null,
      blocked_edges: [], params: { mode: 'car' }, seed: 0 } }
}
watch(() => props.recovery, async () => {
  await Promise.all(viewLayers.value.filter(layer => layer.attached && layer.status === 'error').map(async layer => {
    const visible = layer.visible
    await controller?.load(layer)
    layer.visible = visible
    controller?.appearance(layer)
  }))
  await temporal.refreshAvailability()
  await temporal.refresh()
  if (objectsOpen.value) {
    await refreshObjects()
    if (selectedId.value) await selectObject(selectedId.value)
  }
})
function cancelRestore() { ++restoreVersion; restoreAbort?.abort() }
function captureView() {
  if (!controller) throw new Error('地图尚未就绪')
  return { camera: controller.getCamera(), region: selectedRegion.value }
}
defineExpose({ captureView, home, clearScene, restoreWorkspace, captureWorkspace, cancelRestore, blockedTilesAsset,
  isReady: () => !!controller, canCapture: () => !!controller && !blockedTilesAsset.value })
</script>

<template>
  <div class="map-workspace" :class="{ 'has-time-axis': timeAxisHeight > 0 }" :style="{ '--time-axis-height': `${timeAxisHeight}px` }" aria-label="地图工作台视图">
    <div class="primary-map"><MapCanvas
      :weather-effect="shownWeather.effect" track-weather
      @camera-move="cameraMoving" @weather-resize="weather.resized"
      @ready="onMapReady"
      @selection="onMapSelection"
      @notice="notice = $event"
      @fatal="fatal = $event"
      @boundary="boundaryState = $event"
      @navigation="onNavigation"
      @ground="queryNearby"
    /></div>
    <WeatherControl class="map-weather" compact v-model:mode="weatherMode"
      :weather="shownWeather" :status="weatherStatus" :region="weatherRegion?.name" :reference="weatherReference" />
    <LayerPanel
      v-model:open="sidebar"
      v-model:filter="filter"
      :layers="viewLayers"
      :backend="backend"
      :catalog-error="catalogError"
      :ordering="ordering"
      :order-error="orderError"
      :allow-calibration="allowCalibration"
      :blocked-tiles-asset="blockedTilesAsset"
      @add="emit('add')"
      @refresh="emit('refresh')"
      @toggle="changeLayer($event, 'toggle')"
      @load="changeLayer($event, 'load')"
      @locate="controller?.locate($event)"
      @remove="changeLayer($event, 'remove')"
      @opacity="setOpacity"
      @road-max-level="setRoadMaxLevel"
      @calibrate="startCalibration"
      @move="move"
    />
    <RegionPicker
      v-model:boundary-enabled="boundaryEnabled"
      :boundary-state="boundaryState"
      :selected="selectedRegion"
      :display-label="selectedDisplay?.name"
      :sidebar="sidebar"
      @select="selectRegion"
      @open="displayRegions.refresh"
      @retry-boundary="updateBoundary()"
    >
      <template #display-regions="{ close }">
        <DisplayRegionPanel :regions="projectRegions ?? []" :loading="displayRegionsLoading" :load-error="displayRegionsError"
          :capture="captureDisplayView" :save="displayRegions.save" :remove="displayRegions.remove"
          @open="openDisplayRegion($event) && close()" @retry="displayRegions.refresh" />
      </template>
      <template #bookmarks>
        <BookmarkPanel
          :selected="selectedRegion"
          :active="active"
          :get-controller="getController"
          @select="selectRegion"
          @point="selectPoint"
          @notice="notice = $event"
        />
      </template>
    </RegionPicker>
    <MapToolbar
      class="browse-tools"
      :is2-d="is2D"
      :heading="navigation?.camera.heading ?? 0"
      :add-poi="poiAllowed"
      @poi="startPoi()"
      @zoom="zoomMap"
      @home="home"
      @mode="toggleMode"
      @tilt="tiltMap"
      @north="northMap"
    />
    <button class="object-trigger panel" :aria-expanded="objectsOpen" aria-label="打开对象查询" @click="toggleObjects">对象查询</button>
    <PoiDetails v-if="objectsOpen && inspectedPoiLayer && !poiDraft"
      :selection="inspectedSelection" :layer="inspectedPoiLayer" :distance="inspectedPoiDistance"
      :edit-poi="!!poiSelectionLayer" @close="closeObjects" @back="clearObjectSelection" @edit-poi="startPoi(true)" />
    <NearbyPoiPanel v-if="objectsOpen && nearbyOpen && !inspectedSelection && !poiDraft"
      :items="nearbyItems" :layers="viewLayers" :loading="nearbyLoading" :error="nearbyError" :unavailable="nearbyUnavailable"
      @select="selectNearby" @close="closeObjects" @retry="nearbyPoint && queryNearby(nearbyPoint)" />
    <ObjectPanel v-if="objectsOpen" v-show="!inspectedPoiLayer && !nearbyOpen"
      :class="{ 'temporal-objects': dynamicLayers.length }"
      :layers="queryLayers" :layer-id="activeLayerId" :items="objectItems" :total="objectTotal" :page="objectPage" :page-size="objectPageSize"
      :loading="objectsLoading" :error="objectsError" v-model:q="objectQuery" v-model:type="objectType"
      :selected-id="selectedId" :selection="inspectedPoiLayer ? null : inspectedSelection" :area="Boolean(areaGeometry)" :area-summary="areaSummary" :drawing="drawing" :progress="selectionProgress"
      :edit-poi="!!poiSelectionLayer && !poiDraft"
      @edit-poi="startPoi(true)"
      @close="closeObjects" @layer="changeObjectLayer" @page="setObjectPage" @select="onListSelection" @apply="applyObjectFilters"
      @draw="beginDraw" @finish="controller?.finishAreaSelection()" @cancel="cancelDraw" @clear-area="clearObjectArea"
      @clear-selection="clearObjectSelection" @retry="refreshObjects"
    />
    <div v-if="poiPicking" class="poi-prompt panel" role="status">
      点击地面选择 POI 位置
      <button @click="cancelPoi()">取消</button>
    </div>
    <PoiEditor v-if="poiDraft" v-show="!poiPicking" ref="poiEditor"
      :layers="poiLayers" :layer="poiDraft.layer" :object="poiDraft.object" :coordinates="poiDraft.coordinates"
      @pick="pickPoiPosition" @cancel="cancelPoi()" @saved="savePoi" @refresh="cancelPoi(); emit('refresh')" />
    <TilesCalibrationPanel v-if="calibration" class="model-calibration" :name="calibration.layer.name" :offsets="calibrationOffsets"
      :busy="calibrationBusy" :ready="!!calibrationMatrix" :save-ready="calibrationSaveReady" :can-pick="canPickCalibrationPivot"
      :message="calibrationNotice" :error="calibrationError"
      @change="changeCalibration" @pick="pickCalibrationPivot" @cancel="cancelCalibration" @save="publishCalibration" />
    <MapLegend v-if="!objectsOpen && !calibration" :layers="viewLayers" class="basemap-legend" />
    <BasemapSwitcher :controller="basemapController" :vector-available="vectorAvailable" />
    <TimeAxis v-if="dynamicLayers.length || metadataLoading" :time="time" v-model:resolution="resolution" v-model:rate="rate"
      ref="timeAxis"
      :playing="playing" :maximum="maximum" :position="position" :times="times" :loading="timeLoading" :metadata-loading="metadataLoading"
      :counts="timeCounts" :errors="timeErrors" :all-missing="allMissing"
      @select="temporal.setTime" @seek="temporal.seek" @step="temporal.step" @play="temporal.play" @pause="temporal.pause"
      @refresh="temporal.refreshAvailability(); temporal.refresh()" />
    <MapStatus :layers="viewLayers" :navigation="navigation" />
    <div v-if="sceneRecord" class="scene-banner panel"><span>{{ sceneRecord.name }} · v{{ sceneRecord.version }} · 快照草稿</span><button @click="emit('exitScene')">返回普通地图</button></div>
    <WorkspaceFeedback
      :notice="notice"
      :fatal="fatal"
      toast=""
      @dismiss="notice = ''"
    />
    <div v-if="!sceneRecord && Object.keys(mapStateErrors).length" class="state-errors panel" role="alert">
      <div v-for="(message, id) in mapStateErrors" :key="id">
        <span>{{ layers.find(layer => layer.id === id)?.name }}：地图状态未保存。{{ message }}</span>
        <button @click="retryState(id)">重试保存</button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.model-calibration { position: absolute; z-index: 6; top: 166px; right: 72px; }
@media (max-width: 760px) { .model-calibration { top: auto; bottom: 60px; right: 12px; } }
.poi-prompt { position: absolute; z-index: 6; bottom: 60px; left: 50%; transform: translateX(-50%); padding: 12px 16px; font-size: 12px; }
.poi-prompt button { color: var(--blue); margin-left: 8px; }
.object-trigger { position: absolute; z-index: 3; right: 78px; top: 84px; padding: 11px 15px; font-size: 11px; color: var(--blue); }
.scene-banner { position: absolute; z-index: 4; top: 190px; right: 24px; padding: 10px 14px; display: flex; gap: 12px; font-size: 11px; }
.scene-banner button { color: var(--blue); }
.primary-map { position: absolute; inset: 0; }
.map-weather { position: absolute; z-index: 2; right: 185px; top: 84px; }
.basemap-legend { bottom: calc(var(--basemap-bottom) + 118px); }
.temporal-objects { max-height: max(100px, calc(100svh - var(--time-axis-height) - 192px)); }
.map-workspace {
  --basemap-bottom: 60px;
  position: absolute;
  inset: 0;
}
.map-workspace.has-time-axis { --basemap-bottom: calc(var(--time-axis-height) + 64px); }
.state-errors {
  position: absolute;
  z-index: 6;
  left: 50%;
  bottom: 48px;
  transform: translateX(-50%);
  max-width: min(560px, calc(100% - 32px));
  padding: 12px 16px;
  color: #a55145;
  font-size: 12px;
}
.state-errors > div { display: flex; align-items: center; gap: 12px; }
.state-errors button { flex-shrink: 0; color: var(--blue); }
@media (max-width: 760px) {
  .map-weather { right: 12px; top: 76px; z-index: 5; }
  .browse-tools { top: 124px; }
}
@media (max-width: 600px) {
  .map-workspace:has(> .time-axis) :deep(.layer-panel) {
    max-height: max(100px, calc(100svh - var(--time-axis-height) - 130px));
  }
}
</style>
