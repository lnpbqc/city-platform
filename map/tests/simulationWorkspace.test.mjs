import { beforeEach, mock, test } from 'node:test'
import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import { stripTypeScriptTypes } from 'node:module'
import { parse, compileScript } from 'vue/compiler-sfc'
import { createRenderer, nextTick } from 'vue'

const camera = { longitude: 113, latitude: 23, height: 800, heading: 0, pitch: -1, roll: 0, scene_mode: '3d' }
const layer = { layer_id: 'scene-area', asset: { asset_id: 'area', version: '1.0.0' }, map_attached: true, map_visible: true, map_opacity: 0.4, order: 2 }
const network = { asset_id: 'net-001', version: '1.0.0', name: 'net', directed: false, crs: 'EPSG:4326', synthetic: true,
  nodes: [{ id: 'S', coordinates: [113, 23] }, { id: 'T', coordinates: [113.01, 23] }],
  edges: [{ id: 'S-T', source: 'S', target: 'T', length_m: 100, speed_mps: 10 }] }
const scene = { id: 'scene-one', version: 1, created_at: '2026-10-27T00:00:00Z', updated_at: '2026-10-27T00:00:00Z',
  name: 'scene', camera, layers: [layer], network: { asset_id: 'net-001', version: '1.0.0' }, origin: 'S', destination: 'T',
  blocked_edges: [], params: { mode: 'car' }, seed: 0, current_time: null, run_id: null }
const run = { run_id: 'run-one', scene_id: 'scene-one', scene_version: 1, status: 'queued', inputs_sha256: 'hash', model_version: 'routing-1',
  data_version: 'net-001@1.0.0', submitted_at: '2026-10-27T00:00:00Z', started_at: null, finished_at: null, elapsed_ms: null, error: null, trace_id: 'trace' }
const result = { run_id: 'run-one', baseline: { path: ['S', 'T'], length_m: 100, duration_s: 10, reachable: true },
  blocked: { path: ['S', 'T'], length_m: 100, duration_s: 10, reachable: true }, metrics: { increase_percent: 0, rerouted: false }, created_at: '2026-10-27T00:00:01Z' }
let assetCalls, sceneCalls, sceneValue, assetHandler, times, submissionError, catalogReads, catalogHandler, runWeather
beforeEach(() => {
  assetCalls = []
  sceneCalls = []; sceneValue = scene; times = []; submissionError = null; catalogReads = 0
  runWeather = undefined
  catalogHandler = async query => ({ ...query, total: 0, items: [] })
  assetHandler = async (id, version) => ({ asset_id: id, version, source_kind: 'upload', type: 'geojson', name: 'area', entry_url: '/pinned.geojson', source: '', status: 'ready' })
  globalThis.window = { innerWidth: 1440, addEventListener() {}, removeEventListener() {}, localStorage: { getItem: () => null, setItem() {}, removeItem() {} } }
  globalThis.document = { hidden: false, addEventListener() {}, removeEventListener() {} }
})
mock.module('../src/api/api.ts', { exports: {
  getDisplayRegions: async () => [], saveDisplayRegion: async () => {}, deleteDisplayRegion: async () => {},
  ApiError: class extends Error { constructor(message, status, detail, code, traceId) { super(`${message} ${code ?? ''} ${traceId ?? ''}`); this.status = status; this.code = code } },
  getScenes: async query => { ++catalogReads; return catalogHandler(query) },
  getNetworks: async query => ({ ...query, total: 1, items: [network] }),
  getScene: async (id, signal, version) => { sceneCalls.push({ id, version, signal }); return sceneValue }, getNetwork: async () => network,
  saveScene: async body => ({ ...scene, ...body }), submitRun: async () => { if (submissionError) throw submissionError; return run }, rerunRun: async () => run,
  getRun: async () => ({ ...run, status: 'succeeded' }),
  getRunInput: async () => ({ request: { scene_id: 'scene-one', network: scene.network, origin: 'S', destination: 'T', blocked_edges: [], params: { mode: 'car' }, seed: 0, weather: runWeather },
    scene, model_version: 'routing-1', data_version: 'net-001@1.0.0' }),
  getRunResult: async () => result, cancelRun: async () => ({ ...run, status: 'cancelled' }),
  getAssetVersion: async (id, version) => {
    assetCalls.push({ id, version })
    return assetHandler(id, version)
  },
  getLayerTimes: async () => times,
  getObjects: async () => ({ total: 1, items: [], page: 1, page_size: 1 }),
  getTimeSeries: async query => ({ ...query, unit: 'cm', asset: { asset_id: 'area', version: '1.0.0' }, items: [{ object_id: 'one', value: 0, missing: false, geometry: null }] }),
} })

// Exercise the real SFC setup and watchers without a browser or WebGL context.
const source = await readFile(new URL('../src/views/SimulationWorkspace.vue', import.meta.url), 'utf8')
let compiled = stripTypeScriptTypes(compileScript(parse(source).descriptor, { id: 'simulation-workspace-test' }).content, { mode: 'transform' })
compiled = compiled.replace(/import\s+([\s\S]*?)\s+from\s+(['"])([^'"]+)\2\s*;?/g, (statement, binding, quote, specifier) => {
  if (specifier === 'vue') return `import ${binding} from '${import.meta.resolve('vue')}';`
  if (specifier === '@lucide/vue') return `const ${binding.replace(/\bas\b/g, ':')} = new Proxy({}, { get: () => ({}) });`
  if (specifier.endsWith('.vue')) return `const ${binding} = {};`
  return `import ${binding} from '${new URL(specifier + '.ts', new URL('../src/views/SimulationWorkspace.vue', import.meta.url)).href}';`
})
const component = (await import('data:text/javascript;base64,' + Buffer.from(compiled).toString('base64'))).default
component.render = () => null
const renderer = createRenderer({ createElement: () => ({}), createText: () => ({}), createComment: () => ({}), insert() {}, remove() {}, setText() {}, setElementText() {}, patchProp() {}, parentNode: () => null, nextSibling: () => null })
const flush = async () => { await new Promise(setImmediate); await nextTick() }
async function setup(t, options = {}) {
  const events = []
  const app = renderer.createApp(component, { active: true, recovery: 0, onRunChanged: () => events.push('runChanged'), backend: options.backend ?? 'online', layers: [{ id: 'scene-area', asset_id: 'area', asset_version: options.currentVersion ?? '1.0.0',
    attached: true, visible: true, opacity: 1, order: 2, orderable: true, type: 'geojson', category: '专题', static: options.dynamic ? false : true,
    unit: 'cm', legend: [{ label: '0 cm', color: '#dbeafe' }] }] })
  app.mount({})
  t.after(() => app.unmount())
  await flush()
  const state = app._instance.setupState
  const calls = { load: [], paint: [], replay: [], camera: [], temporal: [], placement: [] }
  const ready = () => state.ready({ initialize: (_region, value) => calls.camera.push(value), getCamera: () => calls.camera.at(-1) ?? camera, setCamera: value => calls.camera.push(value),
    getWeatherPoint: () => null,
    load: async item => {
      calls.load.push({ asset_id: item.asset_id, asset_version: item.asset_version, source_kind: item.asset_source_kind, order: item.order })
      if (item.type === '3dtiles') calls.placement.push({ offset: item.tiles_height_offset_m, anchor: item.tiles_ground_anchor, align: item.tiles_align_to_terrain })
      item.attached = true; item.status = 'ready'
    },
    remove() {}, appearance() {}, setRoadMaxLevel(layer, value) { layer.road_max_level = value },
    setTilesPlacement(layer, value) { Object.assign(layer, value) },
    syncOrder() {}, showTemporal: (layer, frame) => calls.temporal.push({ layer: layer.id, time: frame?.time }), showReplay: value => calls.replay.push(value), showSimulation: value => calls.paint.push(value?.asset_id ?? null) })
  if (options.ready !== false) { ready(); await flush() }
  return { state, calls, ready, props: app._instance.props, events }
}
test('simulation exposes the ready controller to its basemap cards', async t => {
  const { state } = await setup(t)
  assert.equal(typeof state.basemapController?.getCamera, 'function')
  assert.match(source, /<BasemapSwitcher[^>]*:controller="basemapController"/)
})
test('simulation sidebar tabs switch without clearing the draft or result at every width', async t => {
  const { state } = await setup(t)
  state.viewportWidth = 1024
  state.draft.name = '保留我的配置'
  assert.equal(state.configVisible, true)
  await succeeded(state)
  assert.equal(state.resultVisible, true)
  assert.equal(state.configVisible, false)
  state.openConfig()
  assert.equal(state.configVisible, true)
  assert.equal(state.resultVisible, false)
  assert.equal(state.draft.name, '保留我的配置')
  assert.ok(state.result)
  state.viewportWidth = 1440
  assert.equal(state.resultVisible, false)
  state.selectPane('history')
  assert.equal(state.historyVisited, true)
  assert.equal(state.configVisible, false)
  state.selectPane('result')
  assert.equal(state.resultVisible, true)
  state.viewportWidth = 1024
  state.activePane = 'result'
  state.editConfiguration()
  assert.equal(state.configVisible, true)
})

test('mobile sidebar closes on Escape and restores focus without losing the selected pane', async t => {
  window.innerWidth = 390
  const { state } = await setup(t)
  assert.equal(state.sidebarOpen, false)
  let restored = 0, prevented = 0
  state.panelTrigger = { focus() { restored++ } }
  state.openSidebar()
  state.selectPane('history')
  state.sidebarKeydown({ key: 'Escape', defaultPrevented: false, preventDefault() { prevented++ } })
  await flush()
  assert.equal(state.sidebarOpen, false)
  assert.equal(state.activePane, 'history')
  assert.equal(restored, 1)
  assert.equal(prevented, 1)
})

test('sidebar tab keys wrap and move focus while preserving the draft', async t => {
  const { state } = await setup(t)
  state.draft.name = '保留草稿'
  let focused = -1, prevented = 0
  const tabs = [0, 1, 2].map(index => ({ focus() { focused = index } }))
  const press = key => state.navigatePanes({ key, preventDefault() { prevented++ }, currentTarget: { querySelectorAll: () => tabs } })
  press('ArrowLeft')
  assert.equal(state.activePane, 'history')
  assert.equal(state.historyVisited, true)
  assert.equal(focused, 2)
  press('ArrowRight')
  assert.equal(state.activePane, 'config')
  assert.equal(focused, 0)
  press('End')
  assert.equal(focused, 2)
  press('Home')
  assert.equal(focused, 0)
  assert.equal(prevented, 4)
  assert.equal(state.draft.name, '保留草稿')
})

test('mobile focus stays within visible enabled drawer controls', async t => {
  window.innerWidth = 390
  const { state } = await setup(t)
  state.openSidebar()
  await flush()
  let focused = '', prevented = 0
  const control = (name, visible = true, disabled = false) => ({
    getClientRects: () => visible ? [{}] : [], matches: () => disabled,
    focus() { focused = name },
  })
  const first = control('first'), last = control('last')
  state.sidebar = { querySelectorAll: () => [control('hidden', false), first, last, control('disabled', true, true)] }
  document.activeElement = last
  state.sidebarKeydown({ key: 'Tab', defaultPrevented: false, shiftKey: false, preventDefault() { prevented++ } })
  assert.equal(focused, 'first')
  document.activeElement = first
  state.sidebarKeydown({ key: 'Tab', defaultPrevented: false, shiftKey: true, preventDefault() { prevented++ } })
  assert.equal(focused, 'last')
  assert.equal(prevented, 2)
})

test('shrinking to mobile restores focus when the desktop sidebar is hidden', async t => {
  const { state } = await setup(t)
  let focused = 0
  const input = {}
  document.activeElement = input
  state.sidebar = { contains: element => element === input, querySelector: () => null }
  state.panelTrigger = { focus() { focused++ } }
  state.selectPane('history')
  window.innerWidth = 390
  state.resizeLayout()
  await flush()
  assert.equal(state.sidebarOpen, false)
  assert.equal(state.activePane, 'history')
  assert.equal(focused, 1)
  window.innerWidth = 1440
  state.resizeLayout()
  document.activeElement = {}
  window.innerWidth = 390
  state.resizeLayout()
  await flush()
  assert.equal(focused, 1, 'resizing does not move focus away from controls outside the sidebar')
})

test('opening a historical run selects the result tab and keeps history mounted for returning', async t => {
  const { state } = await setup(t)
  state.selectPane('history')
  await state.selectHistory('run-one'); await flush()
  assert.equal(state.activePane, 'result')
  assert.equal(state.historical, true)
  assert.equal(state.historyVisited, true)
  assert.ok(state.result)
  state.selectPane('config')
  assert.equal(state.resultVisible, false)
  state.selectPane('result')
  assert.ok(state.result)
})

test('automatic result selection moves focus out of hidden content without taking focus from the map', async t => {
  const { state } = await setup(t)
  const input = {}, mapControl = {}
  let focused = 0
  const resultTab = { focus() { focused++; document.activeElement = resultTab } }
  state.selectPane('history')
  state.sidebar = { querySelector: selector => {
    if (selector === '#simulation-pane-history') return { contains: element => element === input }
    if (selector === '[role="tab"][aria-selected="true"]') return resultTab
    return null
  } }
  document.activeElement = input
  await succeeded(state)
  assert.equal(state.activePane, 'result')
  assert.equal(focused, 1)
  assert.equal(document.activeElement, resultTab)

  state.selectPane('history')
  document.activeElement = mapControl
  await state.selectHistory('run-one'); await flush()
  assert.equal(state.activePane, 'result')
  assert.equal(focused, 1, 'opening a result does not take focus from map controls')
  assert.equal(document.activeElement, mapControl)

  state.selectPane('history')
  document.activeElement = input
  await state.selectHistory('run-one'); await flush()
  assert.equal(focused, 2, 'opening history moves focus out of the hidden history pane')
  assert.equal(document.activeElement, resultTab)
})
test('a historical result arriving before map readiness restores replay positions when ready', async t => {
  const { state, calls, ready } = await setup(t, { ready: false })
  await state.openRun('run-one')
  await flush()
  const positions = { baseline: [113.01, 23], blocked: [113.005, 23] }
  state.showReplay(positions)
  assert.equal(calls.replay.length, 0)
  ready()
  assert.deepEqual(calls.replay.at(-1), positions)
  state.editConfiguration()
  await flush()
  assert.equal(state.historical, false)
  assert.equal(state.sceneId, '')
  assert.deepEqual(calls.replay.at(-1), { baseline: null, blocked: null })
})

test('opening and leaving a run switches between its saved weather and the session mode', async t => {
  const { state } = await setup(t)
  state.weatherMode = 'rain'
  t.after(() => { state.weatherMode = 'auto' })
  assert.deepEqual(state.shownWeather, { source: 'manual', effect: 'rain' })
  runWeather = { source: 'manual', effect: 'fog' }
  await state.openRun('run-one')
  await flush()
  assert.equal(state.fixedWeather, true)
  assert.deepEqual(state.shownWeather, runWeather)
  assert.equal('weather' in state.draft, false)
  state.editConfiguration()
  await flush()
  assert.deepEqual(state.shownWeather, { source: 'manual', effect: 'rain' })
  runWeather = undefined
  await state.openRun('run-one')
  await flush()
  assert.deepEqual(state.shownWeather, { source: 'none', effect: 'none' })
  runWeather = { source: 'open-meteo', effect: 'none', reading: { latitude: 23, longitude: 113, code: 3, is_day: true, valid_at: '2026-01-01T00:15:00Z' } }
  await state.openRun('run-one')
  await flush()
  assert.deepEqual(state.shownWeather, runWeather, 'legacy snapshots keep their saved effect instead of remapping it')
})
async function succeeded(state) { await state.submit(); await state.refreshRun(); await flush(); assert.equal(state.preview, false); assert.ok(state.result) }

test('editing seed after a result returns the real SFC map to draft preview', async t => {
  const { state, calls } = await setup(t)
  await succeeded(state)
  state.draft.seed = 1
  await flush()
  assert.equal(state.result, null)
  assert.equal(state.preview, true)
  assert.equal(state.graph.asset_id, 'net-001')
  assert.equal(calls.paint.at(-1), 'net-001')
})

test('a fresh submission after a result keeps the draft graph while queued', async t => {
  const { state, calls } = await setup(t)
  await succeeded(state)
  await state.submit()
  await flush()
  assert.equal(state.run.status, 'queued')
  assert.equal(state.preview, true)
  assert.equal(calls.paint.at(-1), 'net-001')
})

test('restored scene loads its pinned asset version and preserves source kind and order', async t => {
  const { state, calls, ready } = await setup(t, { currentVersion: '2.0.0', ready: false })
  await state.chooseScene('scene-one')
  ready(); await flush()
  assert.deepEqual(assetCalls, [{ id: 'area', version: '1.0.0' }])
  assert.deepEqual(calls.load, [{ asset_id: 'area', asset_version: '1.0.0', source_kind: 'upload', order: 2 }])
})

test('map captures model placement and the simulation restores it from the pinned scene', async t => {
  const { captureLayers, prepareSceneLayers } = await import('../src/simulation/sceneLayers.ts')
  const anchor = { longitude: 113.36, latitude: 23.04, height: 25 }
  const [captured] = captureLayers([{ id: layer.layer_id, type: '3dtiles', asset_id: 'area', asset_version: '1.0.0',
    attached: true, visible: true, opacity: 0.4, order: 2, tiles_height_offset_m: -3, tiles_ground_anchor: anchor }])
  assert.equal(captured.tiles_height_offset_m, -3)
  assert.deepEqual(captured.tiles_ground_anchor, anchor)
  assert.equal(captured.tiles_align_to_terrain, true)
  sceneValue = { ...scene, layers: [captured] }
  assetHandler = async (id, version) => ({ asset_id: id, version, source_kind: 'upload',
    type: '3dtiles', name: 'model', entry_url: '/tileset.json', source: '', status: 'ready' })
  const { state, calls, ready } = await setup(t, { ready: false })
  await state.chooseScene('scene-one')
  ready(); await flush()
  assert.deepEqual(calls.placement, [{ offset: -3, anchor, align: true }])
  assert.deepEqual(state.draft.layers[0].tiles_ground_anchor, anchor)
  const [automatic] = await prepareSceneLayers([{ ...captured, tiles_ground_anchor: null }], [])
  const [legacy] = await prepareSceneLayers([{ ...layer, tiles_height_offset_m: 4 }], [])
  const [legacyManual] = await prepareSceneLayers([{ ...layer, tiles_ground_anchor: anchor }], [])
  const [disabled] = await prepareSceneLayers([{ ...captured, tiles_align_to_terrain: false }], [])
  assert.equal(automatic.tiles_align_to_terrain, true)
  assert.equal(automatic.tiles_ground_anchor, null)
  assert.equal(legacy.tiles_align_to_terrain, false)
  assert.equal(legacy.tiles_height_offset_m, 4)
  assert.equal(legacyManual.tiles_align_to_terrain, true)
  assert.deepEqual(legacyManual.tiles_ground_anchor, anchor)
  assert.equal(disabled.tiles_align_to_terrain, false)
})

test('a saved scene uses the current model revision and its baked terrain reference', async () => {
  const { prepareSceneLayers } = await import('../src/simulation/sceneLayers.ts')
  const anchor = { longitude: 94, latitude: 29, height: 2980 }
  assetHandler = async (id, version) => ({ asset_id: id, version, source_kind: 'upload', type: '3dtiles',
    name: 'model', entry_url: '/data-files/area/tileset.json', source: '', status: 'ready',
    revision: 2, tiles_calibrated: true, tiles_terrain_anchor: anchor })
  const [model] = await prepareSceneLayers([{ ...layer, tiles_height_offset_m: 20 }], [])
  assert.equal(model.asset_version, '1.0.0')
  assert.equal(model.tiles_revision, 2)
  assert.deepEqual(model.tiles_terrain_anchor, anchor)
  assert.equal(model.tiles_height_offset_m, 0)
})

test('configuration stays locked until the initial catalog and simulation directories are ready', async t => {
  const { state, props } = await setup(t, { backend: 'loading' })
  assert.equal(state.loading, false, 'simulation initialize has not begun before the layer catalog')
  assert.equal(state.configurationLocked, true)
  props.backend = 'online'
  await flush()
  assert.equal(state.configurationLocked, false)
  assert.equal(state.draft.layers[0].asset.asset_id, 'area')
})

test('a full workspace restores its own pinned scene and run without replacing it with the run input scene', async t => {
  times = ['2026-10-25T00:00:00Z', '2026-10-26T01:00:00Z']
  const saved = { ...scene, id: 'bookmark-copy', version: 7, seed: 44, run_id: 'run-one',
    camera: { ...camera, height: 3333 }, layers: [{ ...layer, map_opacity: 0.25 }], current_time: '2026-10-25T01:00:00Z' }
  sceneValue = saved
  const { state } = await setup(t, { dynamic: true })
  assert.equal(state.isReady(), true)
  const address = { page: 'simulation', scene_id: saved.id, scene_version: 7, run_id: 'run-one', time: '2026-10-26T01:00:00Z',
    resolution: 'day', camera: { ...camera, height: 7777 } }
  await state.restoreWorkspace(saved, address); await flush()
  const capture = state.captureWorkspace()
  assert.equal(sceneCalls.at(-1).version, 7)
  assert.equal(state.sceneId, 'bookmark-copy')
  assert.equal(capture.scene.seed, 44, 'saved scene configuration survives the fixed run input')
  assert.equal(capture.scene.layers[0].map_opacity, 0.25)
  assert.equal(capture.camera.height, 7777)
  assert.equal(capture.time, '2026-10-25T16:00:00.000Z')
  assert.equal(capture.resolution, 'day')
  assert.equal(capture.run_id, 'run-one')
  assert.equal(state.run.status, 'succeeded')
  assert.equal(state.result.run_id, 'run-one')
  assert.equal(state.mapLayers[0].static, false)
  assert.equal(state.mapLayers[0].unit, 'cm')
  assert.equal(state.mapLayers[0].legend[0].color, '#dbeafe')
})

test('run-only links restore historical inputs and explicit scene/run conflicts leave the draft untouched', async t => {
  const { state } = await setup(t)
  const address = { page: 'simulation', run_id: 'run-one', resolution: 'hour' }
  await state.restoreWorkspace(null, address); await flush()
  assert.equal(state.historical, true)
  assert.equal(state.captureWorkspace().run_id, 'run-one')
  const previous = JSON.stringify(state.draft)
  await assert.rejects(state.restoreWorkspace(scene, address), /运行 ID/)
  assert.equal(JSON.stringify(state.draft), previous)
})

test('missing pinned resources and superseded resource reads cannot overwrite the existing simulation draft', async t => {
  const { state } = await setup(t)
  state.draft.name = '保留当前草稿'
  assetHandler = async () => { throw new Error('ASSET_NOT_FOUND · trace_id: missing') }
  const address = { page: 'simulation', scene_id: scene.id, scene_version: 1, resolution: 'hour' }
  await assert.rejects(state.restoreWorkspace(scene, address), /ASSET_NOT_FOUND/)
  assert.equal(state.draft.name, '保留当前草稿')
  let release
  assetHandler = () => new Promise(resolve => { release = resolve })
  const restoring = state.restoreWorkspace(scene, address)
  state.cancelRestore()
  release({ asset_id: 'area', version: '1.0.0', source_kind: 'upload', type: 'geojson', name: 'old', entry_url: '/old.geojson', status: 'ready' })
  await assert.rejects(restoring, /新选择/)
  assert.equal(state.draft.name, '保留当前草稿')
})

test('capture rejects an unknown POST result and waits for both map and initialization readiness', async t => {
  const { state, ready, props } = await setup(t, { backend: 'loading', ready: false })
  assert.equal(state.isReady(), false)
  ready()
  assert.equal(state.isReady(), false)
  assert.throws(() => state.captureWorkspace(), /正在读取/)
  props.backend = 'online'; await flush()
  assert.equal(state.isReady(), true)
  submissionError = new Error('NETWORK_ERROR · trace_id: lost')
  await state.submit()
  assert.equal(state.submissionPending, true)
  assert.throws(() => state.captureWorkspace(), /确认提交/)
})

test('recovery props refresh read-only directories without replacing simulation edits and run changes notify statistics', async t => {
  const { state, props, events, calls } = await setup(t)
  state.draft.name = '离线期间保留的草稿'
  state.draft.camera.height = 4567
  const before = catalogReads
  const cameraBefore = calls.camera.at(-1)
  props.recovery = 1
  await flush(); await flush()
  assert.equal(catalogReads, before + 1)
  assert.equal(state.draft.name, '离线期间保留的草稿')
  assert.equal(calls.camera.at(-1), cameraBefore)
  await state.openRun('run-one'); await flush()
  assert.ok(events.includes('runChanged'))
})

test('automatic initial time availability cannot cancel a delayed remembered-scene restore', async t => {
  let release
  catalogHandler = () => new Promise(resolve => { release = resolve })
  times = ['2026-10-25T00:00:00Z', '2026-10-25T01:00:00Z']
  sceneValue = { ...scene, name: '记住的场景', current_time: '2026-10-25T01:00:00Z' }
  window.localStorage.getItem = () => 'scene-one'
  const { state } = await setup(t, { dynamic: true })
  await flush()
  assert.ok(state.time, 'the map can receive time availability before the scene directory resolves')
  assert.equal(state.draft.current_time, null, 'automatic initialization does not mark the pristine draft as edited')
  release({ total: 0, items: [], page: 1, page_size: 100 })
  await flush(); await flush()
  assert.equal(state.draft.name, '记住的场景')
  assert.equal(sceneCalls.at(-1).id, 'scene-one')
  assert.equal(Date.parse(state.draft.current_time), Date.parse('2026-10-25T01:00:00Z'))
})
