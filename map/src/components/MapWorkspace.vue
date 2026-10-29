<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import MapCanvas from './MapCanvas.vue'
import LayerPanel from './LayerPanel.vue'
import RegionPicker from './RegionPicker.vue'
import BookmarkPanel from './BookmarkPanel.vue'
import MapToolbar from './MapToolbar.vue'
import ObjectPanel from './ObjectPanel.vue'
import MapLegend from './MapLegend.vue'
import MapStatus from './MapStatus.vue'
import TimeAxis from './TimeAxis.vue'
import ComparisonView from './ComparisonView.vue'
import WorkspaceFeedback from './WorkspaceFeedback.vue'
import { demoRegion, type RegionTarget } from '../regions'
import type { MapController, MapPoint } from '../mapController'
import type { BoundaryState } from '../regionBoundary'
import type { MapLayer, Selection, ObjectRecord } from '../types'
import type { SceneRecord } from '../simulationTypes'
import type { CameraState } from '../mapNavigation'
import type { WorkspaceAddress, WorkspaceCapture } from '../workspaceState'
import { captureLayers, prepareSceneLayers } from '../sceneLayers'
import { moveTarget, orderedLayers } from '../layerTree'
import type { CampusKey } from '../campuses'
import { readMapView, saveMapView, type NavigationReading } from '../mapNavigation'
import type { TemporalContext } from '../temporalTypes'
import { linkedCameras } from '../linkedCameras'
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
  retryMapState: [layer: MapLayer]
  move: [layer: MapLayer, direction: number]
  sceneMode: [active: boolean]
  exitScene: []
  changed: []
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
const drawing = ref<'box' | 'polygon' | null>(null)
let controller: MapController | undefined
const sceneLayers = ref<MapLayer[] | null>(null)
const sceneRecord = ref<SceneRecord | null>(null)
let plainView: { camera: CameraState; time: string; resolution: TemporalContext['resolution'] } | undefined
const viewLayers = computed(() => sceneLayers.value ?? props.layers)
let restoreVersion = 0
let restoreAbort: AbortController | undefined
let comparisonController: MapController | undefined
const comparisonOpen = ref(false)
const comparisonTime = ref<TemporalContext>({ time: '', resolution: 'hour' })
const synchronizeCamera = linkedCameras(() => controller, () => comparisonController)
const temporal = useTemporalLayers(() => viewLayers.value, () => controller)
const { time, resolution, rate, playing, maximum, position, times, loading: timeLoading, metadataLoading,
  counts: timeCounts, errors: timeErrors, allMissing, dynamicLayers } = temporal
const temporalContext = computed(() => time.value ? { time: time.value, resolution: resolution.value } : null)
const {
  activeLayerId, items: objectItems, total: objectTotal, page: objectPage, pageSize: objectPageSize,
  loading: objectsLoading, error: objectsError, type: objectType, q: objectQuery,
  selectedId, selected: objectDetail, detailLoading, detailError, areaGeometry, areaIds, selectionProgress,
  refresh: refreshObjects, setLayer: setObjectLayer, setPage: setObjectPage, applyFilters,
  select: selectObject, showPicked, selectArea, clearArea, clearSelection,
} = useObjects(() => viewLayers.value, () => temporalContext.value)
const queryLayers = computed(() => viewLayers.value.filter(layer => layer.id !== 'basemap' && layer.attached))
const drawingScope = computed(() => {
  const layer = queryLayers.value.find(layer => layer.id === activeLayerId.value)
  return layer ? JSON.stringify([layer.id, layer.asset_id, layer.asset_version, layer.campus]) : ''
})
const inspectedSelection = computed<Selection | null>(() => {
  if (!selectedId.value && !selection.value) return null
  const raw = selection.value && (!selectedId.value || selection.value.objectId === selectedId.value) ? selection.value : null
  const object = objectDetail.value
  return {
    title: object?.name ?? raw?.title ?? '对象详情',
    layerName: queryLayers.value.find(layer => layer.id === activeLayerId.value)?.name ?? raw?.layerName ?? '图层未提供',
    properties: raw?.properties ?? object?.properties ?? {},
    resourceType: raw?.resourceType ?? queryLayers.value.find(layer => layer.id === activeLayerId.value)?.type,
    objectId: selectedId.value || raw?.objectId,
    layerId: activeLayerId.value || raw?.layerId,
    asset: object?.asset ?? raw?.asset,
    object: object ?? undefined,
    detailLoading: detailLoading.value,
    detailError: detailError.value,
  }
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
function clearObjectSelection() { selection.value = null; clearSelection() }
function closeObjects() { cancelDraw(); clearObjectSelection(); objectsOpen.value = false }
function toggleObjects() { if (objectsOpen.value) closeObjects(); else objectsOpen.value = true }
async function onMapSelection(value: Selection | null) {
  selection.value = value
  if (!value) { clearSelection(); return }
  objectsOpen.value = true
  if (value.objectId && value.layerId) {
    const page = controller?.objectPage(value.objectId, value.layerId, objectPageSize.value) ?? 1
    await showPicked(value.objectId, value.layerId, page)
  } else {
    if (value.layerId) await setObjectLayer(value.layerId)
    clearSelection()
  }
}
async function onListSelection(item: ObjectRecord) {
  selection.value = null
  await selectObject(item.object_id)
  if (objectDetail.value?.object_id === item.object_id) await controller?.focusObject(activeLayerId.value, objectDetail.value)
}
function changeObjectLayer(id: string) { cancelDraw(); selection.value = null; void setObjectLayer(id) }
function beginDraw(mode: 'box' | 'polygon') {
  if (!controller || !drawingScope.value) return
  const scope = drawingScope.value
  clearObjectSelection()
  drawing.value = mode
  controller.beginAreaSelection(mode, geometry => {
    if (drawingScope.value === scope) void selectArea(geometry)
  }, () => { drawing.value = null })
}
watch(drawingScope, () => { if (drawing.value) cancelDraw() })
function applyObjectFilters() { selection.value = null; void applyFilters() }
function clearObjectArea() { cancelDraw(); selection.value = null; void clearArea() }
function zoomMap(direction: number) { cancelDraw(); controller?.zoom(direction) }
function northMap() { cancelDraw(); controller?.north() }
function tiltMap() { cancelDraw(); controller?.tilt() }
function onEscape(event: KeyboardEvent) { if (event.key === 'Escape' && drawing.value) cancelDraw() }
function onVisibility() { if (document.hidden) temporal.pause() }
onMounted(() => { window.addEventListener('keydown', onEscape); document.addEventListener('visibilitychange', onVisibility) })
onBeforeUnmount(() => { ++restoreVersion; restoreAbort?.abort(); window.removeEventListener('keydown', onEscape); document.removeEventListener('visibilitychange', onVisibility) })
watch([objectsOpen, activeLayerId, selectedId, areaIds, () => props.active], () => {
  if (selection.value && !selection.value.objectId && objectsOpen.value) return
  if (!objectsOpen.value || !props.active) { controller?.highlightObjects(null, []); return }
  const ids = areaGeometry.value ? areaIds.value : selectedId.value ? [selectedId.value] : []
  controller?.highlightObjects(activeLayerId.value || null, ids, selectedId.value || undefined)
})
function getController() {
  return controller
}

function onMapReady(value: MapController) {
  controller = value
  controller.initialize(selectedRegion.value, storedView?.camera)
  if (selectedRegion.value.sampleKey) emit('campus', selectedRegion.value.sampleKey)
  emit('ready', value)
  temporal.paint()
}
function onNavigation(value: NavigationReading, settled: boolean) {
  navigation.value = value
  is2D.value = value.camera.scene_mode === '2d'
  if (comparisonOpen.value) synchronizeCamera('left', value.camera)
  if (settled) {
    try { saveMapView(window.localStorage, { camera: value.camera, region: selectedRegion.value }) } catch { /* Browser storage may be disabled. */ }
    emit('changed')
  }
}
function comparisonReady(value: MapController) { comparisonController = value; if (controller) synchronizeCamera('left', controller.getCamera()) }
function toggleComparison() {
  if (!comparisonOpen.value && (!navigation.value || is2D.value !== (navigation.value.camera.scene_mode === '2d'))) return
  temporal.pause()
  if (comparisonOpen.value) { comparisonOpen.value = false; comparisonController = undefined }
  else {
    closeObjects()
    comparisonTime.value = { time: times.value.at(-1) ?? time.value, resolution: resolution.value }
    comparisonOpen.value = true
  }
  void nextTick(() => controller?.resume())
}
function selectRegion(region: RegionTarget) {
  cancelDraw()
  if (region.sampleKey) emit('campus', region.sampleKey)
  selectedRegion.value = region
  clearObjectSelection()
  is2D.value = false
  controller?.goToRegion(region)
  updateBoundary(true)
}
function selectPoint(point: MapPoint) {
  cancelDraw()
  clearObjectSelection()
  is2D.value = false
  controller?.goToPoint(point)
}
function updateBoundary(frame = false) {
  void controller?.setRegionBoundary(
    boundaryEnabled.value ? selectedRegion.value.id : null,
    frame,
  )
}
watch(boundaryEnabled, () => updateBoundary())
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
  cancelDraw()
  clearObjectSelection()
  is2D.value = false
  controller?.home()
}
function toggleMode() {
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
  comparisonOpen.value = false
  comparisonController = undefined
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
  const prepared = scene ? await prepareSceneLayers(scene.layers, props.layers, restoreAbort.signal) : null
  if (version !== restoreVersion || !controller) return
  closeObjects()
  temporal.pause()
  comparisonOpen.value = false
  comparisonController = undefined
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
  const camera = address.camera ?? scene?.camera
  if (camera) controller.setCamera(camera)
  temporal.paint()
  if (address.comparison) {
    comparisonTime.value = { ...address.comparison }
    comparisonOpen.value = true
    await nextTick()
  }
  controller.resume()
}
function captureWorkspace(): WorkspaceCapture {
  if (!controller) throw new Error('地图尚未就绪')
  const camera = controller.getCamera()
  const current_time = time.value || null
  return { page: 'map', camera, time: current_time, resolution: resolution.value, run_id: null,
    comparison: comparisonOpen.value ? { ...comparisonTime.value } : null,
    scene: { name: sceneRecord.value?.name ?? '地图画面', camera, current_time, run_id: null,
      layers: captureLayers(viewLayers.value.filter(layer => layer.map_attached ?? layer.attached)), network: null, origin: null, destination: null,
      blocked_edges: [], params: { mode: 'car' }, seed: 0 } }
}
watch([time, resolution, comparisonOpen, () => JSON.stringify(comparisonTime.value), () => JSON.stringify(captureLayers(viewLayers.value.filter(layer => layer.map_attached ?? layer.attached)))], () => emit('changed'))
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
defineExpose({ home, clearScene, restoreWorkspace, captureWorkspace, cancelRestore, isReady: () => !!controller })
</script>

<template>
  <div class="map-workspace" :style="{ '--time-axis-height': `${timeAxisHeight}px` }" aria-label="地图工作台视图">
    <div class="primary-map" :class="{ split: comparisonOpen }"><MapCanvas
      @ready="onMapReady"
      @selection="onMapSelection"
      @notice="notice = $event"
      @fatal="fatal = $event"
      @boundary="boundaryState = $event"
      @navigation="onNavigation"
    /></div>
    <ComparisonView v-if="comparisonOpen && navigation" :active="active" :layers="viewLayers" :camera="navigation.camera" :initial-time="comparisonTime" :recovery="recovery"
      @ready="comparisonReady" @navigation="synchronizeCamera('right', $event.camera)" @time="comparisonTime = $event" />
    <LayerPanel v-if="!comparisonOpen"
      v-model:open="sidebar"
      v-model:filter="filter"
      :layers="viewLayers"
      :backend="backend"
      :catalog-error="catalogError"
      :ordering="ordering"
      :order-error="orderError"
      @add="emit('add')"
      @refresh="emit('refresh')"
      @toggle="changeLayer($event, 'toggle')"
      @load="changeLayer($event, 'load')"
      @locate="controller?.locate($event)"
      @remove="changeLayer($event, 'remove')"
      @opacity="setOpacity"
      @move="move"
    />
    <RegionPicker v-if="!comparisonOpen"
      v-model:boundary-enabled="boundaryEnabled"
      :boundary-state="boundaryState"
      :selected="selectedRegion"
      :sidebar="sidebar"
      @select="selectRegion"
      @retry-boundary="updateBoundary()"
    >
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
    <MapToolbar v-if="!comparisonOpen"
      :is2-d="is2D"
      :heading="navigation?.camera.heading ?? 0"
      @zoom="zoomMap"
      @home="home"
      @mode="toggleMode"
      @tilt="tiltMap"
      @north="northMap"
    />
    <button v-if="!comparisonOpen" class="object-trigger panel" :aria-expanded="objectsOpen" aria-label="打开对象查询" @click="toggleObjects">对象查询</button>
    <button class="comparison-trigger panel" :class="{ comparing: comparisonOpen }" :disabled="!comparisonOpen && (!dynamicLayers.length || !navigation || is2D !== (navigation.camera.scene_mode === '2d'))" :aria-pressed="comparisonOpen" @click="toggleComparison">{{ comparisonOpen ? '退出时间对比' : '双视图时间对比' }}</button>
    <span v-if="comparisonOpen" class="comparison-heading panel">左 / 右 · 同视角，时间独立</span>
    <ObjectPanel v-if="objectsOpen"
      :class="{ 'temporal-objects': dynamicLayers.length }"
      :layers="queryLayers" :layer-id="activeLayerId" :items="objectItems" :total="objectTotal" :page="objectPage" :page-size="objectPageSize"
      :loading="objectsLoading" :error="objectsError" v-model:q="objectQuery" v-model:type="objectType"
      :selected-id="selectedId" :selection="inspectedSelection" :area="Boolean(areaGeometry)" :drawing="drawing" :progress="selectionProgress"
      @close="closeObjects" @layer="changeObjectLayer" @page="setObjectPage" @select="onListSelection" @apply="applyObjectFilters"
      @draw="beginDraw" @finish="controller?.finishAreaSelection()" @cancel="cancelDraw" @clear-area="clearObjectArea"
      @clear-selection="clearObjectSelection" @retry="refreshObjects"
    />
    <MapLegend v-if="!objectsOpen && !comparisonOpen" :layers="viewLayers" :class="{ 'temporal-legend': dynamicLayers.length }" />
    <TimeAxis v-if="dynamicLayers.length || metadataLoading" :time="time" v-model:resolution="resolution" v-model:rate="rate"
      ref="timeAxis"
      :class="{ 'comparison-time-left': comparisonOpen }" :label="comparisonOpen ? '左侧时间轴' : undefined"
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
.object-trigger { position: absolute; z-index: 3; right: 78px; top: 84px; padding: 11px 15px; font-size: 11px; color: var(--blue); }
.scene-banner { position: absolute; z-index: 4; top: 190px; right: 24px; padding: 10px 14px; display: flex; gap: 12px; font-size: 11px; }
.scene-banner button { color: var(--blue); }
.primary-map { position: absolute; inset: 0; }
.primary-map.split { right: 50%; }
.comparison-trigger { position: absolute; z-index: 3; right: 78px; top: 132px; padding: 11px 15px; font-size: 11px; color: var(--blue); }
.comparison-trigger.comparing { top: 84px; right: 24px; }
.comparison-trigger:disabled { opacity: .5; }
.comparison-heading { position: absolute; left: 24px; top: 84px; padding: 11px 15px; font-size: 11px; color: #65788e; }
.comparison-time-left { left: 24px; right: calc(50% + 12px); }
.temporal-legend { bottom: calc(var(--time-axis-height) + 58px); }
.temporal-objects { max-height: max(100px, calc(100svh - var(--time-axis-height) - 192px)); }
.map-workspace {
  position: absolute;
  inset: 0;
}
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
@media (max-width: 600px) {
  .map-workspace:has(> .time-axis) :deep(.layer-panel) {
    max-height: max(100px, calc(100svh - var(--time-axis-height) - 130px));
  }
}
</style>
