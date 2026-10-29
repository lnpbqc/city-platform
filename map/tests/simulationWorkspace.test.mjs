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
let assetCalls, sceneCalls, sceneValue, assetHandler, times, submissionError, catalogReads, catalogHandler
beforeEach(() => {
  assetCalls = []
  sceneCalls = []; sceneValue = scene; times = []; submissionError = null; catalogReads = 0
  catalogHandler = async query => ({ ...query, total: 0, items: [] })
  assetHandler = async (id, version) => ({ asset_id: id, version, source_kind: 'upload', type: 'geojson', name: 'area', entry_url: '/pinned.geojson', source: '', status: 'ready' })
  globalThis.window = { localStorage: { getItem: () => null, setItem() {}, removeItem() {} } }
  globalThis.document = { hidden: false, addEventListener() {}, removeEventListener() {} }
})
mock.module('../src/api.ts', { exports: {
  ApiError: class extends Error { constructor(message, status, detail, code, traceId) { super(`${message} ${code ?? ''} ${traceId ?? ''}`); this.status = status; this.code = code } },
  getScenes: async query => { ++catalogReads; return catalogHandler(query) },
  getNetworks: async query => ({ ...query, total: 1, items: [network] }),
  getScene: async (id, signal, version) => { sceneCalls.push({ id, version, signal }); return sceneValue }, getNetwork: async () => network,
  saveScene: async body => ({ ...scene, ...body }), submitRun: async () => { if (submissionError) throw submissionError; return run }, rerunRun: async () => run,
  getRun: async () => ({ ...run, status: 'succeeded' }),
  getRunInput: async () => ({ request: { scene_id: 'scene-one', network: scene.network, origin: 'S', destination: 'T', blocked_edges: [], params: { mode: 'car' }, seed: 0 },
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
const source = await readFile(new URL('../src/components/SimulationWorkspace.vue', import.meta.url), 'utf8')
let compiled = stripTypeScriptTypes(compileScript(parse(source).descriptor, { id: 'simulation-workspace-test' }).content, { mode: 'transform' })
compiled = compiled.replace(/import\s+([\s\S]*?)\s+from\s+(['"])([^'"]+)\2\s*;?/g, (statement, binding, quote, specifier) => {
  if (specifier === 'vue') return `import ${binding} from '${import.meta.resolve('vue')}';`
  if (specifier === '@lucide/vue') return `const ${binding.replace(/\bas\b/g, ':')} = new Proxy({}, { get: () => ({}) });`
  if (specifier.endsWith('.vue')) return `const ${binding} = {};`
  return `import ${binding} from '${new URL('../src/' + specifier.slice(3) + '.ts', import.meta.url).href}';`
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
  const calls = { load: [], paint: [], replay: [], camera: [], temporal: [] }
  const ready = () => state.ready({ initialize: (_region, value) => calls.camera.push(value), getCamera: () => calls.camera.at(-1) ?? camera, setCamera: value => calls.camera.push(value),
    load: async item => { calls.load.push({ asset_id: item.asset_id, asset_version: item.asset_version, source_kind: item.asset_source_kind, order: item.order }); item.attached = true; item.status = 'ready' },
    remove() {}, appearance() {}, syncOrder() {}, showTemporal: (layer, frame) => calls.temporal.push({ layer: layer.id, time: frame?.time }), showReplay: value => calls.replay.push(value), showSimulation: value => calls.paint.push(value?.asset_id ?? null) })
  if (options.ready !== false) { ready(); await flush() }
  return { state, calls, ready, props: app._instance.props, events }
}
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
    resolution: 'day', camera: { ...camera, height: 7777 }, comparison: null }
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
  const address = { page: 'simulation', run_id: 'run-one', resolution: 'hour', comparison: null }
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
  const address = { page: 'simulation', scene_id: scene.id, scene_version: 1, resolution: 'hour', comparison: null }
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
