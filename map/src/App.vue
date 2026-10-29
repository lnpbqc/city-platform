<script setup lang="ts">
import {
  computed,
  defineAsyncComponent,
  nextTick,
  onBeforeUnmount,
  ref,
  watch,
} from 'vue'
import WorkspaceHeader from './components/WorkspaceHeader.vue'
import DataManagerView from './components/DataManagerView.vue'
import LayerDialog from './components/LayerDialog.vue'
import LayerChooser from './components/LayerChooser.vue'
import HelpPanel from './components/HelpPanel.vue'
import WorkspaceFeedback from './components/WorkspaceFeedback.vue'
import WorkspaceBookmarks from './components/WorkspaceBookmarks.vue'
import RequestDiagnostics from './components/RequestDiagnostics.vue'
import { useConnection } from './composables/useConnection'
import { getScene, saveScene } from './api'
import type { SceneRecord } from './simulationTypes'
import { readWorkspaceAddress, workspaceError, workspaceParams, workspaceURL, type WorkspaceAddress, type WorkspaceCapture, type WorkspaceState } from './workspaceState'
import { useLayerCatalog } from './composables/useLayerCatalog'
import { readWorkspacePage, type WorkspacePage } from './workspaceRoute'
import type { MapController } from './mapController'
import type { AssetRecord, LayerInput, LayerRecord, MapLayer } from './types'
import { defaultCampus, type CampusKey } from './campuses'

const MapWorkspace = defineAsyncComponent(
  () => import('./components/MapWorkspace.vue'),
)
const SimulationWorkspace = defineAsyncComponent(() => import('./components/SimulationWorkspace.vue'))
const page = ref(readWorkspacePage(window.location.hash))
const mapVisited = ref(page.value === 'map')
const simulationVisited = ref(page.value === 'simulation')
interface WorkspaceView {
  captureWorkspace: () => WorkspaceCapture
  restoreWorkspace: (scene: SceneRecord | null, address: WorkspaceAddress) => Promise<void>
  isReady: () => boolean
  canCapture?: () => boolean
  cancelRestore: () => void
}
const mapView = ref<WorkspaceView & { home: () => void; clearScene: () => void }>()
const simulationView = ref<WorkspaceView>()
const readyRevision = ref(0)
const recovery = ref(0)
const statsRevision = ref(0)
const mapSceneActive = ref(false)
const restoring = ref(false)
const restoreError = ref('')
let addressBlocked = false
const sharedState = ref<WorkspaceState | null>(null)
let restoreVersion = 0
let restoreAbort: AbortController | undefined
let addressTimer: ReturnType<typeof setTimeout> | undefined
let capturePromise: Promise<WorkspaceState> | undefined
let snapshotSignature = ''
const showDialog = ref(false)
const showChooser = ref(false)
const showHelp = ref(false)
const editing = ref<LayerRecord>()
const initial = ref<LayerInput>()
const toast = ref('')
const sampleCampus = ref<CampusKey>(defaultCampus.key)
let controller: MapController | undefined
let pendingJoin: string | undefined
let toastTimer: ReturnType<typeof setTimeout> | undefined
function notify(message: string) {
  toast.value = message
  clearTimeout(toastTimer)
  toastTimer = setTimeout(() => {
    toast.value = ''
  }, 5000)
}
const {
  layers,
  backend,
  catalogError,
  deleting,
  revision,
  switchCampus,
  refreshCatalog,
  saved,
  removeRecord,
  toggleVisibility,
  mapStateErrors,
  controllerReady,
  joinLayer,
  removeFromMap,
  changeOpacity,
  retryMapState,
  ordering,
  orderError,
  moveLayer,
} = useLayerCatalog(() => mapSceneActive.value ? undefined : controller, notify)
const { status: connectionStatus, lastError: requestError, retryIn, retry: retryConnection } = useConnection(() => {
  recovery.value++
  void refreshCatalog()
})
const registeredCount = computed(
  () => layers.value.filter((layer) => !layer.builtin).length,
)

function synchronizePage() {
  const next = readWorkspacePage(window.location.hash)
  if (page.value === next) return
  page.value = next
  if (page.value === 'map') mapVisited.value = true
  if (page.value === 'simulation') simulationVisited.value = true
  showChooser.value = false
  showHelp.value = false
  showDialog.value = false
}
function navigate(value: WorkspacePage) {
  cancelAddressRestore()
  addressBlocked = false
  restoreError.value = ''
  sharedState.value = null
  snapshotSignature = ''
  const url = new URL(window.location.href)
  for (const key of workspaceParams) url.searchParams.delete(key)
  url.hash = `/${value}`
  window.history.pushState(null, '', url)
  synchronizePage()
}
function addressChanged() {
  cancelAddressRestore()
  addressBlocked = false
  try {
    const address = readWorkspaceAddress(new URL(window.location.href))
    if (address) void restoreAddress(address)
    else {
      sharedState.value = null
      synchronizePage()
      if (page.value === 'map' && mapSceneActive.value) void leaveMapScene()
    }
  } catch (cause) { addressBlocked = true; restoreError.value = cause instanceof Error ? cause.message : '复现链接读取失败' }
}
window.addEventListener('hashchange', addressChanged)
window.addEventListener('popstate', addressChanged)
if (!['#/map', '#/data', '#/simulation'].includes(window.location.hash))
  window.history.replaceState(null, '', '#/map')

function addDialog(record?: LayerRecord) {
  editing.value = record
  initial.value = undefined
  showDialog.value = true
}
function registerAsset(asset: AssetRecord) {
  if (!asset.entry_url || (asset.type !== 'geojson' && asset.type !== '3dtiles')) return
  editing.value = undefined
  initial.value = {
    name:
      asset.name || asset.original_name?.replace(/\.(zip|geojson|json)$/i, '') ||
      `历史数据 ${asset.id.slice(0, 8)}`,
    category: '自定义图层',
    type: asset.type,
    url: asset.entry_url,
    source: asset.source || (asset.source_kind === 'external' ? '外部资产' : '本地文件资产'),
  }
  showDialog.value = true
}
function onSaved(record: LayerRecord) {
  showDialog.value = false
  saved(record)
  void refreshCatalog()
}
function changeCampus(key: CampusKey) {
  sampleCampus.value = key
  void switchCampus(key)
}
function onMapReady(value: MapController) {
  controller = value
  readyRevision.value++
  void controllerReady()
  const layer = layers.value.find((item) => item.id === pendingJoin)
  pendingJoin = undefined
  if (layer) void loadAndLocate(layer)
}
async function loadAndLocate(layer: MapLayer) {
  if (mapSceneActive.value) await leaveMapScene()
  await nextTick()
  if (!controller) return
  controller.resume()
  await joinLayer(layer)
  if (layer.status === 'ready' || layer.status === 'loading') await controller.locate(layer)
}
function join(layer: MapLayer) {
  showChooser.value = false
  navigate('map')
  if (!controller) pendingJoin = layer.id
  else void loadAndLocate(layer)
}
function createData() {
  navigate('data')
  addDialog()
}
function brandHome() {
  navigate('map')
  mapView.value?.home()
}
function cancelAddressRestore() {
  ++restoreVersion
  restoreAbort?.abort()
  mapView.value?.cancelRestore()
  simulationView.value?.cancelRestore()
  restoring.value = false
  clearTimeout(addressTimer)
}
function activeView() { return page.value === 'map' ? mapView.value : page.value === 'simulation' ? simulationView.value : undefined }
const canCapture = computed(() => {
  void readyRevision.value
  const view = activeView()
  return !restoring.value && backend.value === 'online' && !!view && (view.canCapture?.() ?? view.isReady())
})
function waitForWorkspace(signal: AbortSignal): Promise<WorkspaceView> {
  return new Promise((resolve, reject) => {
    const stop = watch([page, backend, mapView, simulationView, readyRevision], check)
    const timeout = setTimeout(() => finish(undefined, workspaceError('工作区尚未就绪，请恢复服务后重新打开链接')), 20000)
    const aborted = () => finish(undefined, new DOMException('恢复已取消', 'AbortError'))
    function finish(view?: WorkspaceView, cause?: unknown) {
      stop(); clearTimeout(timeout); signal.removeEventListener('abort', aborted)
      if (view) resolve(view); else reject(cause)
    }
    function check() { const view = activeView(); if (backend.value !== 'loading' && view?.isReady()) finish(view) }
    signal.addEventListener('abort', aborted, { once: true })
    if (signal.aborted) aborted(); else check()
  })
}
async function restoreAddress(address: WorkspaceAddress) {
  cancelAddressRestore()
  const version = restoreVersion
  restoreAbort = new AbortController()
  const signal = restoreAbort.signal
  restoring.value = true
  addressBlocked = false
  restoreError.value = ''
  page.value = address.page
  if (address.page === 'map') mapVisited.value = true
  else simulationVisited.value = true
  try {
    const scene = address.scene_id ? await getScene(address.scene_id, signal, address.scene_version) : null
    if (scene && address.run_id && scene.run_id !== address.run_id) throw workspaceError('链接的运行 ID 与场景保存的运行不一致')
    if (signal.aborted || version !== restoreVersion) return
    const view = await waitForWorkspace(signal)
    if (address.page === 'map' && !scene && mapSceneActive.value) {
      mapView.value?.clearScene()
      await controllerReady()
    }
    await view.restoreWorkspace(scene, address)
    if (signal.aborted || version !== restoreVersion) return
    if (scene) {
      const capture = view.captureWorkspace()
      const { scene: input, ...state } = capture
      sharedState.value = { ...state, scene_id: scene.id, scene_version: scene.version }
      snapshotSignature = signature(input)
      window.history.replaceState(null, '', workspaceURL(sharedState.value))
    }
  } catch (cause) {
    if (version === restoreVersion && !(cause instanceof Error && cause.name === 'AbortError')) { addressBlocked = true; restoreError.value = cause instanceof Error ? cause.message : '完整画面恢复失败' }
  } finally { if (version === restoreVersion) restoring.value = false }
}
function signature(scene: WorkspaceCapture['scene']) {
  const { camera: _camera, current_time: _time, ...rest } = scene
  return JSON.stringify(rest)
}
async function createSnapshot(): Promise<WorkspaceState> {
  if (capturePromise) await capturePromise
  const view = activeView()
  if (!view?.isReady() || restoring.value || page.value === 'data') throw workspaceError('当前工作区尚未就绪')
  const capture = view.captureWorkspace()
  const version = restoreVersion
  const requestedPage = page.value
  capturePromise = (async () => {
    const { scene, ...state } = capture
    const key = signature(scene)
    const saved = sharedState.value?.page === capture.page && snapshotSignature === key
      ? { id: sharedState.value.scene_id, version: sharedState.value.scene_version }
      : await saveScene(scene)
    const complete = { ...state, scene_id: saved.id, scene_version: saved.version }
    if (version === restoreVersion && page.value === requestedPage) {
      sharedState.value = complete
      snapshotSignature = key
      addressBlocked = false
      restoreError.value = ''
      window.history.replaceState(null, '', workspaceURL(complete))
    }
    return complete
  })()
  try { return await capturePromise } finally { capturePromise = undefined }
}
function viewChanged() {
  if (restoring.value || addressBlocked || !canCapture.value || page.value === 'data') return
  clearTimeout(addressTimer)
  addressTimer = setTimeout(() => { void createSnapshot().catch(cause => { restoreError.value = cause instanceof Error ? cause.message : '复现链接更新失败' }) }, 350)
}
async function openBookmark(state: WorkspaceState) {
  window.history.pushState(null, '', workspaceURL(state))
  await restoreAddress({ ...state, run_id: state.run_id ?? undefined, time: state.time ?? undefined })
}
async function leaveMapScene() {
  cancelAddressRestore()
  mapView.value?.clearScene()
  addressBlocked = false
  restoreError.value = ''
  sharedState.value = null
  snapshotSignature = ''
  const url = new URL(window.location.href)
  for (const key of workspaceParams) url.searchParams.delete(key)
  window.history.replaceState(null, '', url)
  await controllerReady()
}
onBeforeUnmount(() => {
  cancelAddressRestore()
  window.removeEventListener('hashchange', addressChanged)
  window.removeEventListener('popstate', addressChanged)
  clearTimeout(toastTimer)
  controller = undefined
})
addressChanged()
</script>

<template>
  <main class="workspace">
    <MapWorkspace
      v-if="mapVisited"
      v-show="page === 'map'"
      ref="mapView"
      :active="page === 'map'"
      :layers="layers"
      :backend="backend"
      :catalog-error="catalogError"
      :map-state-errors="mapStateErrors"
      :ordering="ordering"
      :order-error="orderError"
      :recovery="recovery"
      @ready="onMapReady"
      @add="showChooser = true"
      @refresh="refreshCatalog"
      @toggle="toggleVisibility"
      @load="joinLayer"
      @remove="removeFromMap"
      @opacity="changeOpacity"
      @retry-map-state="retryMapState"
      @move="moveLayer"
      @campus="changeCampus"
      @scene-mode="mapSceneActive = $event"
      @exit-scene="leaveMapScene"
      @changed="viewChanged"
    />
    <DataManagerView
      v-show="page === 'data'"
      :layers="layers"
      :backend="backend"
      :catalog-error="catalogError"
      :deleting="deleting"
      :revision="revision"
      :active="page === 'data'"
      :recovery="recovery + statsRevision"
      @add="addDialog()"
      @edit="addDialog"
      @register-asset="registerAsset"
      @join="join"
      @delete-record="removeRecord"
      @refresh="refreshCatalog"
    />
    <SimulationWorkspace v-if="simulationVisited" v-show="page === 'simulation'" ref="simulationView"
      :active="page === 'simulation'" :layers="layers" :backend="backend" :recovery="recovery" @ready="readyRevision++" @changed="viewChanged" @run-changed="statsRevision++" />
    <WorkspaceHeader
      :page="page"
      :count="registeredCount"
      @navigate="navigate"
      @home="brandHome"
      @help="showHelp = !showHelp"
    ><template #tools><WorkspaceBookmarks :enabled="canCapture" :capture="createSnapshot" @open="openBookmark" /><RequestDiagnostics :error="requestError" /></template></WorkspaceHeader>
    <div v-if="connectionStatus === 'retrying'" class="connection-banner panel" role="status" aria-label="服务连接状态"><span>连接中断，正在重试<span v-if="retryIn"> · {{ retryIn }} 秒后再次检查</span></span><button @click="retryConnection">立即重连</button></div>
    <div v-if="restoring || restoreError" class="restore-feedback panel" :role="restoreError ? 'alert' : 'status'"><span>{{ restoring ? '正在恢复完整画面…' : restoreError }}</span><button v-if="restoreError" @click="restoreError = ''">关闭</button></div>
    <div v-if="restoring" class="restore-shield" aria-hidden="true" />
    <WorkspaceFeedback notice="" fatal="" :toast="toast" />
    <HelpPanel :open="showHelp" @close="showHelp = false" />
    <LayerChooser
      v-if="showChooser"
      :layers="layers"
      @close="showChooser = false"
      @join="join"
      @manage="createData"
    />
    <LayerDialog
      v-if="showDialog"
      :editing="editing"
      :initial="initial"
      @close="showDialog = false"
      @saved="onSaved"
    />
  </main>
</template>

<style scoped>
.workspace {
  height: 100svh;
  width: 100%;
  overflow: hidden;
  position: relative;
}
.restore-feedback { position: absolute; z-index: 7; top: 74px; left: 50%; transform: translateX(-50%); padding: 12px 18px; display: flex; gap: 16px; max-width: calc(100% - 32px); font-size: 12px; overflow-wrap: anywhere; }
.restore-feedback button { color: var(--blue); }
.restore-shield { position: absolute; inset: 64px 0 0; z-index: 4; cursor: progress; }
.connection-banner { position: absolute; z-index: 8; top: 70px; left: 50%; transform: translateX(-50%); display: flex; align-items: center; gap: 14px; max-width: calc(100% - 32px); padding: 10px 16px; font-size: 12px; color: #9b603b; }
.connection-banner button { white-space: nowrap; color: var(--blue); }
</style>
