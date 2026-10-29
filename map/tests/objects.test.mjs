import { beforeEach, mock, test } from 'node:test'
import assert from 'node:assert/strict'
import { createRenderer, defineComponent, nextTick, ref } from 'vue'

const deferred = () => {
  let resolve, reject
  const promise = new Promise((yes, no) => { resolve = yes; reject = no })
  return { promise, resolve, reject }
}
let listCalls, detailCalls, areaCalls, listRequest, detailRequest, areaRequest
const object = (id, options = {}) => ({
  object_id: id, asset: { asset_id: 'asset-one', version: '1.0.0' }, layer_id: 'first',
  type: 'building', name: null, height_m: null, level: null, semantic_source: 'dataset', confidence: null,
  coordinates: [113, 23], geometry: { type: 'Point', coordinates: [113, 23] }, properties: { name: '原始属性' }, feature_index: 0,
  ...options,
})
const pageOf = (items, query, total = items.length) => ({ items, total, page: query.page, page_size: query.page_size })
beforeEach(() => {
  listCalls = []; detailCalls = []; areaCalls = []
  listRequest = async query => pageOf([object('one')], query)
  detailRequest = async id => object(id)
  areaRequest = async query => pageOf([], query)
})
mock.module('../src/api.ts', {
  exports: {
    getObjects: (query, signal) => { listCalls.push({ ...query, signal }); return listRequest(query, signal) },
    getObject: (id, signal, temporal) => { detailCalls.push({ id, signal, temporal }); return detailRequest(id, signal, temporal) },
    selectObjects: (query, geometry, signal) => { areaCalls.push({ ...query, geometry: structuredClone(geometry), signal }); return areaRequest(query, geometry, signal) },
  },
})
const { useObjects } = await import('../src/composables/useObjects.ts')
const renderer = createRenderer({ createElement: () => ({}), createText: () => ({}), createComment: () => ({}), insert() {}, remove() {}, setText() {}, setElementText() {}, patchProp() {}, parentNode: () => null, nextSibling: () => null })
const first = { id: 'first', name: '第一层', type: 'geojson', attached: true, asset_id: 'asset-one', asset_version: '1.0.0', campus: 'university-town' }
const second = { ...first, id: 'second', asset_id: 'asset-two' }
function setup(initial = [first, second], getTime = () => null) {
  let objects
  const layers = ref(structuredClone(initial))
  const app = renderer.createApp(defineComponent({ setup() { objects = useObjects(() => layers.value, getTime); return () => null } }))
  app.mount({})
  return { app, objects, layers }
}
const flush = async () => { await new Promise(setImmediate); await nextTick() }
const polygon = { type: 'Polygon', coordinates: [[[112, 22], [114, 22], [114, 24], [112, 22]]] }

test('dynamic object lists and selected details follow the clock while static queries remain unchanged', async t => {
  const time = ref({ time: '2026-10-25T00:00:00Z', resolution: 'hour' })
  detailRequest = async (id, _signal, temporal) => object(id, { temporal: { ...temporal, value: temporal.time.includes('01:00') ? null : 0, missing: temporal.time.includes('01:00'), unit: 'cm' } })
  const { app, objects } = setup([{ ...first, static: false }, { ...second, static: true }], () => time.value)
  t.after(() => app.unmount())
  await flush()
  assert.equal(listCalls.at(-1).time, time.value.time)
  await objects.select('one')
  assert.equal(objects.selected.value.temporal.value, 0)
  time.value = { time: '2026-10-25T01:00:00Z', resolution: 'hour' }; await flush()
  assert.equal(listCalls.at(-1).time, time.value.time)
  assert.equal(objects.selectedId.value, 'one')
  assert.equal(objects.selected.value.temporal.missing, true)
  await objects.setLayer('second')
  await flush()
  const count = listCalls.length
  assert.equal(listCalls.at(-1).time, undefined)
  time.value = { time: '2026-10-25T02:00:00Z', resolution: 'hour' }; await flush()
  assert.equal(listCalls.length, count)
})

test('defaults to one attached non-basemap layer and sends its pinned context once', async () => {
  const { app, objects } = setup([{ ...first, id: 'basemap' }, { ...first, id: 'detached', attached: false }, first])
  await flush()
  assert.equal(objects.activeLayerId.value, 'first')
  assert.equal(listCalls.length, 1)
  assert.deepEqual({ ...listCalls[0], signal: undefined }, { asset_id: 'asset-one', version: '1.0.0', layer_id: 'first', campus: 'university-town', type: '', q: '', page: 1, page_size: 20, signal: undefined })
  assert.equal(objects.items.value[0].confidence, null)
  assert.equal(objects.pageSize.value, 20)
  app.unmount()
})

test('filters reset pagination and failures clear rows while retaining trace text', async () => {
  const { app, objects } = setup()
  await flush()
  await objects.setPage(3)
  objects.type.value = 'building'; objects.q.value = '教学'
  await objects.applyFilters()
  assert.equal(listCalls.at(-1).page, 1)
  assert.equal(listCalls.at(-1).q, '教学')
  listRequest = async () => { throw new Error('索引不可用 (OBJECT_INDEX_UNAVAILABLE · trace_id: trace-one)') }
  await objects.refresh()
  assert.deepEqual(objects.items.value, [])
  assert.equal(objects.total.value, 0)
  assert.match(objects.error.value, /trace-one/)
  app.unmount()
})

test('late page and detail responses are aborted and cannot overwrite a newer layer', async () => {
  const oldList = deferred(), oldDetail = deferred()
  listRequest = query => query.layer_id === 'first' ? oldList.promise : Promise.resolve(pageOf([object('new', { asset: { asset_id: 'asset-two', version: '1.0.0' } })], query))
  detailRequest = () => oldDetail.promise
  const { app, objects } = setup()
  const detail = objects.select('old')
  await objects.setLayer('second')
  assert.equal(listCalls[0].signal.aborted, true)
  assert.equal(detailCalls[0].signal.aborted, true)
  oldList.resolve(pageOf([object('old')], { page: 1, page_size: 20 }))
  oldDetail.resolve(object('old'))
  await detail; await flush()
  assert.equal(objects.items.value[0].object_id, 'new')
  assert.equal(objects.selected.value, null)
  assert.equal(objects.detailLoading.value, false)
  app.unmount()
})

test('asset version changes and selected-layer removal clear stale selection and query only necessary context', async () => {
  const { app, objects, layers } = setup()
  await flush(); await objects.select('one')
  layers.value[0].asset_version = '2.0.0'
  await flush()
  assert.equal(listCalls.length, 2)
  assert.equal(listCalls[1].version, '2.0.0')
  assert.equal(objects.selected.value, null)
  layers.value[0].attached = false
  await flush()
  assert.equal(objects.activeLayerId.value, 'second')
  assert.equal(listCalls.length, 3)
  layers.value[1].attached = false
  await flush()
  assert.equal(objects.activeLayerId.value, '')
  assert.deepEqual(objects.items.value, [])
  app.unmount()
})

test('area selection fetches the complete 205 ids, fixes asset context and pages cached clipped rows by 20', async () => {
  const selected = Array.from({ length: 205 }, (_, i) => object(`area-${String(i).padStart(3, '0')}`, { geometry: { type: 'Point', coordinates: [113.1, 23.1] } }))
  areaRequest = async query => pageOf(selected.slice((query.page - 1) * 100, query.page * 100), query, selected.length)
  const { app, objects } = setup()
  await flush()
  await objects.selectArea(polygon)
  assert.deepEqual(areaCalls.map(call => [call.page, call.page_size, call.asset_id, call.version, call.layer_id]), [[1, 100, 'asset-one', '1.0.0', 'first'], [2, 100, 'asset-one', '1.0.0', 'first'], [3, 100, 'asset-one', '1.0.0', 'first']])
  assert.equal(objects.total.value, 205)
  assert.equal(objects.areaIds.value.length, 205)
  assert.equal(objects.items.value.length, 20)
  assert.equal(objects.selectionProgress.value, null)
  const requests = areaCalls.length
  await objects.setPage(11)
  assert.equal(objects.items.value.length, 5)
  assert.equal(areaCalls.length, requests)
  await objects.select(objects.items.value[0].object_id)
  assert.deepEqual(objects.selected.value.geometry.coordinates, [113, 23], 'details use the original object endpoint, not a clipped page row')
  await objects.clearArea()
  assert.deepEqual(objects.areaIds.value, [])
  assert.equal(objects.areaGeometry.value, null)
  assert.equal(objects.page.value, 1)
  app.unmount()
})

test('area progress is visible and cancellation prevents partial ids or late results', async () => {
  const last = deferred()
  areaRequest = query => query.page === 1 ? Promise.resolve(pageOf(Array.from({ length: 100 }, (_, i) => object(`a${i}`)), query, 101)) : last.promise
  const { app, objects } = setup()
  await flush()
  const selecting = objects.selectArea(polygon)
  await flush()
  assert.deepEqual(objects.selectionProgress.value, { loaded: 100, total: 101 })
  assert.deepEqual(objects.areaIds.value, [])
  await objects.setLayer('second')
  assert.equal(areaCalls.at(-1).signal.aborted, true)
  last.resolve(pageOf([object('last')], { page: 2, page_size: 100 }, 101))
  await selecting
  assert.deepEqual(objects.areaIds.value, [])
  assert.equal(objects.areaGeometry.value, null)
  assert.equal(objects.loading.value, false)
  app.unmount()
})

test('area filtering refetches the full area rather than silently returning an ordinary list', async () => {
  areaRequest = async query => pageOf([object(query.q || 'area')], query)
  const { app, objects } = setup()
  await flush(); await objects.selectArea(polygon)
  objects.q.value = 'library'
  await objects.applyFilters()
  assert.equal(areaCalls.at(-1).q, 'library')
  assert.equal(objects.areaIds.value[0], 'library')
  assert.equal(listCalls.length, 1)
  app.unmount()
})

test('map picking clears filters and area, selects the requested page once and fetches original details', async () => {
  const { app, objects } = setup()
  await flush(); await objects.selectArea(polygon)
  objects.type.value = 'building'; objects.q.value = 'old'
  const before = listCalls.length
  detailRequest = async id => object(id, { asset: { asset_id: 'asset-two', version: '1.0.0' } })
  await objects.showPicked('picked', 'second', 4)
  assert.equal(listCalls.length, before + 1)
  assert.deepEqual([objects.activeLayerId.value, objects.page.value, objects.type.value, objects.q.value], ['second', 4, '', ''])
  assert.deepEqual(objects.areaIds.value, [])
  assert.equal(objects.selected.value.object_id, 'picked')
  assert.equal(detailCalls.at(-1).id, 'picked')
  app.unmount()
})

test('unknown local index still reaches the service and surfaces its error without inventing attributes', async () => {
  listRequest = async () => { throw new Error('外部资源未读取 (OBJECT_INDEX_UNAVAILABLE · trace_id: external-one)') }
  const { app, objects } = setup([{ ...first, asset_id: null, asset_version: null, campus: null }])
  await flush()
  assert.equal(listCalls[0].layer_id, 'first')
  assert.equal(listCalls[0].asset_id, undefined)
  assert.equal(listCalls[0].campus, undefined)
  assert.match(objects.error.value, /external-one/)
  assert.equal(objects.selected.value, null)
  app.unmount()
})

test('incomplete area pages report failure and never expose a partial highlight set', async () => {
  areaRequest = async query => query.page === 1
    ? pageOf(Array.from({ length: 100 }, (_, i) => object(`a${i}`)), query, 101)
    : pageOf([], query, 101)
  const { app, objects } = setup()
  await flush(); await objects.selectArea(polygon)
  assert.match(objects.error.value, /选择结果/)
  assert.deepEqual(objects.areaIds.value, [])
  assert.deepEqual(objects.items.value, [])
  assert.equal(objects.total.value, 0)
  app.unmount()
})

test('detail request races expose only the latest original object and keep explicit failures', async () => {
  const old = deferred()
  detailRequest = id => id === 'old' ? old.promise : Promise.resolve(object(id))
  const { app, objects } = setup()
  await flush()
  const previous = objects.select('old')
  await objects.select('new')
  old.reject(new Error('旧详情失败'))
  await previous
  assert.equal(objects.selected.value.object_id, 'new')
  assert.equal(objects.detailError.value, '')
  detailRequest = async () => { throw new Error('对象不存在 (OBJECT_NOT_FOUND · trace_id: gone-one)') }
  await objects.select('gone')
  assert.equal(objects.selected.value, null)
  assert.match(objects.detailError.value, /gone-one/)
  objects.clearSelection()
  assert.equal(objects.selectedId.value, '')
  assert.equal(objects.detailError.value, '')
  app.unmount()
})

test('unmount aborts both requests and ignores their late successes or errors', async () => {
  const list = deferred(), detail = deferred()
  listRequest = () => list.promise; detailRequest = () => detail.promise
  const { app, objects } = setup()
  const selecting = objects.select('one')
  app.unmount()
  assert.equal(listCalls[0].signal.aborted, true)
  assert.equal(detailCalls[0].signal.aborted, true)
  list.reject(new Error('late list error')); detail.resolve(object('one'))
  await selecting; await flush()
  assert.deepEqual(objects.items.value, [])
  assert.equal(objects.selected.value, null)
  assert.equal(objects.error.value, '')
})
