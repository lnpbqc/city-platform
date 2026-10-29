<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { LoaderCircle, Save, Play, Square, Plus, RefreshCw, Crosshair, History } from '@lucide/vue'
import MapCanvas from './MapCanvas.vue'
import RunHistoryPanel from './RunHistoryPanel.vue'
import ReplayControls from './ReplayControls.vue'
import RunExports from './RunExports.vue'
import TimeAxis from './TimeAxis.vue'
import { useSimulation } from '../composables/useSimulation'
import { useTemporalLayers } from '../composables/useTemporalLayers'
import type { MapLayer } from '../types'
import { prepareSceneLayers } from '../sceneLayers'
import type { MapController } from '../mapController'
import type { CameraState } from '../mapNavigation'
import type { SceneLayerState, SceneRecord } from '../simulationTypes'
import type { WorkspaceAddress, WorkspaceCapture } from '../workspaceState'
import { workspaceError } from '../workspaceState'
import { demoRegion } from '../regions'

const props = defineProps<{ active: boolean; layers: MapLayer[]; backend: 'loading' | 'online' | 'offline'; recovery?: number }>()
const emit = defineEmits<{ ready: []; changed: []; runChanged: [] }>()
const initialCamera: CameraState = { longitude: 113.364, latitude: 23.043, height: 1400, heading: 0, pitch: -Math.PI / 2, roll: 0, scene_mode: '3d' }
let controller: MapController | undefined
const currentLayers = (): SceneLayerState[] => props.layers.filter(layer => layer.id === 'basemap' || layer.asset_id && layer.asset_version).map((layer, index) => ({
  layer_id: layer.id, asset: layer.asset_id && layer.asset_version ? { asset_id: layer.asset_id, version: layer.asset_version } : null,
  map_attached: layer.attached || !!layer.map_attached, map_visible: layer.visible, map_opacity: layer.opacity, order: layer.order ?? index,
}))
const simulation = useSimulation(() => controller?.getCamera() ?? initialCamera, currentLayers)
const { scenes, networks, draft, sceneId, sceneVersion, network, run, result, snapshot, loading, saving, submitting, error,
  busy, submissionPending, editingLocked, historical, resultNetwork, previewDraft, cancelling, recoveryError, initialize, chooseScene, chooseNetwork, save, submit, cancel, refreshRun, toggleEdge, newScene, openRun, rerun } = simulation
const configurationLocked = computed(() => props.backend === 'loading' || loading.value || editingLocked.value)
const historyLocked = computed(() => loading.value || saving.value || submitting.value || busy.value || submissionPending.value)
const historyOpen = ref(false)
const historyRevision = computed(() => `${run.value?.run_id ?? ''}:${run.value?.status ?? ''}`)
const mapError = ref('')
const notice = ref('')
const runStatus = ref<HTMLElement | null>(null)
const preview = ref(true)
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
      initializationFinished.value = true
      if (!draft.value.current_time && time.value) draft.value.current_time = time.value
      announceReady(); void recoverWorkspace()
    })
  }
}, { immediate: true })
watch(() => props.active, async active => { if (active) { await nextTick(); controller?.resume() } else temporal.pause() })
watch(() => draft.value.camera, camera => { controller?.setCamera(camera) })
watch(() => draft.value.current_time, value => {
  if (value && value !== time.value) temporal.setTime(value)
  else if (!value) { if (times.value[0]) temporal.setTime(times.value[0]); else time.value = '' }
})
watch(time, value => { if (initializationFinished.value) draft.value.current_time = value || null })
watch([time, resolution, sceneId, sceneVersion, loading, saving, submitting, submissionPending, () => run.value?.run_id, () => JSON.stringify(draft.value)], changed)
watch(() => props.recovery, () => { recoveryPending = true; void recoverWorkspace() })
watch([loading, saving, submitting, cancelling, submissionPending], () => { void recoverWorkspace() })
watch(historyRevision, () => emit('runChanged'))
watch(result, value => { preview.value = !value })
watch([preview, result], () => { if (preview.value || !result.value) showReplay({ baseline: null, blocked: null }) })
watch(() => run.value?.run_id, async id => {
  if (id) { await nextTick(); runStatus.value?.scrollIntoView({ block: 'nearest' }) }
})

function paint() {
  try { controller?.showSimulation(graph.value ?? null, blocked.value, displayResult.value, id => {
    if (!preview.value) { notice.value = `点击“${historical.value ? '从历史编辑' : '编辑配置'}”切换到草稿后选择阻断边。`; return }
    toggleEdge(id)
  }) } catch (cause) { mapError.value = String(cause) }
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
      existing.visible = state.map_visible; existing.opacity = state.map_opacity; existing.order = state.order
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
      current.visible = state.map_visible; current.opacity = state.map_opacity
      controller.appearance(current)
    } catch (cause) { if (alive && version === layerVersion) mapError.value = String(cause) }
  }))
  if (alive && version === layerVersion) { controller?.syncOrder(mapLayers.value); temporal.paint() }
}
watch(() => JSON.stringify(draft.value.layers), () => { if (!restoringWorkspace) void syncLayers() })
function ready(value: MapController) {
  controller = value
  controller.initialize(demoRegion, draft.value.camera)
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
function changed() { if (isReady()) emit('changed') }
function captureWorkspace(): WorkspaceCapture {
  if (!canCapture()) throw workspaceError('仿真画面正在读取、保存或确认提交，请完成后保存画面')
  const camera = controller!.getCamera()
  const scene = JSON.parse(JSON.stringify({ ...draft.value, camera, current_time: time.value || null, run_id: run.value?.run_id ?? draft.value.run_id }))
  return { page: 'simulation', scene, camera, run_id: scene.run_id, time: scene.current_time, resolution: resolution.value, comparison: null }
}
async function restoreWorkspace(scene: SceneRecord | null, address: WorkspaceAddress) {
  if (!isReady()) throw workspaceError('仿真工作区尚未准备好')
  if (address.comparison) throw workspaceError('双视图时间仅用于地图工作台')
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
  controller?.setCamera({ ...initialCamera, longitude: (west + east) / 2 - (east - west) * 0.35,
    latitude: (south + north) / 2, height: Math.max(900, (east - west) * 111320 * 2.4, (north - south) * 111320 * 2.4) })
}
function editConfiguration() { previewDraft(); preview.value = true }
async function selectHistory(identity: string) {
  await openRun(identity)
  if (run.value?.run_id === identity) historyOpen.value = false
}
async function rerunHistory(identity: string) {
  const previous = run.value?.run_id
  await rerun(identity)
  if (submissionPending.value || run.value?.run_id !== previous) historyOpen.value = false
}
onBeforeUnmount(() => { alive = false; cancelRestore(); document.removeEventListener('visibilitychange', visibility); controller = undefined })
defineExpose({ captureWorkspace, restoreWorkspace, cancelRestore, isReady, canCapture })
</script>

<template>
  <section class="simulation-workspace" aria-label="仿真推演工作区">
    <MapCanvas @ready="ready" @navigation="(_value, settled) => { if (settled) changed() }" @notice="notice = $event" @fatal="mapError = $event" />
    <aside class="simulation-config panel" aria-label="仿真配置">
      <header><div><span class="eyebrow">SIMULATION</span><h1>仿真推演</h1></div><button class="icon-button" aria-label="新建场景" :disabled="configurationLocked" @click="newScene(); preview = true"><Plus :size="18" /></button></header>
      <p class="synthetic">{{ network?.synthetic ? '合成演示 · 校区附近路网' : '版本化路网' }}</p>
      <p v-if="loading || backend === 'loading'"><LoaderCircle :size="14" class="spin" />正在读取场景与路网…</p>
      <fieldset :disabled="configurationLocked">
        <label>已保存场景<select aria-label="选择场景" :value="sceneId" @change="selectScene"><option value="">新建场景</option><option v-for="scene in scenes" :key="scene.id" :value="scene.id">{{ scene.name }} · v{{ scene.version }}</option></select></label>
        <label>场景名称<input v-model="draft.name" maxlength="120" aria-label="场景名称"></label>
        <label>路网版本<select aria-label="路网版本" :value="networkKey" @change="selectNetwork"><option value="">选择路网</option><option v-for="item in networks" :key="`${item.asset_id}@${item.version}`" :value="JSON.stringify([item.asset_id, item.version])">{{ item.name }} · {{ item.version }}</option></select></label>
        <div class="field-pair"><label>起点<select v-model="draft.origin" aria-label="起点" @change="preview = true"><option v-for="node in network?.nodes ?? []" :key="node.id" :value="node.id">{{ node.id }}</option></select></label><label>终点<select v-model="draft.destination" aria-label="终点" @change="preview = true"><option v-for="node in network?.nodes ?? []" :key="node.id" :value="node.id">{{ node.id }}</option></select></label></div>
        <div class="field-pair"><label>模式<input value="小汽车" readonly aria-label="运行模式"></label><label>随机种子<input v-model.number="draft.seed" type="number" step="1" aria-label="随机种子"></label></div>
        <div class="section-heading"><h2>阻断边</h2><span>{{ draft.blocked_edges.length }} / {{ network?.edges.length ?? 0 }}</span></div>
        <p class="hint">点击地图道路或勾选列表，使用相同的边ID。</p>
        <ul class="edge-list"><li v-for="edge in network?.edges ?? []" :key="edge.id"><label><input type="checkbox" :checked="draft.blocked_edges.includes(edge.id)" :aria-label="`阻断 ${edge.id}`" @change="editEdge(edge.id)"><span>{{ edge.id }}</span><small>{{ number(edge.length_m) }} m</small></label></li></ul>
        <details class="scene-layers"><summary>固定图层与状态 · {{ draft.layers.length }}</summary><div v-for="layer in draft.layers" :key="layer.layer_id" class="scene-layer"><label><input v-model="layer.map_attached" type="checkbox" :aria-label="`加入场景 ${layerName(layer.layer_id)}`">{{ layerName(layer.layer_id) }}<small>{{ layer.asset?.version ?? '底图' }}</small></label><div v-if="layer.map_attached" class="scene-layer-controls"><label><input v-model="layer.map_visible" type="checkbox" :aria-label="`显示场景 ${layerName(layer.layer_id)}`">显示</label><input v-model.number="layer.map_opacity" type="range" min="0" max="1" step="0.05" :aria-label="`场景透明度 ${layerName(layer.layer_id)}`"><span>{{ Math.round(layer.map_opacity * 100) }}%</span></div></div></details>
      </fieldset>
      <div class="save-actions"><button class="secondary-button" :disabled="configurationLocked" @click="save()"><Save :size="14" />{{ saving ? '保存中…' : sceneId ? '保存场景' : '创建场景' }}</button><button v-if="sceneId" class="text-button" :disabled="configurationLocked" @click="save(true)">另存为</button><span v-if="sceneId">v{{ sceneVersion }}</span></div>
      <p v-if="historical" class="hint">历史快照 · 场景 v{{ run?.scene_version }}。从历史编辑会创建新场景草稿。</p>
      <button v-if="historical && !submissionPending && run" class="secondary-button run-button" :disabled="historyLocked" @click="editConfiguration">从历史编辑</button>
      <button class="primary-button run-button" :disabled="backend === 'loading' || submitting || busy || saving || loading || !network" @click="historical && !submissionPending && run ? rerunHistory(run.run_id) : submit()"><LoaderCircle v-if="submitting || busy" :size="16" class="spin" /><Play v-else :size="16" />{{ submitting ? '正在提交…' : busy ? '正在运行' : submissionPending ? '重试同一次提交' : historical ? '从历史重跑' : '提交运行' }}</button>
      <p v-if="submissionPending" class="hint">上次提交结果未知，重试将复用同一幂等键。配置已锁定。</p>
      <p v-if="error" class="error" role="alert">{{ error }}<button v-if="!submissionPending && sceneId && error.includes('SCENE_VERSION_CONFLICT')" class="text-button" @click="chooseScene(sceneId)">读取最新场景</button><button v-else-if="!submissionPending" class="text-button" @click="run ? refreshRun() : initialize()"><RefreshCw :size="13" />刷新</button></p>
      <p v-if="recoveryError" class="error" role="alert">只读恢复失败：{{ recoveryError }}</p>
      <section v-if="run" ref="runStatus" class="run-status" aria-label="当前运行">
        <div class="section-heading"><h2>{{ statusLabel }}</h2><button v-if="busy" class="text-button" :disabled="cancelling" @click="cancel()"><Square :size="12" />{{ cancelling ? '取消中…' : '取消运行' }}</button></div>
        <p class="identity">run_id：{{ run.run_id }}</p><p>场景版本 {{ run.scene_version }} · {{ run.model_version }}</p>
        <p class="identity">输入SHA-256：{{ run.inputs_sha256 }}</p><p class="identity">trace_id：{{ run.trace_id }}</p>
        <p v-if="run.error" class="error">{{ run.error.code }} · {{ run.error.message }} · trace_id：{{ run.error.trace_id }}</p>
      </section>
    </aside>
    <div class="simulation-tools panel"><button :aria-expanded="historyOpen" @click="historyOpen = !historyOpen"><History :size="16" />运行历史</button><button @click="frameNetwork"><Crosshair :size="16" />定位路网</button><button v-if="result && !historical" :aria-pressed="preview" @click="preview ? preview = false : editConfiguration()">{{ preview ? '查看结果图层' : '编辑配置' }}</button><span>{{ preview ? '配置预览' : '固定运行结果' }}</span></div>
    <div class="route-legend panel" aria-label="路线图例"><span class="blue">━ 基准路径</span><span class="orange">━ 阻断后路径</span><span class="red">× 阻断边</span></div>
    <TimeAxis v-if="initializationFinished && temporal.dynamicLayers.value.length" class="simulation-time" :class="{ 'with-result': result }" label="仿真专题时间轴" :time="time" v-model:resolution="resolution" v-model:rate="rate" :playing="playing"
      :maximum="maximum" :position="position" :times="times" :loading="timeLoading" :metadata-loading="metadataLoading" :counts="counts" :errors="timeErrors" :all-missing="allMissing"
      @select="temporal.setTime" @seek="temporal.seek" @step="temporal.step" @play="temporal.play" @pause="temporal.pause" @refresh="temporal.refreshAvailability(); temporal.refresh()" />
    <section v-if="result" class="simulation-result panel" aria-label="运行结果对比">
      <header><h2>路径对比</h2><span>{{ snapshot?.request.network.asset_id }}@{{ snapshot?.request.network.version }} · {{ snapshot?.request.origin }} → {{ snapshot?.request.destination }}</span><strong>{{ result.blocked.reachable ? result.metrics.rerouted ? '已绕行' : result.blocked.path.length === 1 ? '起终点相同' : '路径保持' : '阻断后不可达' }}</strong><RunExports :key="result.run_id" :identity="result.run_id" /></header>
      <div class="result-columns"><div class="blue"><h3>基准</h3><strong>{{ number(result.baseline.length_m) }} <small>m</small></strong><span>{{ number(result.baseline.duration_s) }} 秒</span><p>{{ result.baseline.reachable ? result.baseline.path.join(' → ') : '不可达' }}</p></div><div class="orange"><h3>阻断后</h3><strong>{{ number(result.blocked.length_m) }} <small>m</small></strong><span>{{ number(result.blocked.duration_s) }} 秒</span><p>{{ result.blocked.reachable ? result.blocked.path.join(' → ') : '不可达' }}</p></div><div><h3>长度变化</h3><strong>{{ result.metrics.increase_percent === null ? '—' : `${result.metrics.increase_percent >= 0 ? '+' : ''}${number(result.metrics.increase_percent)}%` }}</strong><span>按边速度累计时间</span><p>合成演示，长度使用路网显式权重。</p></div></div>
      <ReplayControls v-if="resultNetwork && !preview" :key="result.run_id" :network="resultNetwork" :result="result" :active="active" @position="showReplay" />
    </section>
    <RunHistoryPanel v-if="historyOpen" :scenes="scenes" :locked="historyLocked" :selected="run?.run_id ?? ''" :revision="historyRevision" :recovery="recovery" @close="historyOpen = false" @select="selectHistory" @rerun="rerunHistory" />
    <div v-if="mapError || notice || mapLayers.some(layer => layer.status === 'error')" class="map-notice panel" role="status"><p>{{ mapError || notice }}</p><p v-for="layer in mapLayers.filter(layer => layer.status === 'error')" :key="layer.id">{{ layer.name }}：{{ layer.error }}</p><button class="text-button" @click="mapError = ''; notice = ''; syncLayers()">刷新场景图层</button></div>
  </section>
</template>

<style scoped>
.simulation-workspace { position: absolute; inset: 0; }
.simulation-config { position: absolute; z-index: 3; left: 24px; top: 84px; bottom: 28px; width: 330px; padding: 22px; overflow-y: auto; }
header, .section-heading, .save-actions, .simulation-tools { display: flex; align-items: center; gap: 12px; }
header, .section-heading { justify-content: space-between; }
h1 { font-size: 23px; margin: 5px 0 0; }
h2, h3 { font-size: 13px; margin: 0; font-weight: 600; }
.synthetic, .hint, small, .save-actions > span, .run-status p { font-size: 11px; color: #73859a; line-height: 1.7; }
.synthetic { margin: 9px 0 22px; }
fieldset { border: 0; padding: 0; margin: 0; min-width: 0; }
fieldset > label, .field-pair label { display: grid; gap: 7px; margin-bottom: 14px; font-size: 12px; color: #435870; }
select, input:not([type=checkbox]) { width: 100%; min-width: 0; padding: 9px 10px; border: 1px solid var(--line); border-radius: 5px; background: white; color: #29405a; }
fieldset:disabled { opacity: .6; }
.field-pair { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }
.section-heading { margin-top: 17px; font-size: 11px; color: #73859a; }
.hint { margin: 8px 0; }
.edge-list { list-style: none; padding: 0; margin: 0; max-height: 205px; overflow-y: auto; }
.edge-list label { display: flex; gap: 9px; align-items: center; padding: 8px 0; font-size: 12px; border-bottom: 1px solid #edf1f6; cursor: pointer; }
.edge-list small { margin-left: auto; }
input[type=checkbox] { accent-color: var(--blue); }
.scene-layers { font-size: 11px; margin-top: 18px; color: #65788e; }
.scene-layers summary { cursor: pointer; margin-bottom: 8px; }
.scene-layers label { display: flex; align-items: center; gap: 7px; padding: 6px 0; }
.scene-layers small { margin-left: auto; }
.scene-layer-controls { display: flex; gap: 8px; align-items: center; }
.scene-layer-controls label { flex-shrink: 0; }
.scene-layer-controls input[type=range] { width: 100%; min-width: 0; padding: 0; }
.scene-layer-controls span { flex-shrink: 0; }
.save-actions { margin-top: 20px; }
.save-actions button { display: inline-flex; align-items: center; gap: 7px; }
.run-button { display: flex; justify-content: center; gap: 8px; width: 100%; margin-top: 13px; padding: 12px; }
.error { color: #b94e46; font-size: 12px; line-height: 1.7; overflow-wrap: anywhere; }
.error button { margin-left: 10px; }
.identity { overflow-wrap: anywhere; font-size: 10px !important; }
.run-status { border-top: 1px solid var(--line); margin-top: 18px; }
.simulation-tools { position: absolute; right: 24px; top: 84px; z-index: 3; padding: 12px; font-size: 11px; }
.simulation-tools button { display: flex; gap: 7px; align-items: center; color: var(--blue); }
.simulation-tools > span { color: #73859a; }
.route-legend { position: absolute; right: 24px; top: 143px; padding: 10px 14px; display: flex; gap: 18px; font-size: 12px; }
.blue { color: #2563eb; } .orange { color: #c77c00; } .red { color: #dc2626; }
.simulation-result { position: absolute; left: 380px; right: 24px; bottom: 28px; padding: 20px 24px; max-height: 48%; overflow-y: auto; }
.simulation-time { left: 380px; right: 24px; bottom: 28px; }
.simulation-time.with-result { bottom: auto; top: 192px; }
.simulation-result header { flex-wrap: wrap; font-size: 11px; color: #73859a; }
.simulation-result header strong { color: #29405a; font-weight: 500; }
.result-columns { display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 24px; margin-top: 18px; }
.result-columns > div { display: grid; gap: 6px; }
.result-columns strong { font-size: 23px; font-weight: 550; }
.result-columns span, .result-columns p { font-size: 11px; line-height: 1.6; margin: 0; }
.result-columns > div:last-child { color: #52657d; }
.map-notice { position: absolute; left: 380px; top: 192px; right: 24px; padding: 10px 16px; font-size: 12px; color: #a55145; }
button:disabled { opacity: .5; cursor: default; }
@media (max-width: 900px) {
  .simulation-config { width: 280px; left: 12px; padding: 16px; }
  .simulation-result, .map-notice { left: 308px; right: 12px; }
  .simulation-time { left: 308px; right: 12px; }
  .simulation-result { padding: 16px; }
  .result-columns { gap: 12px; }
  .result-columns strong { font-size: 19px; }
  .simulation-result header > span { display: none; }
  .simulation-tools, .route-legend { right: 12px; }
}
@media (max-width: 600px) {
  .simulation-workspace { overflow-y: auto; padding-top: 58px; }
  .simulation-config { position: relative; top: auto; left: auto; width: auto; margin: 300px 12px 12px; overflow: visible; }
  .simulation-result { position: relative; inset: auto; margin: 12px; }
  .simulation-time, .simulation-time.with-result { position: relative; inset: auto; margin: 12px; }
  .simulation-tools { top: 75px; }
  .route-legend { top: 128px; }
  .map-notice { position: relative; inset: auto; margin: 12px; }
}
</style>
