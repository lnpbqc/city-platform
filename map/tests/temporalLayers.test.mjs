import { beforeEach, mock, test } from 'node:test'
import assert from 'node:assert/strict'
import { createRenderer, defineComponent, nextTick, ref } from 'vue'

const deferred = () => { let resolve; return { promise: new Promise(yes => { resolve = yes }), resolve: value => resolve(value) } }
let requests, timeCalls, fetchFrame
beforeEach(() => {
  requests = []; timeCalls = []
  fetchFrame = async query => ({ layer_id: query.layer_id, asset: { asset_id: query.asset_id, version: query.version }, time: query.time, resolution: query.resolution,
    unit: 'cm', items: [{ object_id: 'point', geometry: { type: 'Point', coordinates: [113, 23] }, value: 0, missing: false }] })
})
mock.module('../src/api.ts', { exports: {
  getLayerTimes: async (id, query, signal) => { timeCalls.push({ id, query, signal }); return ['2026-10-25T00:00:00Z', '2026-10-25T01:00:00Z'] },
  getTimeSeries: (query, signal) => { requests.push({ query, signal }); return fetchFrame(query) },
} })
const { useTemporalLayers } = await import('../src/composables/useTemporalLayers.ts')
const renderer = createRenderer({ createElement: () => ({}), createText: () => ({}), createComment: () => ({}), insert() {}, remove() {}, setText() {}, setElementText() {}, patchProp() {}, parentNode: () => null, nextSibling: () => null })
const flush = async () => { await new Promise(setImmediate); await nextTick() }
function setup(t) {
  let state
  const calls = []
  const layers = ref([{ id: 'static', static: true, attached: true, status: 'ready' },
    { id: 'points', static: false, attached: true, status: 'ready', asset_id: 'asset', asset_version: '1.0.0', campus: 'university-town' }])
  const controller = { showTemporal: (layer, frame) => calls.push({ id: layer.id, frame }) }
  const app = renderer.createApp(defineComponent({ setup() { state = useTemporalLayers(() => layers.value, () => controller); return () => null } }))
  app.mount({}); t.after(() => app.unmount())
  return { state, calls, layers, app }
}
test('only dynamic pinned layers fetch values; changing time reuses resources and keeps zero', async t => {
  const { state, calls, layers } = setup(t)
  await flush()
  assert.equal(timeCalls.length, 1)
  assert.equal(timeCalls[0].query.version, '1.0.0')
  assert.equal(requests.length, 1)
  assert.equal(state.frames.value.points.items[0].value, 0)
  assert.equal(state.allMissing.value, false)
  state.seek(1); await flush()
  assert.equal(requests.length, 2)
  assert.equal(timeCalls.length, 1, 'time changes do not reload availability or asset files')
  assert.ok(calls.every(call => call.id === 'points'))
  layers.value[1].status = 'loading'; await flush()
  layers.value[1].status = 'ready'; await flush()
  assert.equal(requests.length, 2)
  assert.equal(calls.at(-1).frame.time, '2026-10-25T01:00:00.000Z')
})
test('late responses are discarded, missing stays null, failures hide stale values and unmount aborts', async t => {
  const { state, calls, app } = setup(t)
  await flush()
  const old = deferred()
  fetchFrame = query => query.time.includes('00:30') ? old.promise : Promise.resolve({ layer_id: 'points', asset: { asset_id: 'asset', version: '1.0.0' },
    time: query.time, resolution: query.resolution, unit: 'cm', items: [{ object_id: 'point', geometry: null, value: null, missing: true }] })
  state.setTime('2026-10-25T00:30:00Z'); await flush()
  const oldSignal = requests.at(-1).signal
  state.seek(1); await flush()
  assert.equal(oldSignal.aborted, true)
  assert.equal(state.allMissing.value, true)
  old.resolve({ layer_id: 'points', items: [{ value: 99, missing: false }] }); await flush()
  assert.equal(state.frames.value.points.items[0].value, null)
  fetchFrame = async () => { throw new Error('时序不可用 (TIMESERIES_UNAVAILABLE · trace_id: example)') }
  state.seek(0); await flush()
  assert.match(state.errors.value.points, /trace_id: example/)
  assert.equal(calls.at(-1).frame, null)
  const pending = deferred(); fetchFrame = () => pending.promise
  state.seek(1); await flush()
  const signal = requests.at(-1).signal
  app.unmount()
  assert.equal(signal.aborted, true)
  pending.resolve({ layer_id: 'points', items: [] }); await flush()
})
