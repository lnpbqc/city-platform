import { beforeEach, mock, test } from 'node:test'
import assert from 'node:assert/strict'
import { createRenderer, defineComponent, nextTick } from 'vue'

const clone = value => JSON.parse(JSON.stringify(value))
const deferred = () => { let resolve, reject; const promise = new Promise((yes, no) => { resolve = yes; reject = no }); return { promise, resolve, reject } }
const camera = { longitude: 113.36, latitude: 23.04, height: 800, heading: 0.2, pitch: -0.9, roll: 0, scene_mode: '3d' }
const layer = { layer_id: 'one', asset: { asset_id: 'asset-one', version: '1.0.0' }, map_attached: true, map_visible: false, map_opacity: 0.4, order: 2 }
const network = { asset_id: 'net-001', version: '1.0.0', name: '合成路网', directed: false, crs: 'EPSG:4326', synthetic: true,
  nodes: ['S', 'A', 'T'].map((id, i) => ({ id, coordinates: [113 + i / 100, 23] })),
  edges: [{ id: 'S-A', source: 'S', target: 'A', length_m: 200, speed_mps: 10 }, { id: 'A-T', source: 'A', target: 'T', length_m: 200, speed_mps: 10 }] }
const scene = (id = 'scene-one', overrides = {}) => ({ name: '已存场景', camera: { ...camera, height: 1234 }, layers: [layer],
  network: { asset_id: 'net-001', version: '1.0.0' }, origin: 'S', destination: 'T', blocked_edges: ['A-T'], params: { mode: 'car' }, seed: 14, current_time: null, run_id: null,
  id, version: 3, created_at: '2026-10-26T00:00:00Z', updated_at: '2026-10-26T01:00:00Z', ...overrides })
const record = (status = 'queued', overrides = {}) => ({ run_id: 'run-one', status, scene_id: 'scene-one', scene_version: 1, inputs_sha256: 'hash', model_version: 'routing-1', data_version: 'net-001@1.0.0',
  submitted_at: '2026-10-26T00:00:00Z', started_at: null, finished_at: null, elapsed_ms: null, error: null, trace_id: 'run-trace', ...overrides })
const snapshot = () => ({ request: { scene_id: 'scene-one', network: { asset_id: 'net-001', version: '1.0.0' }, origin: 'S', destination: 'T', blocked_edges: ['A-T'], params: { mode: 'car' }, seed: 14 },
  scene: scene(), model_version: 'routing-1', data_version: 'net-001@1.0.0' })
const result = () => ({ run_id: 'run-one', baseline: { path: ['S', 'A', 'T'], length_m: 400, duration_s: 40, reachable: true },
  blocked: { path: [], length_m: null, duration_s: null, reachable: false }, metrics: { increase_percent: null, rerouted: false }, created_at: '2026-10-26T00:00:01Z' })
class ApiError extends Error { constructor(message, status = 0) { super(message); this.status = status } }
let calls, handlers, storage
beforeEach(() => {
  calls = { save: [], submit: [], rerun: [], run: [], input: [], result: [], cancel: [], scene: [], network: [], catalogs: [] }
  storage = new Map()
  globalThis.window = { localStorage: { getItem: key => storage.get(key) ?? null, setItem: (key, value) => storage.set(key, value), removeItem: key => storage.delete(key) } }
  handlers = {
    scenes: async query => ({ items: [scene()], total: 1, ...query }), networks: async query => ({ items: [network], total: 1, ...query }),
    scene: async id => scene(id), network: async (id, version) => ({ ...network, asset_id: id, version }),
    save: async (body, id, version) => ({ ...clone(body), id: id || 'scene-one', version: id ? version + 1 : 1, created_at: '2026-10-26T00:00:00Z', updated_at: '2026-10-26T01:00:00Z' }),
    submit: async () => record(), rerun: async () => record(), run: async () => record('running'), input: async () => snapshot(), result: async () => result(), cancel: async () => record('cancelled'),
  }
})
mock.module('../src/api.ts', { exports: {
  ApiError,
  getScenes: (query, signal) => { calls.catalogs.push({ kind: 'scenes', signal }); return handlers.scenes(query, signal) },
  getNetworks: (query, signal) => { calls.catalogs.push({ kind: 'networks', signal }); return handlers.networks(query, signal) },
  getScene: (id, signal) => { calls.scene.push({ id, signal }); return handlers.scene(id, signal) },
  getNetwork: (id, version, signal) => { calls.network.push({ id, version, signal }); return handlers.network(id, version, signal) },
  saveScene: (body, id, version, signal) => { calls.save.push({ body: clone(body), id, version, signal }); return handlers.save(body, id, version, signal) },
  submitRun: (body, key, signal) => { calls.submit.push({ body: clone(body), key, signal }); return handlers.submit(body, key, signal) },
  rerunRun: (id, key, signal) => { calls.rerun.push({ id, key, signal }); return handlers.rerun(id, key, signal) },
  getRun: (id, signal) => { calls.run.push({ id, signal }); return handlers.run(id, signal) },
  getRunInput: (id, signal) => { calls.input.push({ id, signal }); return handlers.input(id, signal) },
  getRunResult: (id, signal) => { calls.result.push({ id, signal }); return handlers.result(id, signal) },
  cancelRun: (id, signal) => { calls.cancel.push({ id, signal }); return handlers.cancel(id, signal) },
} })
const { useSimulation } = await import('../src/composables/useSimulation.ts')
const renderer = createRenderer({ createElement: () => ({}), createText: () => ({}), createComment: () => ({}), insert() {}, remove() {}, setText() {}, setElementText() {}, patchProp() {}, parentNode: () => null, nextSibling: () => null })
function setup() {
  let simulation
  let currentCamera = clone(camera), currentLayers = [clone(layer)]
  const app = renderer.createApp(defineComponent({ setup() { simulation = useSimulation(() => currentCamera, () => currentLayers); return () => null } }))
  app.mount({})
  return { app, simulation, camera: value => { currentCamera = value }, layers: value => { currentLayers = value } }
}
const flush = async () => { await new Promise(setImmediate); await nextTick() }

test('initial draft captures layers once and initialization prefers the default network', async () => {
  const { app, simulation } = setup()
  assert.deepEqual([simulation.draft.value.name, simulation.draft.value.seed, simulation.draft.value.layers], ['未命名场景', 0, [layer]])
  await simulation.initialize()
  assert.deepEqual(simulation.draft.value.network, { asset_id: 'net-001', version: '1.0.0' })
  assert.equal(simulation.network.value.synthetic, true)
  assert.deepEqual([simulation.draft.value.origin, simulation.draft.value.destination, simulation.draft.value.blocked_edges], ['S', 'T', []])
  assert.equal(simulation.scenes.value.length, 1)
  app.unmount()
})

test('history opens queued input immediately as a locked snapshot, then explicitly becomes a new editable scene', async () => {
  const { app, simulation } = setup()
  handlers.input = async () => ({ ...snapshot(), request: { ...snapshot().request, origin: 'A', seed: 99 } })
  await simulation.openRun('historical')
  assert.equal(simulation.historical.value, true)
  assert.equal(simulation.editingLocked.value, true)
  assert.equal(simulation.sceneId.value, '')
  assert.equal(simulation.sceneVersion.value, null)
  assert.equal(simulation.draft.value.seed, 99)
  assert.equal(simulation.draft.value.origin, 'A')
  assert.deepEqual(simulation.draft.value.layers, [layer])
  assert.deepEqual(simulation.draft.value.camera, scene().camera)
  assert.ok(simulation.snapshot.value)
  assert.equal(calls.result.length, 0)
  assert.equal(calls.scene.length, 0)
  assert.equal(simulation.busy.value, true)
  simulation.previewDraft()
  assert.equal(simulation.historical.value, true)
  handlers.run = async () => record('failed')
  await simulation.refreshRun()
  simulation.previewDraft()
  assert.equal(simulation.historical.value, false)
  assert.equal(simulation.editingLocked.value, false)
  assert.equal(simulation.run.value, null)
  assert.equal(simulation.draft.value.run_id, null)
  await simulation.save()
  assert.equal(calls.save[0].id, undefined)
  assert.equal(calls.save[0].body.seed, 99)
  assert.equal('scene_id' in calls.save[0].body, false)
  app.unmount()
})

test('late history reads cannot override a newer scope or an unmounted view', async () => {
  const old = deferred()
  handlers.run = id => id === 'old' ? old.promise : Promise.resolve(record('succeeded', { run_id: id }))
  const { app, simulation } = setup()
  const opening = simulation.openRun('old')
  await simulation.openRun('new')
  old.resolve(record('succeeded', { run_id: 'old' }))
  await opening
  assert.equal(simulation.run.value.run_id, 'new')
  assert.equal(calls.run[0].signal.aborted, true)
  await simulation.chooseScene('current')
  assert.equal(simulation.historical.value, false)
  assert.equal(simulation.sceneId.value, 'current')
  const late = deferred()
  handlers.run = () => late.promise
  const unmounting = simulation.openRun('late')
  app.unmount()
  late.resolve(record('succeeded', { run_id: 'late' }))
  await unmounting
  assert.equal(simulation.run.value, null)
})

test('lost rerun responses retry the original source and key without saving or replacing pending work', async () => {
  const { app, simulation } = setup()
  handlers.rerun = async () => { throw new ApiError('NETWORK_ERROR · trace_id: rerun-lost', 0) }
  await simulation.rerun('old/id')
  assert.equal(simulation.submissionPending.value, true)
  assert.equal(calls.save.length, 0)
  await simulation.openRun('other')
  assert.equal(calls.run.length, 0)
  const key = calls.rerun[0].key
  handlers.rerun = async () => record()
  await simulation.submit()
  assert.deepEqual(calls.rerun.map(item => [item.id, item.key]), [['old/id', key], ['old/id', key]])
  assert.equal(calls.save.length, 0)
  assert.equal(simulation.historical.value, true)
  assert.ok(simulation.snapshot.value)
  assert.equal(simulation.submissionPending.value, false)
  assert.equal(simulation.busy.value, true)
  await simulation.rerun('other')
  assert.equal(calls.rerun.length, 2)
  app.unmount()
})

test('history rerun uses a fresh key per confirmed run and keeps unsupported-model errors explicit', async () => {
  const { app, simulation } = setup()
  handlers.rerun = async () => record('succeeded')
  await simulation.rerun('source')
  await simulation.rerun('source')
  assert.notEqual(calls.rerun[0].key, calls.rerun[1].key)
  handlers.rerun = async () => { throw new ApiError('MODEL_VERSION_UNAVAILABLE · trace_id: model', 409) }
  await simulation.rerun('legacy')
  assert.match(simulation.error.value, /MODEL_VERSION_UNAVAILABLE/)
  assert.equal(simulation.submissionPending.value, false)
  assert.equal(calls.save.length, 0)
  app.unmount()
})

test('a confirmed rerun with a failed input fetch can only edit a new scene copy', async () => {
  const { app, simulation } = setup()
  await simulation.chooseScene('current-scene')
  handlers.rerun = async () => record('succeeded', { run_id: 'rerun-new' })
  handlers.input = async () => { throw new ApiError('输入暂不可读 · trace_id: input', 503) }
  await simulation.rerun('historical')
  assert.equal(simulation.run.value.run_id, 'rerun-new')
  assert.equal(simulation.submissionPending.value, false)
  assert.match(simulation.error.value, /trace_id: input/)
  simulation.previewDraft()
  await simulation.save()
  assert.equal(calls.save[0].id, undefined)
  app.unmount()
})

test('saved scenes restore full camera and layers; saving captures current camera without rebinding layers', async () => {
  const context = setup(), { app, simulation } = context
  await simulation.initialize(); await simulation.chooseScene('scene-one')
  assert.deepEqual(simulation.draft.value.camera, scene().camera)
  context.camera({ ...camera, height: 999 }); context.layers([])
  await simulation.save()
  assert.equal(calls.save.at(-1).version, 3)
  assert.equal(calls.save.at(-1).body.camera.height, 999)
  assert.deepEqual(calls.save.at(-1).body.layers, [layer])
  assert.equal(simulation.sceneVersion.value, 4)
  await simulation.save(true)
  assert.equal(calls.save.at(-1).id, undefined)
  app.unmount()
})

test('late scene responses cannot overwrite a newer choice; errors preserve the draft', async () => {
  const old = deferred()
  handlers.scene = id => id === 'old' ? old.promise : Promise.resolve(scene(id))
  const { app, simulation } = setup()
  await simulation.initialize()
  const choosing = simulation.chooseScene('old')
  await simulation.chooseScene('new')
  old.resolve(scene('old', { name: '旧响应' }))
  await choosing
  assert.equal(simulation.sceneId.value, 'new')
  assert.equal(calls.scene[0].signal.aborted, true)
  const before = clone(simulation.draft.value)
  handlers.scene = async () => { throw new ApiError('场景不存在 · trace_id: missing', 404) }
  await simulation.chooseScene('missing')
  assert.deepEqual(simulation.draft.value, before)
  assert.match(simulation.error.value, /trace_id: missing/)
  app.unmount()
})

test('409 save conflicts keep draft edits and its known version without silent overwrite', async () => {
  const { app, simulation } = setup()
  await simulation.initialize(); await simulation.chooseScene('scene-one')
  simulation.draft.value.name = '我的修改'
  handlers.save = async () => { throw new ApiError('SCENE_VERSION_CONFLICT · trace_id: conflict', 409) }
  await simulation.save()
  assert.equal(simulation.sceneVersion.value, 3)
  assert.equal(simulation.draft.value.name, '我的修改')
  assert.match(simulation.error.value, /conflict/)
  app.unmount()
})

test('double submission saves and posts once; busy ignores further submit calls', async () => {
  const saving = deferred()
  const { app, simulation } = setup()
  await simulation.initialize()
  handlers.save = () => saving.promise
  const first = simulation.submit()
  await simulation.submit()
  assert.equal(calls.save.length, 1)
  saving.resolve(scene('scene-one', { version: 1 }))
  await first
  assert.equal(calls.submit.length, 1)
  assert.ok(calls.submit[0].key)
  assert.equal(simulation.busy.value, true)
  await simulation.submit()
  assert.equal(calls.submit.length, 1)
  app.unmount()
})

test('lost POST response retries the exact key and body without saving a new scene version', async () => {
  const { app, simulation } = setup()
  await simulation.initialize()
  handlers.submit = async () => { throw new ApiError('NETWORK_ERROR · trace_id: lost', 0) }
  await simulation.submit()
  assert.equal(simulation.submissionPending.value, true)
  assert.equal(simulation.editingLocked.value, true)
  assert.match(simulation.error.value, /重试/)
  const frozen = clone(calls.submit[0].body), key = calls.submit[0].key
  simulation.draft.value.seed = 999
  await simulation.chooseNetwork('other', '2.0.0')
  assert.equal(calls.network.length, 0)
  await simulation.newScene()
  assert.equal(simulation.sceneId.value, 'scene-one')
  handlers.submit = async () => record()
  await simulation.submit()
  assert.equal(calls.save.length, 1)
  assert.equal(calls.submit[1].key, key)
  assert.deepEqual(calls.submit[1].body, frozen)
  assert.equal(simulation.submissionPending.value, false)
  app.unmount()
})

test('polling uses 500 ms and terminal output retains missing unreachable metrics and original network', async (t) => {
  t.mock.timers.enable({ apis: ['setTimeout'] })
  const { app, simulation } = setup()
  await simulation.initialize(); await simulation.submit()
  handlers.run = async () => record(calls.run.length === 1 ? 'running' : 'succeeded')
  t.mock.timers.tick(499); await flush()
  assert.equal(calls.run.length, 0)
  t.mock.timers.tick(1); await flush()
  assert.equal(calls.run.length, 1)
  t.mock.timers.tick(500); await flush()
  assert.equal(simulation.run.value.status, 'succeeded')
  assert.equal(simulation.result.value.blocked.reachable, false)
  assert.equal(simulation.result.value.blocked.length_m, null)
  assert.equal(simulation.result.value.metrics.increase_percent, null)
  assert.equal(simulation.snapshot.value.request.blocked_edges[0], 'A-T')
  assert.equal(simulation.resultNetwork.value.asset_id, 'net-001')
  const oldKey = calls.submit[0].key
  await simulation.submit()
  assert.notEqual(calls.submit[1].key, oldKey)
  assert.equal(calls.save.length, 2)
  app.unmount()
})

test('same origin and destination is valid and cancellation keeps terminal metadata and snapshot', async () => {
  const { app, simulation } = setup()
  await simulation.initialize()
  simulation.draft.value.destination = 'S'
  await simulation.submit()
  assert.deepEqual([calls.submit[0].body.origin, calls.submit[0].body.destination], ['S', 'S'])
  await simulation.cancel()
  assert.equal(calls.cancel.length, 1)
  assert.equal(simulation.run.value.status, 'cancelled')
  assert.equal(simulation.busy.value, false)
  assert.equal(simulation.result.value, null)
  assert.ok(simulation.snapshot.value)
  app.unmount()
})

test('failed runs retain structured error and original input without fetching a success result', async () => {
  const { app, simulation } = setup()
  await simulation.initialize(); await simulation.submit()
  handlers.run = async () => record('failed', { error: { code: 'MODEL_ERROR', message: '模型失败', detail: null, trace_id: 'run-trace' } })
  await simulation.refreshRun()
  assert.equal(simulation.run.value.error.code, 'MODEL_ERROR')
  assert.equal(simulation.result.value, null)
  assert.equal(calls.result.length, 0)
  assert.ok(simulation.snapshot.value)
  app.unmount()
})

test('poll failures preserve known metadata, stop automatic retries and allow manual refresh', async (t) => {
  t.mock.timers.enable({ apis: ['setTimeout'] })
  const { app, simulation } = setup()
  await simulation.initialize(); await simulation.submit()
  handlers.run = async () => { throw new ApiError('NETWORK_ERROR · trace_id: polling', 0) }
  t.mock.timers.tick(500); await flush()
  assert.match(simulation.error.value, /polling/)
  assert.equal(simulation.run.value.status, 'queued')
  t.mock.timers.tick(2000); await flush()
  assert.equal(calls.run.length, 1)
  handlers.run = async () => record('succeeded')
  await simulation.refreshRun()
  assert.equal(simulation.error.value, '')
  assert.ok(simulation.result.value)
  app.unmount()
})

test('switching scenes and unmounting abort stale run requests and metadata', async () => {
  const old = deferred()
  handlers.scene = async id => scene(id, { run_id: id === 'old' ? 'run-old' : null })
  handlers.run = () => old.promise
  const { app, simulation } = setup()
  await simulation.initialize()
  const choosing = simulation.chooseScene('old')
  await flush()
  await simulation.chooseScene('new')
  assert.equal(calls.run[0].signal.aborted, true)
  old.resolve(record('succeeded', { run_id: 'run-old' }))
  await choosing
  assert.equal(simulation.sceneId.value, 'new')
  assert.equal(simulation.run.value, null)
  assert.equal(simulation.result.value, null)
  const late = deferred()
  handlers.scene = () => late.promise
  const pending = simulation.chooseScene('late')
  app.unmount()
  assert.equal(calls.scene.at(-1).signal.aborted, true)
  late.resolve(scene('late'))
  await pending
  assert.equal(simulation.sceneId.value, 'new')
})

test('last-scene restore failure preserves a new draft; newScene takes current camera and layers', async () => {
  storage.set('city.simulation.scene.v1', 'gone')
  handlers.scene = async () => { throw new ApiError('SCENE_NOT_FOUND · trace_id: gone', 404) }
  const context = setup(), { app, simulation } = context
  const before = clone(simulation.draft.value)
  await simulation.initialize()
  assert.deepEqual(simulation.draft.value, before)
  assert.match(simulation.error.value, /gone/)
  context.camera({ ...camera, height: 2000 }); context.layers([])
  await simulation.newScene()
  assert.equal(simulation.draft.value.name, '未命名场景')
  assert.equal(simulation.draft.value.camera.height, 2000)
  assert.deepEqual(simulation.draft.value.layers, [])
  assert.equal(simulation.sceneId.value, '')
  assert.equal(storage.has('city.simulation.scene.v1'), false)
  app.unmount()
})

test('editing terminal configuration returns to draft preview and never changes saved snapshot data', async () => {
  const { app, simulation } = setup()
  await simulation.initialize(); await simulation.submit()
  handlers.run = async () => record('succeeded')
  await simulation.refreshRun()
  const previous = clone(simulation.snapshot.value)
  simulation.toggleEdge('S-A')
  await flush()
  assert.deepEqual(simulation.draft.value.blocked_edges, ['S-A'])
  assert.equal(simulation.run.value, null)
  assert.equal(simulation.result.value, null)
  assert.equal(simulation.snapshot.value, null)
  assert.deepEqual(previous.request.blocked_edges, ['A-T'])
  app.unmount()
})

test('cancel is single-flight and old polling cannot replace its terminal response', async () => {
  const poll = deferred(), cancellation = deferred()
  const { app, simulation } = setup()
  await simulation.initialize(); await simulation.submit()
  handlers.run = () => poll.promise
  handlers.cancel = () => cancellation.promise
  const refreshing = simulation.refreshRun()
  const cancelling = simulation.cancel()
  await simulation.cancel()
  assert.equal(calls.cancel.length, 1)
  assert.equal(calls.run[0].signal.aborted, true)
  cancellation.resolve(record('cancelled'))
  await cancelling
  poll.resolve(record('running'))
  await refreshing
  assert.equal(simulation.run.value.status, 'cancelled')
  assert.equal(simulation.cancelling.value, false)
  app.unmount()
})

test('scene changes while cancelled input is loading reset the scoped cancellation flag', async () => {
  const input = deferred()
  const { app, simulation } = setup()
  await simulation.initialize(); await simulation.submit()
  handlers.input = () => input.promise
  const cancellation = simulation.cancel()
  await flush()
  assert.equal(simulation.run.value.status, 'cancelled')
  assert.equal(simulation.cancelling.value, true)
  await simulation.chooseScene('another')
  input.resolve(snapshot())
  await cancellation
  assert.equal(simulation.cancelling.value, false)
  assert.equal(simulation.run.value, null)
  assert.equal(simulation.snapshot.value, null)
  app.unmount()
})

test('initialize loads all dropdown pages and unmount removes the scheduled poll', async (t) => {
  t.mock.timers.enable({ apis: ['setTimeout'] })
  const pages = []
  handlers.scenes = async query => {
    pages.push(query.page)
    return { ...query, total: 101, items: Array.from({ length: query.page === 1 ? 100 : 1 }, (_, i) => scene(`scene-${query.page}-${i}`)) }
  }
  const { app, simulation } = setup()
  await simulation.initialize()
  assert.deepEqual(pages, [1, 2])
  assert.equal(simulation.scenes.value.length, 101)
  await simulation.submit()
  app.unmount()
  t.mock.timers.tick(2000); await flush()
  assert.equal(calls.run.length, 0)
})

test('first successful initialization captures a delayed catalog once without overwriting edited drafts', async () => {
  const catalog = deferred()
  handlers.networks = () => catalog.promise
  const context = setup(), { app, simulation } = context
  const initializing = simulation.initialize()
  const resolvedLayer = { ...layer, asset: { asset_id: 'resolved-asset', version: '2.0.0' } }
  context.layers([resolvedLayer]); context.camera({ ...camera, height: 4321 })
  catalog.resolve({ items: [network], total: 1, page: 1, page_size: 100 })
  await initializing
  assert.deepEqual(simulation.draft.value.layers, [resolvedLayer])
  assert.equal(simulation.draft.value.camera.height, 4321)
  context.layers([])
  await simulation.initialize()
  assert.deepEqual(simulation.draft.value.layers, [resolvedLayer])
  app.unmount()
  const edited = setup()
  edited.simulation.draft.value.name = '已编辑草稿'
  edited.layers([]); edited.camera({ ...camera, height: 9999 })
  await edited.simulation.initialize()
  assert.equal(edited.simulation.draft.value.name, '已编辑草稿')
  assert.deepEqual(edited.simulation.draft.value.layers, [layer])
  assert.equal(edited.simulation.draft.value.camera.height, camera.height)
  edited.app.unmount()
})

test('initialization retries and delayed saved-scene reads never replace an edited draft', async t => {
  const context = setup(), { app, simulation } = context
  t.after(() => app.unmount())
  storage.set('city.simulation.scene.v1', 'previous')
  handlers.networks = async () => { throw new ApiError('NETWORK_ERROR · trace_id: first', 0) }
  await simulation.initialize()
  const delayed = deferred()
  handlers.networks = () => delayed.promise
  const retrying = simulation.initialize()
  simulation.draft.value.name = '重试期间编辑'
  simulation.draft.value.origin = 'A'
  simulation.draft.value.blocked_edges = ['S-A']
  const expected = clone(simulation.draft.value)
  delayed.resolve({ items: [network], total: 1, page: 1, page_size: 100 })
  await retrying
  assert.deepEqual(simulation.draft.value, expected)
  assert.equal(calls.scene.length, 0)

  const other = setup(); t.after(() => other.app.unmount())
  const savedScene = deferred()
  handlers.scene = () => savedScene.promise
  const restoringInitial = other.simulation.initialize()
  await flush()
  other.simulation.draft.value.name = '场景 GET 等待期间编辑'
  const untouched = clone(other.simulation.draft.value)
  savedScene.resolve(scene('previous'))
  await restoringInitial
  assert.deepEqual(other.simulation.draft.value, untouched)
  assert.equal(other.simulation.sceneId.value, '')
})

test('read-only recovery preserves draft, fixed scene version and pending POST input while refreshing directories', async t => {
  const { app, simulation } = setup(); t.after(() => app.unmount())
  await simulation.initialize(); await simulation.chooseScene('scene-one')
  simulation.draft.value.name = '未保存配置'
  simulation.draft.value.camera.height = 4321
  simulation.draft.value.current_time = '2026-10-25T01:00:00Z'
  const expected = clone(simulation.draft.value)
  handlers.scenes = async query => ({ ...query, items: [scene('scene-one', { version: 99 })], total: 1 })
  handlers.networks = async query => ({ ...query, items: [], total: 0 })
  await simulation.recover()
  assert.deepEqual(simulation.draft.value, expected)
  assert.equal(simulation.sceneVersion.value, 3)
  assert.equal(simulation.scenes.value[0].version, 99)
  assert.equal(simulation.network.value.asset_id, 'net-001', 'the fixed loaded network survives catalog removal')
  handlers.submit = async () => { throw new ApiError('NETWORK_ERROR · trace_id: post-lost', 0) }
  await simulation.submit()
  const first = clone(calls.submit[0])
  const pendingError = simulation.error.value
  const pendingDraft = clone(simulation.draft.value)
  await simulation.recover()
  assert.equal(calls.submit.length, 1)
  assert.equal(calls.save.length, 1)
  assert.equal(simulation.submissionPending.value, true)
  assert.equal(simulation.error.value, pendingError)
  assert.deepEqual(simulation.draft.value, pendingDraft)
  handlers.submit = async () => record('queued')
  await simulation.submit()
  assert.equal(calls.submit[1].key, first.key)
  assert.deepEqual(calls.submit[1].body, first.body)
})

test('recovery refreshes a known historical run and resumes polling without changing its draft or history state', async t => {
  t.mock.timers.enable({ apis: ['setTimeout'] })
  const { app, simulation } = setup(); t.after(() => app.unmount())
  await simulation.openRun('run-one')
  simulation.draft.value.camera.height = 2345
  simulation.draft.value.current_time = '2026-10-26T00:00:00Z'
  const expected = clone(simulation.draft.value)
  handlers.run = async () => { throw new ApiError('NETWORK_ERROR · trace_id: disconnected', 0) }
  await simulation.refreshRun()
  handlers.run = async () => record('running')
  await simulation.recover()
  assert.deepEqual(simulation.draft.value, expected)
  assert.equal(simulation.historical.value, true)
  const beforePoll = calls.run.length
  handlers.run = async () => record('succeeded')
  t.mock.timers.tick(500); await flush()
  assert.equal(calls.run.length, beforePoll + 1)
  assert.equal(simulation.run.value.status, 'succeeded')
  assert.equal(simulation.result.value.run_id, 'run-one')
  assert.deepEqual(simulation.draft.value, expected)
  assert.equal(calls.submit.length, 0)
  assert.equal(calls.save.length, 0)
})

test('read-only catalog recovery does not interrupt saves and late catalogs cannot replace a newer view', async t => {
  const { app, simulation } = setup(); t.after(() => app.unmount())
  await simulation.initialize()
  const saving = deferred()
  handlers.save = () => saving.promise
  const save = simulation.save()
  const before = calls.catalogs.length
  assert.equal(await simulation.recover(), false)
  assert.equal(calls.catalogs.length, before)
  assert.equal(calls.save[0].signal.aborted, false)
  saving.resolve(scene()); await save
  const delayed = deferred()
  handlers.scenes = () => delayed.promise
  const recovery = simulation.recover()
  const signal = calls.catalogs.at(-2).signal
  await simulation.chooseScene('new')
  delayed.resolve({ items: [scene('old-catalog')], total: 1, page: 1, page_size: 100 })
  assert.equal(await recovery, false)
  assert.equal(signal.aborted, true)
  assert.equal(simulation.sceneId.value, 'new')
  assert.equal(simulation.scenes.value[0].id, 'new')
})
