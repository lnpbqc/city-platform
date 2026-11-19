<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, shallowRef, watch } from 'vue'
import { LoaderCircle, Save, Play, Square, Plus, RefreshCw, Crosshair, History, Settings2, X, ChartNoAxesCombined } from '@lucide/vue'
import UiTooltip from '../components/common/UiTooltip.vue'
import MapCanvas from '../components/map/MapCanvas.vue'
import BasemapSwitcher from '../components/map/BasemapSwitcher.vue'
import { vectorBasemapConfigured } from '../map/basemapSetting'
import WeatherControl from '../components/map/WeatherControl.vue'
import { useWeatherView } from '../composables/useWeatherView'
import { useDisplayRegions } from '../composables/useDisplayRegions'
import { noWeather } from '../map/weather'
import RunHistoryPanel from '../components/simulation/RunHistoryPanel.vue'
import ReplayControls from '../components/simulation/ReplayControls.vue'
import RunExports from '../components/simulation/RunExports.vue'
import TimeAxis from '../components/common/TimeAxis.vue'
import { useSimulation } from '../composables/useSimulation'
import { useTemporalLayers } from '../composables/useTemporalLayers'
import { sameTilesPlacement, tilesPlacement, type MapLayer } from '../layers/types'
import { prepareSceneLayers, sceneTilesPlacement } from '../simulation/sceneLayers'
import type { MapController } from '../map/mapController'
import { validCamera, type CameraState, type NavigationReading } from '../map/mapNavigation'
import type { SceneLayerState, SceneRecord } from '../simulation/simulationTypes'
import type { WorkspaceAddress, WorkspaceCapture } from '../router/workspaceState'
import { workspaceError } from '../router/workspaceState'
import { demoRegion } from '../map/regions'

const props = defineProps<{ active: boolean; layers: MapLayer[]; backend: 'loading' | 'online' | 'offline'; recovery?: number }>()
const emit = defineEmits<{ ready: []; runChanged: [] }>()
const cameraStorageKey = 'city.simulation.camera.v1'
function storedCamera(): CameraState | null {
  try {
    const camera: unknown = JSON.parse(window.localStorage.getItem(cameraStorageKey) ?? 'null')
    return validCamera(camera) ? camera : null
  } catch { return null }
}
const localCamera = storedCamera()
const initialCamera: CameraState = localCamera ?? { longitude: 113.364, latitude: 23.043, height: 1400, heading: 0, pitch: -Math.PI / 2, roll: 0, scene_mode: '3d' }
let controller: MapController | undefined
const basemapController = shallowRef<MapController>()
const vectorAvailable = vectorBasemapConfigured({ VITE_TIANDITU_KEY: import.meta.env?.VITE_TIANDITU_KEY })
const currentLayers = (): SceneLayerState[] => props.layers.filter(layer => layer.id === 'basemap' || layer.asset_id && layer.asset_version).map((layer, index) => ({
  layer_id: layer.id, asset: layer.asset_id && layer.asset_version ? { asset_id: layer.asset_id, version: layer.asset_version } : null,
  name: layer.name, category: layer.category,
  map_attached: layer.attached || !!layer.map_attached, map_visible: layer.visible, map_opacity: layer.opacity, road_max_level: layer.road_max_level ?? 2, order: layer.order ?? index,
  ...(layer.type === '3dtiles' ? tilesPlacement(layer, true) : {}),
}))
const simulation = useSimulation(() => controller?.getCamera() ?? initialCamera, currentLayers)
const { scenes, networks, draft, sceneId, sceneVersion, network, run, result, snapshot, loading, saving, submitting, error,
  busy, submissionPending, editingLocked, historical, resultNetwork, previewDraft, cancelling, recoveryError, initialize, chooseScene, chooseNetwork, save, submit: submitRun, cancel, refreshRun, toggleEdge, newScene, openRun, rerun } = simulation
const configurationLocked = computed(() => props.backend === 'loading' || loading.value || editingLocked.value)
const historyLocked = computed(() => loading.value || saving.value || submitting.value || busy.value || submissionPending.value)
const viewportWidth = ref(window.innerWidth)
const mobile = computed(() => viewportWidth.value < 768)
const sidebarOpen = ref(!mobile.value)
const sidebar = ref<HTMLElement | null>(null)
const panelTrigger = ref<HTMLButtonElement | null>(null)
const paneNames = { config: '配置', result: '结果', history: '历史' }
const activePane = ref<keyof typeof paneNames>('config')
const historyVisited = ref(false)
const configVisible = computed(() => sidebarOpen.value && activePane.value === 'config')
const resultVisible = computed(() => sidebarOpen.value && activePane.value === 'result')
function selectPane(value: keyof typeof paneNames) {
  const moveFocus = value !== activePane.value && sidebar.value?.querySelector<HTMLElement>(`#simulation-pane-${activePane.value}`)?.contains(document.activeElement)
  activePane.value = value
  if (value === 'history') historyVisited.value = true
  if (moveFocus) void nextTick(() => {
    if (sidebarOpen.value) sidebar.value?.querySelector<HTMLButtonElement>('[role="tab"][aria-selected="true"]')?.focus()
  })
}
function openConfig() { selectPane('config'); sidebarOpen.value = true }
function openSidebar() {
  sidebarOpen.value = true
  void nextTick(() => sidebar.value?.querySelector<HTMLButtonElement>('[role="tab"][aria-selected="true"]')?.focus())
}
function closeSidebar() { sidebarOpen.value = false; void nextTick(() => panelTrigger.value?.focus()) }
function resizeLayout() {
  const wasMobile = mobile.value
  viewportWidth.value = window.innerWidth
  if (wasMobile !== mobile.value) {
    if (mobile.value && sidebar.value?.contains(document.activeElement)) closeSidebar()
    else sidebarOpen.value = !mobile.value
  }
}
function navigatePanes(event: KeyboardEvent) {
  if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return
  event.preventDefault()
  const panes = Object.keys(paneNames) as (keyof typeof paneNames)[]
  const index = panes.indexOf(activePane.value)
  const next = event.key === 'Home' ? 0 : event.key === 'End' ? panes.length - 1
    : (index + (event.key === 'ArrowRight' ? 1 : -1) + panes.length) % panes.length
  selectPane(panes[next]!)
  const buttons = (event.currentTarget as HTMLElement).querySelectorAll<HTMLButtonElement>('[role="tab"]')
  buttons[next]?.focus()
}
function sidebarKeydown(event: KeyboardEvent) {
  if (event.defaultPrevented || !sidebarOpen.value) return
  if (event.key === 'Escape') { event.preventDefault(); closeSidebar(); return }
  if (event.key !== 'Tab' || !mobile.value) return
  const buttons = [...(sidebar.value?.querySelectorAll<HTMLElement>('button, input, select, summary, [tabindex="0"]') ?? [])]
    .filter(element => element.getClientRects().length && !element.matches(':disabled, [tabindex="-1"]'))
  const first = buttons[0], last = buttons.at(-1)
  if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last?.focus() }
  else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first?.focus() }
}
watch(result, value => { if (value) selectPane('result') })
onMounted(() => { resizeLayout(); window.addEventListener('resize', resizeLayout) })
onBeforeUnmount(() => window.removeEventListener('resize', resizeLayout))
const historyRevision = computed(() => `${run.value?.run_id ?? ''}:${run.value?.status ?? ''}`)
const mapError = ref('')
const notice = ref('')
const preview = ref(true)
const fixedWeather = computed(() => historical.value || !preview.value)
const useLiveWeather = () => props.active && !fixedWeather.value
const { regions: projectRegions } = useDisplayRegions(() => useLiveWeather() && props.backend === 'online', () => props.recovery)
const weather = useWeatherView(() => controller?.getWeatherPoint() ?? null, useLiveWeather, () => projectRegions.value)
const { mode: weatherMode, status: weatherStatus, region: weatherRegion, reference: weatherReference } = weather
const shownWeather = computed(() => fixedWeather.value ? snapshot.value?.request.weather ?? noWeather : weather.display.value)
function submit() { return submitRun(shownWeather.value) }
const replayPositions = ref<{ baseline: number[] | null; blocked: number[] | null }>({ baseline: null, blocked: null })
const mapLayers = ref<MapLayer[]>([])
const temporal = useTemporalLayers(() => mapLayers.value, () => controller)
const { time, resolution, rate, playing, maximum, position, times, loading: timeLoading, metadataLoading, counts, errors: timeErrors, allMissing } = temporal
const graph = computed(() => preview.value ? network.value : resultNetwork.value)
const blocked = computed(() => preview.value ? draft.value.blocked_edges : snapshot.value?.request.blocked_edges ?? [])
const displayResult = computed(() => preview.value ? null : result.value)
const networkKey = computed(() => draft.value.network ? JSON.stringify([draft.value.network.asset_id, draft.value.network.version]) : '')
const statusLabel = computed(() => run.value ? ({ queued: '排队', running: '运行中', succeeded: '成功', failed: '失败', cancelled: '已取消' })[run.value.status] : '')
let initialized = false
const initializationFinished = ref(false)
let layerVersion = 0
let alive = true
let restoreVersion = 0
let restoreAbort: AbortController | undefined
let restoringWorkspace = false
let recoveryPending = false
let recoveryRunning = false

watch(() => props.backend, value => {
  if (value !== 'loading' && !initialized) {
    initialized = true
    void initialize().finally(() => {
      if (localCamera && alive) controller?.setCamera(localCamera)
      initializationFinished.value = true
      if (!draft.value.current_time && time.value) draft.value.current_time = time.value
      announceReady(); void recoverWorkspace()
    })
  }
}, { immediate: true })
watch(() => props.active, async active => {
  if (!active) { temporal.pause(); return }
  await nextTick()
  controller?.resume()
  if (initializationFinished.value) void simulation.refreshCatalogs()
})
watch(() => draft.value.camera, camera => { controller?.setCamera(camera) })
watch(() => draft.value.current_time, value => {
  if (value && value !== time.value) temporal.setTime(value)
  else if (!value) { if (times.value[0]) temporal.setTime(times.value[0]); else time.value = '' }
})
watch(time, value => { if (initializationFinished.value) draft.value.current_time = value || null })
watch(() => props.recovery, () => { recoveryPending = true; void recoverWorkspace() })
watch([loading, saving, submitting, cancelling, submissionPending], () => { void recoverWorkspace() })
watch(historyRevision, () => emit('runChanged'))
watch(result, value => { preview.value = !value })
watch([preview, result], () => { if (preview.value || !result.value) showReplay({ baseline: null, blocked: null }) })

function paint() {
  try { controller?.showSimulation(graph.value ?? null, blocked.value, displayResult.value, id => {
    if (!preview.value) { notice.value = `点击“${historical.value ? '从历史编辑' : '编辑配置'}”切换到草稿后选择阻断边。`; return }
    toggleEdge(id)
    }, { origin: draft.value.origin ?? undefined, destination: draft.value.destination ?? undefined }) } catch (cause) { mapError.value = String(cause) }
}
watch([graph, () => JSON.stringify(blocked.value), displayResult], paint)
async function syncLayers(prepared: MapLayer[] = []) {
  const version = ++layerVersion
  if (!controller) return
  mapError.value = ''
  const states = draft.value.layers
  const key = (state: SceneLayerState) => JSON.stringify([state.layer_id, state.asset?.asset_id, state.asset?.version])
  const desired = new Set(states.filter(state => state.map_attached).map(key))
  for (const layer of [...mapLayers.value]) {
    if (!desired.has(key({ layer_id: layer.id, asset: layer.asset_id && layer.asset_version ? { asset_id: layer.asset_id, version: layer.asset_version } : null } as SceneLayerState))) {
      controller.remove(layer)
      mapLayers.value = mapLayers.value.filter(item => item !== layer)
    }
  }
  await Promise.all(states.filter(state => state.map_attached).map(async state => {
    const existing = mapLayers.value.find(layer => layer.id === state.layer_id && layer.asset_id === state.asset?.asset_id && layer.asset_version === state.asset?.version)
    if (existing) {
      if (existing.status === 'error') await controller?.load(existing)
      if (!alive || version !== layerVersion) return
      existing.visible = state.map_visible; existing.opacity = state.map_opacity; controller?.setRoadMaxLevel(existing, state.road_max_level ?? 2); existing.order = state.order
      if (existing.type === '3dtiles') {
        const placement = sceneTilesPlacement(state)
        if (!sameTilesPlacement(existing, placement)) void controller?.setTilesPlacement(existing, placement)
      }
      controller?.appearance(existing)
      return
    }
    try {
      const layer = prepared.find(layer => layer.id === state.layer_id && layer.asset_id === state.asset?.asset_id && layer.asset_version === state.asset?.version)
        ?? (await prepareSceneLayers([state], props.layers))[0]!
      if (!alive || version !== layerVersion || !controller) return
      mapLayers.value.push(layer)
      const current = mapLayers.value.at(-1)!
      await controller.load(current)
      if (!alive || version !== layerVersion) return
      current.visible = state.map_visible; current.opacity = state.map_opacity; controller?.setRoadMaxLevel(current, state.road_max_level ?? 2)
      controller.appearance(current)
    } catch (cause) { if (alive && version === layerVersion) mapError.value = String(cause) }
  }))
  if (alive && version === layerVersion) { controller?.syncOrder(mapLayers.value); temporal.paint() }
}
watch(() => JSON.stringify(draft.value.layers), () => { if (!restoringWorkspace) void syncLayers() })
function ready(value: MapController) {
  controller = value
  basemapController.value = value
  controller.initialize(demoRegion, localCamera ?? draft.value.camera)
  weather.resized()
  void syncLayers()
  paint()
  controller.showReplay(replayPositions.value)
  announceReady()
  void recoverWorkspace()
}
async function recoverWorkspace() {
  if (!recoveryPending || recoveryRunning || !isReady() || restoringWorkspace || loading.value || saving.value || submitting.value || cancelling.value) return
  recoveryPending = false
  recoveryRunning = true
  try {
    const recovered = await simulation.recover()
    if (!alive) return
    if (!recovered && !recoveryError.value) recoveryPending = true
    if (recovered) { await syncLayers(); await temporal.refreshAvailability(); await temporal.refresh() }
  } finally {
    recoveryRunning = false
    if (recoveryPending && alive) void recoverWorkspace()
  }
}
function isReady() { return !!controller && initializationFinished.value && alive }
function canCapture() { return isReady() && !restoringWorkspace && !loading.value && !saving.value && !submitting.value && !submissionPending.value }
function announceReady() { if (isReady()) emit('ready') }
function onNavigation(value: NavigationReading, settled: boolean) {
  if (!settled) return
  weather.settled()
  if (!props.active) return
  try { window.localStorage.setItem(cameraStorageKey, JSON.stringify(value.camera)) } catch { /* Browser storage may be disabled. */ }
}
function captureWorkspace(): WorkspaceCapture {
  if (!canCapture()) throw workspaceError('仿真画面正在读取、保存或确认提交，请完成后保存画面')
  const camera = controller!.getCamera()
  const scene = JSON.parse(JSON.stringify({ ...draft.value, camera, current_time: time.value || null, run_id: run.value?.run_id ?? draft.value.run_id }))
  return { page: 'simulation', scene, camera, run_id: scene.run_id, time: scene.current_time, resolution: resolution.value }
}
async function restoreWorkspace(scene: SceneRecord | null, address: WorkspaceAddress) {
  if (!isReady()) throw workspaceError('仿真工作区尚未准备好')
  if (scene && address.run_id && scene.run_id !== address.run_id) throw workspaceError('链接运行 ID 与固定场景保存的运行 ID 不一致')
  cancelRestore()
  const version = restoreVersion
  restoreAbort = new AbortController()
  restoringWorkspace = true
  try {
    const prepared = scene ? await prepareSceneLayers(scene.layers.filter(layer => layer.map_attached), props.layers, restoreAbort.signal) : []
    if (!alive || version !== restoreVersion) throw workspaceError('画面恢复已被新选择替换')
    const restored = scene ? await chooseScene(scene.id, address.scene_version ?? scene.version, true)
      : address.run_id ? await openRun(address.run_id, true) : true
    if (!restored || !alive || version !== restoreVersion) throw workspaceError(error.value || '画面恢复已被新选择替换')
    temporal.pause()
    resolution.value = address.resolution
    await nextTick()
    if (!alive || version !== restoreVersion) throw workspaceError('画面恢复已被新选择替换')
    const targetTime = address.time ?? scene?.current_time ?? draft.value.current_time
    if (targetTime) temporal.setTime(targetTime)
    if (address.camera) { draft.value.camera = { ...address.camera }; controller!.setCamera(address.camera) }
    await syncLayers(prepared)
    if (!alive || version !== restoreVersion) throw workspaceError('画面恢复已被新选择替换')
    preview.value = !result.value
    paint()
  } finally { if (version === restoreVersion) { restoringWorkspace = false; void recoverWorkspace() } }
}
function cancelRestore() {
  ++restoreVersion; restoreAbort?.abort(); restoringWorkspace = false; ++layerVersion
  simulation.cancelRestore()
}
function visibility() { if (document.hidden) temporal.pause() }
onMounted(() => document.addEventListener('visibilitychange', visibility))
function showReplay(value: { baseline: number[] | null; blocked: number[] | null }) {
  replayPositions.value = value
  controller?.showReplay(value)
}
function selectNetwork(event: Event) {
  const value = (event.target as HTMLSelectElement).value
  if (!value) return
  const [identity, version] = JSON.parse(value) as [string, string]
  preview.value = true
  void chooseNetwork(identity, version)
}
function selectScene(event: Event) { preview.value = true; void chooseScene((event.target as HTMLSelectElement).value) }
function editEdge(id: string) { preview.value = true; toggleEdge(id) }
function number(value: number | null) { return value === null ? '—' : value.toLocaleString('zh-CN', { maximumFractionDigits: 1 }) }
function layerName(id: string) { return props.layers.find(layer => layer.id === id)?.name ?? id }
function frameNetwork() {
  const nodes = graph.value?.nodes
  if (!nodes?.length) return
  let west = Infinity, east = -Infinity, south = Infinity, north = -Infinity
  for (const node of nodes) {
    west = Math.min(west, node.coordinates[0]!); east = Math.max(east, node.coordinates[0]!)
    south = Math.min(south, node.coordinates[1]!); north = Math.max(north, node.coordinates[1]!)
  }
  controller?.setCamera({ ...initialCamera, longitude: (west + east) / 2,
    latitude: (south + north) / 2, height: Math.max(900, (east - west) * 111320 * 2.4, (north - south) * 111320 * 2.4) })
}
function editConfiguration() { previewDraft(); preview.value = true; openConfig() }
async function selectHistory(identity: string) {
  await openRun(identity)
  if (run.value?.run_id === identity) selectPane('result')
}
async function rerunHistory(identity: string) {
  const previous = run.value?.run_id
  await rerun(identity)
  if (submissionPending.value || run.value?.run_id !== previous) selectPane('result')
}
function deletedHistory(identity: string) {
  simulation.runDeleted(identity)
  if (!run.value) { showReplay({ baseline: null, blocked: null }); preview.value = true; paint() }
  emit('runChanged')
}
onBeforeUnmount(() => { alive = false; cancelRestore(); document.removeEventListener('visibilitychange', visibility); controller = undefined })
defineExpose({ captureWorkspace, restoreWorkspace, cancelRestore, isReady, canCapture })
</script>

<template>
  <section class="simulation-workspace" :class="{ 'sidebar-open': sidebarOpen }" aria-label="仿真推演工作区">
    <div v-if="mobile && sidebarOpen" class="simulation-scrim" @click="closeSidebar" />
    <aside v-show="sidebarOpen" id="simulation-sidebar" ref="sidebar" class="simulation-sidebar panel"
      :role="mobile ? 'dialog' : undefined" :aria-modal="mobile || undefined" aria-label="仿真面板" @keydown="sidebarKeydown">
      <header class="sidebar-heading"><h1>仿真推演</h1><div class="sidebar-actions">
        <UiTooltip :text="configurationLocked ? '请完成当前操作后新建场景' : '新建场景'"><button class="icon-button" aria-label="新建场景" :disabled="configurationLocked" @click="newScene(); preview = true; selectPane('config')"><Plus :size="18" /></button></UiTooltip>
        <button class="icon-button" aria-label="收起仿真面板" @click="closeSidebar"><X :size="18" /></button>
      </div></header>
      <div class="simulation-tabs" role="tablist" aria-label="仿真面板内容" @keydown="navigatePanes">
        <button v-for="(label, pane) in paneNames" :id="`simulation-tab-${pane}`" :key="pane" role="tab"
          :aria-selected="activePane === pane" :aria-controls="`simulation-pane-${pane}`" :tabindex="activePane === pane ? 0 : -1" @click="selectPane(pane)">
          <Settings2 v-if="pane === 'config'" :size="16" /><ChartNoAxesCombined v-else-if="pane === 'result'" :size="16" /><History v-else :size="16" />{{ label }}
        </button>
      </div>
      <div class="simulation-pane-body">
        <section v-show="configVisible" id="simulation-pane-config" class="simulation-config" role="tabpanel" aria-labelledby="simulation-tab-config" tabindex="0">
          <p class="synthetic">{{ network?.synthetic ? '合成演示 · 校区附近路网' : '版本化路网' }}</p>
          <p v-if="loading || backend === 'loading'" role="status"><LoaderCircle :size="14" class="spin" />正在读取场景与路网…</p>
          <fieldset :disabled="configurationLocked">
              <section class="config-group"><h2>场景</h2>
        <label>已保存场景<select aria-label="选择场景" :value="sceneId" @change="selectScene"><option value="">新建场景</option><option v-for="scene in scenes" :key="scene.id" :value="scene.id">{{ scene.name }} · v{{ scene.version }}</option></select></label>
        <label>场景名称<input v-model="draft.name" maxlength="120" aria-label="场景名称"></label>
        </section><section class="config-group"><h2>路网与起终点</h2>
        <label>路网版本<select aria-label="路网版本" :value="networkKey" @change="selectNetwork"><option value="">选择路网</option><option v-for="item in networks" :key="`${item.asset_id}@${item.version}`" :value="JSON.stringify([item.asset_id, item.version])">{{ item.name }} · {{ item.version }}</option></select></label>
        <div class="field-pair"><label>起点<select v-model="draft.origin" aria-label="起点" @change="preview = true"><option v-for="node in network?.nodes ?? []" :key="node.id" :value="node.id">{{ node.id }}</option></select></label><label>终点<select v-model="draft.destination" aria-label="终点" @change="preview = true"><option v-for="node in network?.nodes ?? []" :key="node.id" :value="node.id">{{ node.id }}</option></select></label></div>
        <div class="field-pair"><label>模式<input value="小汽车" readonly aria-label="运行模式"></label><label>随机种子<input v-model.number="draft.seed" type="number" step="1" aria-label="随机种子"></label></div>
        </section><section class="config-group"><div class="section-heading"><h2>阻断边</h2><span>{{ draft.blocked_edges.length }} / {{ network?.edges.length ?? 0 }}</span></div>
        <p class="hint">点击地图道路或勾选列表，使用相同的边ID。</p>
        <ul class="edge-list"><li v-for="edge in network?.edges ?? []" :key="edge.id"><label><input type="checkbox" :checked="draft.blocked_edges.includes(edge.id)" :aria-label="`阻断 ${edge.id}`" @change="editEdge(edge.id)"><span>{{ edge.id }}</span><small>{{ number(edge.length_m) }} m</small></label></li></ul>
        </section><section class="config-group"><h2>固定图层</h2><details class="scene-layers"><summary>固定图层与状态 · {{ draft.layers.length }}</summary><div v-for="layer in draft.layers" :key="layer.layer_id" class="scene-layer"><label><input v-model="layer.map_attached" type="checkbox" :aria-label="`加入场景 ${layerName(layer.layer_id)}`">{{ layerName(layer.layer_id) }}<small>{{ layer.asset?.version ?? '底图' }}</small></label><div v-if="layer.map_attached" class="scene-layer-controls"><label><input v-model="layer.map_visible" type="checkbox" :aria-label="`显示场景 ${layerName(layer.layer_id)}`">显示</label><input v-model.number="layer.map_opacity" type="range" min="0" max="1" step="0.05" :aria-label="`场景透明度 ${layerName(layer.layer_id)}`"><span>{{ Math.round(layer.map_opacity * 100) }}%</span><label v-if="layer.category === '道路' || layer.category === '线状网络'">道路显示到<select :value="layer.road_max_level ?? 2" :aria-label="`场景道路显示到 ${layerName(layer.layer_id)}`" @change="layer.road_max_level = Number(($event.target as HTMLSelectElement).value)"><option v-for="level in 4" :key="level" :value="level">第 {{ level }} 级</option></select></label></div></div></details>
      </section></fieldset>
          <p v-if="historical" class="hint">历史快照 · 场景 v{{ run?.scene_version }}。从历史编辑会创建新场景草稿。</p>
        </section>
        <section v-show="resultVisible" id="simulation-pane-result" class="simulation-result" role="tabpanel" aria-labelledby="simulation-tab-result" tabindex="0">
          <p v-if="!run" class="empty-result">配置场景并提交运行后，在此查看结果与路径回放。</p>
          <section v-if="run" class="run-summary" aria-label="当前运行">
            <div class="section-heading"><h2>{{ statusLabel }}</h2><span>场景 v{{ run.scene_version }}</span></div>
            <p v-if="busy" class="hint">运行完成后自动显示路径对比。</p>
            <p v-if="run.error" class="error" role="alert">{{ run.error.code }} · {{ run.error.message }}</p>
            <details class="run-identifiers"><summary>运行详情</summary><p>run_id：{{ run.run_id }}</p><p>{{ run.model_version }} · {{ run.data_version }}</p><p>输入 SHA-256：{{ run.inputs_sha256 }}</p><p>trace_id：{{ run.trace_id }}</p></details>
          </section>
          <template v-if="result"><header><h2>路径对比</h2><span>{{ snapshot?.request.network.asset_id }}@{{ snapshot?.request.network.version }} · {{ snapshot?.request.origin }} → {{ snapshot?.request.destination }}</span><strong>{{ result.blocked.reachable ? result.metrics.rerouted ? '已绕行' : result.blocked.path.length === 1 ? '起终点相同' : '路径保持' : '阻断后不可达' }}</strong><RunExports :key="result.run_id" :identity="result.run_id" /></header>
      <div class="result-columns"><div class="blue"><h3>基准</h3><strong>{{ number(result.baseline.length_m) }} <small>m</small></strong><span>{{ number(result.baseline.duration_s) }} 秒</span><p>{{ result.baseline.reachable ? result.baseline.path.join(' → ') : '不可达' }}</p></div><div class="orange"><h3>阻断后</h3><strong>{{ number(result.blocked.length_m) }} <small>m</small></strong><span>{{ number(result.blocked.duration_s) }} 秒</span><p>{{ result.blocked.reachable ? result.blocked.path.join(' → ') : '不可达' }}</p></div><div><h3>长度变化</h3><strong>{{ result.metrics.increase_percent === null ? '—' : `${result.metrics.increase_percent >= 0 ? '+' : ''}${number(result.metrics.increase_percent)}%` }}</strong><span>按边速度累计时间</span><p>合成演示，长度使用路网显式权重。</p></div></div>
      <ReplayControls v-if="resultNetwork && !preview" :key="result.run_id" :network="resultNetwork" :result="result" :active="active && resultVisible" @position="showReplay" />
    </template>
        </section>
        <section v-show="activePane === 'history'" id="simulation-pane-history" class="simulation-history" role="tabpanel" aria-labelledby="simulation-tab-history">
          <RunHistoryPanel v-if="historyVisited" embedded :active="active && sidebarOpen && activePane === 'history'" :scenes="scenes" :locked="historyLocked" :selected="run?.run_id ?? ''" :revision="historyRevision" :recovery="recovery" @close="closeSidebar" @select="selectHistory" @rerun="rerunHistory" @deleted="deletedHistory" />
        </section>
      </div>
      <footer class="simulation-footer">
        <div v-if="run" class="run-status"><span role="status">当前运行 · {{ statusLabel }}</span><button v-if="busy" class="text-button" :disabled="cancelling" @click="cancel()"><Square :size="12" />{{ cancelling ? '取消中…' : '取消运行' }}</button></div>
        <div v-if="error || recoveryError || submissionPending" class="footer-messages">
          <p v-if="submissionPending" class="hint">上次提交结果未知，重试将复用同一幂等键。配置已锁定。</p>
          <p v-if="error" class="error" role="alert">{{ error }}<button v-if="!submissionPending && sceneId && error.includes('SCENE_VERSION_CONFLICT')" class="text-button" @click="chooseScene(sceneId)">读取最新场景</button><button v-else-if="!submissionPending" class="text-button" @click="run ? refreshRun() : initialize()"><RefreshCw :size="13" />刷新</button></p>
          <p v-if="recoveryError" class="error" role="alert">只读恢复失败：{{ recoveryError }}</p>
        </div>
        <template v-if="activePane === 'config'"><div class="save-actions"><button class="secondary-button" :disabled="configurationLocked" @click="save()"><Save :size="14" />{{ saving ? '保存中…' : sceneId ? '保存场景' : '创建场景' }}</button><button v-if="sceneId" class="text-button" :disabled="configurationLocked" @click="save(true)">另存为</button><span v-if="sceneId">v{{ sceneVersion }}</span></div></template>
        <button v-if="historical && run && !submissionPending" class="secondary-button" :disabled="historyLocked" @click="editConfiguration">从历史编辑</button>
        <button v-else-if="activePane === 'result' && result" class="secondary-button" :disabled="historyLocked" @click="editConfiguration">编辑配置</button>
        <template v-if="activePane !== 'history'"><button class="primary-button run-button" :disabled="backend === 'loading' || submitting || busy || saving || loading || !network" @click="historical && !submissionPending && run ? rerunHistory(run.run_id) : submit()"><LoaderCircle v-if="submitting || busy" :size="16" class="spin" /><Play v-else :size="16" />{{ submitting ? '正在提交…' : busy ? '正在运行' : submissionPending ? '重试同一次提交' : historical ? '从历史重跑' : '提交运行' }}</button></template>
      </footer>
    </aside>
    <section class="simulation-map" aria-label="仿真地图" :inert="mobile && sidebarOpen">
      <MapCanvas :weather-effect="active ? shownWeather.effect : 'none'" track-weather
        @camera-move="weather.moving" @weather-resize="weather.resized" @ready="ready" @navigation="onNavigation" @notice="notice = $event" @fatal="mapError = $event" />
      <div class="simulation-map-layout">
        <div class="simulation-map-top">
          <div class="simulation-tools panel">
            <button v-if="!sidebarOpen" ref="panelTrigger" aria-label="打开仿真面板" aria-controls="simulation-sidebar" :aria-expanded="sidebarOpen" @click="openSidebar"><Settings2 :size="16" />仿真面板</button>
            <button @click="frameNetwork"><Crosshair :size="16" />定位路网</button>
            <button v-if="result && !historical" :aria-pressed="preview" @click="preview ? preview = false : editConfiguration()">{{ preview ? '查看结果图层' : '编辑配置' }}</button>
            <span>{{ preview ? '配置预览' : '固定运行结果' }}</span>
          </div>
          <WeatherControl class="simulation-weather" compact v-model:mode="weatherMode" :weather="shownWeather" :status="weatherStatus"
        :region="weatherRegion?.name" :reference="weatherReference" :fixed="fixedWeather" />
        </div>
        <div v-if="mapError || notice || mapLayers.some(layer => layer.status === 'error')" class="map-notice panel" role="status"><p>{{ mapError || notice }}</p><p v-for="layer in mapLayers.filter(layer => layer.status === 'error')" :key="layer.id">{{ layer.name }}：{{ layer.error }}</p><button class="text-button" @click="mapError = ''; notice = ''; syncLayers()">刷新场景图层</button></div>
        <div class="simulation-map-bottom">
          <div class="simulation-map-bottom-row">
            <div class="route-legend panel" aria-label="路线图例"><span class="blue">━ 基准路径</span><span class="orange">━ 阻断后路径</span><span class="red">× 阻断边</span></div>
            <BasemapSwitcher class="simulation-basemap" :controller="basemapController" :vector-available="vectorAvailable" />
          </div>
          <TimeAxis v-if="initializationFinished && temporal.dynamicLayers.value.length" class="simulation-time" label="专题数据时间" :time="time" v-model:resolution="resolution" v-model:rate="rate" :playing="playing"
      :maximum="maximum" :position="position" :times="times" :loading="timeLoading" :metadata-loading="metadataLoading" :counts="counts" :errors="timeErrors" :all-missing="allMissing"
      @select="temporal.setTime" @seek="temporal.seek" @step="temporal.step" @play="temporal.play" @pause="temporal.pause" @refresh="temporal.refreshAvailability(); temporal.refresh()" />
        </div>
      </div>
    </section>
  </section>
</template>

<style scoped>
.simulation-workspace { position: absolute; inset: 80px 16px 16px; display: grid; grid-template-columns: minmax(0, 1fr); gap: 16px; color: var(--text); font-size: 14px; }
.simulation-workspace.sidebar-open { grid-template-columns: 360px minmax(0, 1fr); }
.simulation-sidebar { display: flex; flex-direction: column; min-width: 0; min-height: 0; overflow: hidden; background: white; }
.sidebar-heading { display: flex; align-items: center; justify-content: space-between; gap: 12px; padding: 12px 16px; }
.sidebar-heading h1 { font-size: 18px; margin: 0; }
.sidebar-actions { display: flex; gap: 8px; }
.simulation-tabs { display: flex; padding: 0 16px; gap: 8px; border-bottom: 1px solid var(--line); }
.simulation-tabs button { flex: 1; min-height: 44px; gap: 8px; padding: 0 4px; border-bottom: 3px solid transparent; color: #475569; }
.simulation-tabs button[aria-selected=true] { color: var(--blue); border-bottom-color: var(--blue); font-weight: 600; }
.sidebar-heading, .simulation-tabs, .simulation-footer { flex-shrink: 0; }
.simulation-pane-body { flex: 1; min-height: 0; overflow: hidden; }
.simulation-pane-body > section { height: 100%; min-height: 0; overflow-y: auto; overscroll-behavior: contain; scrollbar-gutter: stable; }
.simulation-pane-body > section:focus-visible { outline: 2px solid var(--blue); outline-offset: -2px; }
.simulation-config, .simulation-result { padding: 16px; }
.simulation-history { min-height: 0; }
.synthetic, .hint, .run-summary span, .run-status, .save-actions > span { font-size: 12px; color: #475569; line-height: 1.7; }
.synthetic { margin-bottom: 16px; }
.hint { margin: 8px 0; }
h2, h3 { font-size: 16px; margin: 0; font-weight: 600; }
fieldset { min-width: 0; border: 0; padding: 0; margin: 0; }
fieldset:disabled { opacity: .6; }
.config-group + .config-group { margin-top: 24px; }
.config-group > h2, .config-group > .section-heading { margin-bottom: 12px; }
.config-group > label, .field-pair label { display: grid; gap: 8px; margin-bottom: 12px; min-width: 0; color: #334155; }
.field-pair { display: grid; grid-template-columns: minmax(0, 1fr) minmax(0, 1fr); gap: 12px; }
select, input:not([type=checkbox]) { width: 100%; min-width: 0; padding: 9px 10px; border: 1px solid var(--line); border-radius: 5px; background: white; color: var(--text); font: inherit; }
input[type=checkbox] { accent-color: var(--blue); }
.section-heading { display: flex; align-items: center; justify-content: space-between; gap: 12px; }
.section-heading > span { font-size: 12px; color: #475569; }
.edge-list { list-style: none; margin: 0; padding: 0; }
.edge-list label { display: flex; align-items: center; gap: 8px; min-height: 40px; border-bottom: 1px solid #edf1f6; cursor: pointer; }
.edge-list small { margin-left: auto; color: #475569; font-size: 12px; }
.scene-layers summary { cursor: pointer; padding-block: 8px; color: #475569; }
.scene-layer { padding-block: 8px; border-bottom: 1px solid var(--line); }
.scene-layer label { display: flex; flex-wrap: wrap; align-items: center; gap: 8px; overflow-wrap: anywhere; }
.scene-layer small { margin-left: auto; font-size: 12px; color: #475569; }
.scene-layer-controls { display: flex; flex-wrap: wrap; align-items: center; gap: 8px; padding-top: 8px; }
.scene-layer-controls input[type=range] { flex: 1; width: 70px; padding: 0; }
.scene-layer-controls span { font-size: 12px; }
.simulation-footer { display: grid; gap: 8px; padding: 12px 16px 16px; border-top: 1px solid var(--line); background: white; }
.simulation-footer > button { width: 100%; min-height: 40px; }
.save-actions { display: flex; align-items: center; flex-wrap: wrap; gap: 8px; }
.save-actions button { gap: 8px; min-height: 36px; }
.run-button { gap: 8px; }
.run-status { display: flex; align-items: center; justify-content: space-between; gap: 8px; }
.run-status button { gap: 8px; }
.footer-messages { max-height: 84px; overflow-y: auto; }
.footer-messages .hint { margin: 0; }
.error { color: #b42318; font-size: 12px; line-height: 1.7; overflow-wrap: anywhere; }
.error button { margin-left: 8px; }
.empty-result { margin: 0; color: #475569; line-height: 1.7; }
.run-summary { margin-bottom: 24px; }
.run-identifiers { margin-top: 12px; font-size: 12px; color: #475569; }
.run-identifiers summary { cursor: pointer; }
.run-identifiers p { margin: 8px 0 0; overflow-wrap: anywhere; }
.simulation-result > header { display: flex; flex-wrap: wrap; align-items: center; gap: 12px; }
.simulation-result > header > span { width: 100%; font-size: 12px; color: #475569; overflow-wrap: anywhere; }
.simulation-result > header > strong { font-size: 14px; }
.result-columns { display: grid; gap: 16px; margin-top: 16px; }
.result-columns > div { display: grid; gap: 8px; padding: 12px; border: 1px solid var(--line); border-radius: 6px; }
.result-columns strong { font-size: 26px; font-weight: 600; }
.result-columns small, .result-columns span, .result-columns p { font-size: 12px; line-height: 1.7; margin: 0; overflow-wrap: anywhere; }
.result-columns > div:last-child { color: #475569; }
.simulation-result :deep(.replay-actions) { flex-wrap: wrap; gap: 8px; }
.simulation-result :deep(.replay-actions > span) { flex-basis: 100%; margin-left: 0; }
.simulation-result :deep(.replay button) { min-width: 36px; min-height: 36px; }
.simulation-result :deep(.replay :is(h3, output, label, .replay-actions > span)), .simulation-result :deep(.run-exports button) { font-size: 12px; }
.simulation-result :deep(.run-exports button) { min-height: 36px; }
.simulation-map { position: relative; min-width: 0; min-height: 0; overflow: hidden; border-radius: 9px; }
.simulation-map > :deep(.map-canvas) { inset: 0; }
.simulation-map :deep(.cesium-viewer-bottom) { max-width: calc(100% - 12px); }
.simulation-map-layout { position: absolute; inset: 16px 16px 32px; display: flex; flex-direction: column; justify-content: space-between; gap: 16px; pointer-events: none; }
.simulation-map-top { position: relative; z-index: 5; display: flex; flex-wrap: wrap; align-items: start; justify-content: space-between; gap: 16px; }
.simulation-map-top > *, .simulation-map-bottom-row > *, .simulation-time, .map-notice { pointer-events: auto; }
.simulation-tools { display: flex; flex-wrap: wrap; align-items: center; gap: 8px; padding: 4px 8px; max-width: 100%; }
.simulation-tools button { min-height: 36px; gap: 8px; padding-inline: 4px; color: var(--blue); }
.simulation-tools > span { color: #475569; font-size: 12px; padding-inline: 4px; }
.simulation-map-top .simulation-weather { position: static; min-width: 0; max-width: 100%; }
.simulation-map-top .simulation-weather :deep(.weather-content) { right: 0; left: auto; width: min(320px, calc(100vw - 64px)); }
.simulation-map-bottom { display: flex; flex-direction: column; gap: 12px; min-height: 0; }
.simulation-map-bottom-row { display: flex; flex-wrap: wrap; align-items: end; justify-content: space-between; gap: 16px; flex-shrink: 0; }
.route-legend { display: flex; flex-wrap: wrap; gap: 8px 16px; max-width: 100%; padding: 12px; font-size: 12px; }
.blue { color: #2563eb; } .orange { color: #a65f00; } .red { color: #dc2626; }
.simulation-basemap { position: relative; inset: auto; flex: 0 0 auto; margin-left: auto; }
.simulation-time { position: relative; inset: auto; min-height: 64px; max-height: min(28svh, 240px); overflow-y: auto; flex: 0 1 auto; }
.map-notice { align-self: start; max-width: 100%; max-height: 96px; overflow: auto; padding: 12px; font-size: 12px; color: #a55145; }
@media (min-width: 768px) and (max-width: 1199px) { .simulation-workspace.sidebar-open { grid-template-columns: 320px minmax(0, 1fr); } }
@media (max-width: 767px) {
  .simulation-workspace, .simulation-workspace.sidebar-open { inset: 80px 16px 16px; grid-template-columns: minmax(0, 1fr); }
  .simulation-sidebar { position: absolute; inset: 0 auto 0 0; z-index: 8; width: min(360px, calc(100vw - 56px)); }
  .simulation-scrim { position: fixed; inset: 64px 0 0; z-index: 7; background: #14263b66; }
  .simulation-map-layout { inset: 12px 12px 32px; gap: 12px; }
  .simulation-tools > span { display: none; }
  .simulation-tools button { min-height: 44px; }
  .simulation-map-top { gap: 12px; }
  .simulation-map-bottom-row { gap: 12px; }
  .route-legend { gap: 8px; padding: 8px; }
  .simulation-time { max-height: 24svh; }
}
@media (max-width: 600px) {
  .simulation-workspace, .simulation-workspace.sidebar-open { top: 74px; }
  .simulation-scrim { top: 58px; }
}
@media (max-height: 560px) {
  .sidebar-heading { padding-block: 4px; }
  .simulation-footer { grid-template-columns: minmax(0, 1fr) minmax(0, 1fr); padding-block: 8px; }
  .simulation-footer > :is(.run-status, .footer-messages) { grid-column: 1 / -1; }
  .simulation-footer > button { min-height: 36px; padding: 8px; }
  .simulation-footer > .run-button:only-child { grid-column: 1 / -1; }
  .simulation-map-top { gap: 8px; }
  .simulation-map-layout { gap: 8px; }
  .simulation-map-bottom { gap: 8px; }
  .simulation-map-bottom-row { align-items: end; }
  .simulation-map-bottom-row .route-legend { padding: 6px 8px; }
  .simulation-basemap { height: 60px; }
  .simulation-basemap :deep(.basemap-card) { height: 54px; }
}
</style>
