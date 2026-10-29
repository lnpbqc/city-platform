import { beforeEach, mock, test } from 'node:test'
import assert from 'node:assert/strict'
import { createRenderer, defineComponent, nextTick } from 'vue'

let records = []
let deleted = []
let saves = []
let getLayersResult
let saveResult
let requestedCampuses
beforeEach(() => {
  records = []
  deleted = []
  saves = []
  getLayersResult = undefined
  saveResult = undefined
  requestedCampuses = []
})
mock.module('../src/api.ts', {
  exports: {
    getLayerCatalog: async (campus, signal) => {
      requestedCampuses.push(campus)
      return getLayersResult ? getLayersResult(campus, signal) : structuredClone(records)
    },
    deleteLayer: async (id) => {
      deleted.push(id)
      records = records.filter((record) => record.id !== id)
    },
    saveCatalogMapState: async (id, state) => {
      saves.push({ id, ...structuredClone(state) })
      if (saveResult) await saveResult(id, state)
      const record = records.find((item) => item.id === id)
      if ('order' in state) {
        records.sort((a, b) => a.order - b.order)
        records.splice(records.indexOf(record), 1)
        records.splice(state.order, 0, record)
        records.forEach((item, index) => { item.order = index })
      }
      Object.assign(record, state)
      return structuredClone(record)
    },
  },
})
const { useLayerCatalog } =
  await import('../src/composables/useLayerCatalog.ts')
const renderer = createRenderer({
  createElement: () => ({}),
  createText: () => ({}),
  createComment: () => ({}),
  insert() {},
  remove() {},
  setText() {},
  setElementText() {},
  patchProp() {},
  parentNode: () => null,
  nextSibling: () => null,
})
function setup(options = {}) {
  let catalog
  const calls = { load: 0, remove: [], locate: 0, messages: [], appearances: [] }
  const controller = {
    load(layer) {
      calls.load++
      if (options.removeDuringLoad) controller.remove(layer)
      layer.attached = true
      layer.visible = true
      if (options.loadError) {
        layer.status = 'error'
        layer.error = '资源加载失败'
        return
      }
      if (options.loadPending) {
        layer.status = 'loading'
        return options.loadPending.then(() => { layer.status = 'ready' })
      }
      layer.status = 'ready'
    },
    appearance(layer) {
      calls.appearances.push({ id: layer.id, visible: layer.visible, opacity: layer.opacity })
    },
    locate() {
      calls.locate++
    },
    remove(layer) {
      calls.remove.push(layer.id)
      layer.attached = false
      layer.status = 'idle'
    },
  }
  let currentController = options.controller === false ? undefined : controller
  const app = renderer.createApp(
    defineComponent({
      setup() {
        catalog = useLayerCatalog(
          () => currentController,
          (message) => calls.messages.push(message),
        )
        return () => null
      },
    }),
  )
  app.mount({})
  return {
    app, catalog, calls,
    setControllerReady() { currentController = controller },
  }
}
const flush = async () => {
  await new Promise(setImmediate)
  await nextTick()
}
function deferred() {
  let resolve
  let reject
  const promise = new Promise((yes, no) => { resolve = yes; reject = no })
  return { promise, resolve, reject }
}
const record = {
  id: 'local-one',
  name: '测试图层',
  category: '自定义',
  type: 'geojson',
  url: '/data-files/test/data.geojson',
  source: '合成',
}

test('saving registration does not load or locate; metadata edits preserve current map state', async () => {
  records = []
  const { app, catalog, calls } = setup()
  await nextTick()
  catalog.saved(record)
  const layer = catalog.layers.value.find((item) => item.id === record.id)
  assert.equal(layer.attached, false)
  assert.equal(calls.load, 0)
  assert.equal(calls.locate, 0)
  Object.assign(layer, {
    attached: true,
    visible: false,
    opacity: 0.4,
    status: 'ready',
  })
  catalog.saved({ ...record, name: '修改名称', category: '修改分类' })
  assert.equal(
    catalog.layers.value.find((item) => item.id === record.id),
    layer,
  )
  assert.equal(layer.opacity, 0.4)
  assert.equal(layer.visible, false)
  assert.equal(layer.status, 'ready')
  assert.deepEqual(calls.remove, [])
  records = [{ ...record, url: 'https://example.invalid/new.geojson' }]
  catalog.saved({ ...record, url: 'https://example.invalid/new.geojson' })
  assert.equal(layer.attached, false)
  assert.deepEqual(calls.remove, [record.id])
  assert.equal(calls.load, 0)
  app.unmount()
})

test('refresh removes deleted records from the map, preserving unchanged layer objects', async () => {
  records = [record]
  const { app, catalog, calls } = setup()
  await nextTick()
  const layer = catalog.layers.value.find((item) => item.id === record.id)
  layer.attached = true
  records = [{ ...record, name: '服务端修改' }]
  await catalog.refreshCatalog()
  assert.equal(
    catalog.layers.value.find((item) => item.id === record.id),
    layer,
  )
  assert.equal(layer.attached, true)
  records = []
  await catalog.refreshCatalog()
  assert.deepEqual(calls.remove, [record.id])
  assert.ok(!catalog.layers.value.some((item) => item.id === record.id))
  app.unmount()
})

test('deleting a registration detaches it while preserving the file deletion boundary', async (t) => {
  records = [record]
  deleted = []
  globalThis.window = { confirm: () => true }
  t.after(() => {
    delete globalThis.window
  })
  const { app, catalog, calls } = setup()
  await nextTick()
  await catalog.removeRecord(
    catalog.layers.value.find((item) => item.id === record.id),
  )
  assert.deepEqual(deleted, [record.id])
  assert.deepEqual(calls.remove, [record.id])
  assert.match(calls.messages.at(-1), /文件已保留/)
  app.unmount()
})

test('switching campuses replaces only attached builtins and preserves user data and viewing state', async () => {
  const { samplesForCampus } = await import('../src/types.ts')
  const builtinRecords = (campus) => samplesForCampus(campus).map((item) => ({
    ...item, builtin: true, asset: { asset_id: `${campus}-${item.id}`, version: '1.0.0' },
    map_attached: item.id !== 'demo-areas', map_visible: item.id !== 'demo-points', map_opacity: item.id === 'demo-points' ? 0.35 : 1,
  }))
  records = [...builtinRecords('university-town'), record]
  getLayersResult = (campus) => structuredClone([...builtinRecords(campus), record])
  const { app, catalog, calls } = setup()
  await flush()
  const builtins = catalog.layers.value.filter((layer) => layer.builtin)
  for (const layer of builtins)
    Object.assign(layer, { attached: true, status: 'ready' })
  const points = builtins.find((layer) => layer.id === 'demo-points')
  points.visible = false
  points.opacity = 0.35
  const detached = builtins.find((layer) => layer.id === 'demo-areas')
  detached.attached = false
  const user = catalog.layers.value.find((layer) => layer.id === record.id)
  Object.assign(user, { attached: true, status: 'ready', opacity: 0.6 })
  const beforeUser = { ...user }
  const beforeLoad = calls.load
  await catalog.switchCampus('huangpu')
  assert.ok(
    builtins.every((layer) => layer.url.startsWith('/samples/huangpu/')),
  )
  assert.ok(builtins.every((layer) => layer.source.includes('黄埔校区')))
  assert.equal(calls.load, beforeLoad + 4)
  assert.equal(points.visible, false)
  assert.equal(points.opacity, 0.35)
  assert.equal(detached.attached, false)
  assert.deepEqual({ ...user }, beforeUser)
  await catalog.switchCampus('huangpu')
  assert.equal(calls.load, beforeLoad + 4)
  await catalog.switchCampus('university-town')
  assert.equal(calls.load, beforeLoad + 8)
  assert.equal(points.visible, false)
  assert.equal(points.opacity, 0.35)
  assert.equal(detached.attached, false)
  assert.deepEqual({ ...user }, beforeUser)
  app.unmount()
})

test('remount restores custom membership, visibility and opacity without locating', async () => {
  records = [{ ...record }]
  const first = setup()
  await flush()
  await first.catalog.controllerReady()
  const layer = first.catalog.layers.value.find((item) => item.id === record.id)
  await first.catalog.joinLayer(layer)
  await first.catalog.toggleVisibility(layer)
  first.catalog.changeOpacity(layer, 0.35)
  await new Promise((resolve) => setTimeout(resolve, 330))
  await flush()
  assert.deepEqual(
    [records[0].map_attached, records[0].map_visible, records[0].map_opacity],
    [true, false, 0.35],
  )
  first.app.unmount()
  const beforeRestore = saves.length
  const second = setup({ removeDuringLoad: true })
  await flush()
  await second.catalog.controllerReady()
  const restored = second.catalog.layers.value.find((item) => item.id === record.id)
  assert.deepEqual([restored.attached, restored.visible, restored.opacity], [true, false, 0.35])
  assert.equal(second.calls.load, 1)
  assert.equal(second.calls.locate, 0)
  assert.equal(saves.length, beforeRestore, 'internal resource loading must not save transient state')
  await second.catalog.refreshCatalog()
  await second.catalog.controllerReady()
  assert.equal(second.calls.load, 1, 'refresh and repeated readiness must not reload an attached layer')
  second.app.unmount()
})

test('catalog loaded before controller readiness restores once the controller arrives', async () => {
  records = [{ ...record, map_attached: true, map_visible: false, map_opacity: 0.6 }]
  const { app, catalog, calls, setControllerReady } = setup({ controller: false })
  await flush()
  assert.equal(calls.load, 0)
  setControllerReady()
  await catalog.controllerReady()
  const layer = catalog.layers.value.find((item) => item.id === record.id)
  assert.deepEqual([layer.attached, layer.visible, layer.opacity], [true, false, 0.6])
  assert.equal(calls.load, 1)
  assert.deepEqual(saves, [])
  app.unmount()
})

test('controller ready before the catalog restores after the catalog request completes', async () => {
  const request = deferred()
  getLayersResult = () => request.promise
  records = [{ ...record, map_attached: true, map_visible: false, map_opacity: 0.25 }]
  const { app, catalog, calls } = setup()
  await catalog.controllerReady()
  assert.equal(calls.load, 0)
  request.resolve(structuredClone(records))
  await flush()
  const layer = catalog.layers.value.find((item) => item.id === record.id)
  assert.deepEqual([layer.attached, layer.visible, layer.opacity], [true, false, 0.25])
  assert.equal(calls.load, 1)
  assert.equal(calls.locate, 0)
  app.unmount()
})

test('explicit removal saves detached state and does not restore on remount', async () => {
  records = [{ ...record, map_attached: true, map_visible: true, map_opacity: 1 }]
  const first = setup()
  await flush()
  await first.catalog.controllerReady()
  const layer = first.catalog.layers.value.find((item) => item.id === record.id)
  await first.catalog.removeFromMap(layer)
  await flush()
  assert.equal(layer.attached, false)
  assert.equal(records[0].map_attached, false)
  first.app.unmount()
  const second = setup()
  await flush()
  await second.catalog.controllerReady()
  assert.equal(second.calls.load, 0)
  second.app.unmount()
})

test('save failures expose an unsaved state and retry saves the latest selection', async () => {
  records = [{ ...record }]
  saveResult = async () => { throw new Error('网络不可用') }
  const { app, catalog } = setup()
  await flush()
  const layer = catalog.layers.value.find((item) => item.id === record.id)
  await catalog.joinLayer(layer)
  await flush()
  assert.ok(catalog.mapStateErrors.value[record.id])
  assert.equal(records[0].map_attached, undefined)
  saveResult = undefined
  await catalog.retryMapState(layer)
  await flush()
  assert.equal(records[0].map_attached, true)
  assert.ok(!catalog.mapStateErrors.value[record.id])
  app.unmount()
})

test('writes for the same layer are serial and rapid visibility changes keep the latest choice', async () => {
  records = [{ ...record }]
  const firstWrite = deferred()
  let active = 0
  let maxActive = 0
  saveResult = async () => {
    active++
    maxActive = Math.max(maxActive, active)
    if (saves.length === 1) await firstWrite.promise
    active--
  }
  const { app, catalog } = setup()
  await flush()
  const layer = catalog.layers.value.find((item) => item.id === record.id)
  const joining = catalog.joinLayer(layer)
  await flush()
  assert.equal(saves.length, 1)
  catalog.toggleVisibility(layer)
  catalog.toggleVisibility(layer)
  catalog.toggleVisibility(layer)
  await flush()
  assert.equal(saves.length, 1, 'later state must wait for the first write')
  firstWrite.resolve()
  await joining
  await flush()
  assert.equal(maxActive, 1)
  assert.equal(records[0].map_attached, true)
  assert.equal(records[0].map_visible, false)
  assert.equal(layer.visible, false, 'an earlier save response must not overwrite the latest local choice')
  app.unmount()
})

test('opacity saves debounce for 300 ms and persist the latest value', async () => {
  records = [{ ...record }]
  const { app, catalog } = setup()
  await flush()
  const layer = catalog.layers.value.find((item) => item.id === record.id)
  await catalog.joinLayer(layer)
  await flush()
  const initialSaves = saves.length
  catalog.changeOpacity(layer, 0.2)
  catalog.changeOpacity(layer, 0.45)
  catalog.changeOpacity(layer, 0.7)
  assert.equal(layer.opacity, 0.7)
  await new Promise((resolve) => setTimeout(resolve, 250))
  assert.equal(saves.length, initialSaves)
  await new Promise((resolve) => setTimeout(resolve, 80))
  await flush()
  assert.equal(saves.length, initialSaves + 1)
  assert.equal(records[0].map_opacity, 0.7)
  app.unmount()
})

test('failed resource restoration preserves the saved desired state and does not persist cleanup', async () => {
  records = [{ ...record, map_attached: true, map_visible: false, map_opacity: 0.5 }]
  const { app, catalog, calls } = setup({ loadError: true, removeDuringLoad: true })
  await flush()
  await catalog.controllerReady()
  const layer = catalog.layers.value.find((item) => item.id === record.id)
  assert.equal(layer.status, 'error')
  assert.equal(calls.load, 1)
  assert.deepEqual(saves, [])
  assert.deepEqual(
    [records[0].map_attached, records[0].map_visible, records[0].map_opacity],
    [true, false, 0.5],
  )
  app.unmount()
})

test('builtin visibility, opacity and removal persist and stay detached on remount', async () => {
  records = [{ ...record, id: 'demo-points', builtin: true, asset: { asset_id: 'default-points', version: '1.0.0' }, map_attached: true }]
  const { app, catalog } = setup()
  await flush()
  const layer = catalog.layers.value.find((item) => item.builtin)
  await catalog.joinLayer(layer)
  await catalog.toggleVisibility(layer)
  catalog.changeOpacity(layer, 0.3)
  await new Promise((resolve) => setTimeout(resolve, 330))
  await flush()
  assert.equal(layer.visible, false)
  assert.equal(layer.opacity, 0.3)
  assert.equal(records[0].map_opacity, 0.3)
  assert.equal(records[0].map_visible, false)
  catalog.removeFromMap(layer)
  await flush()
  assert.equal(records[0].map_attached, false)
  app.unmount()
  const second = setup()
  await flush()
  await second.catalog.controllerReady()
  assert.equal(second.calls.load, 0)
  second.app.unmount()
})

test('catalog maps pinned assets and metadata, preserving the basemap special id', async () => {
  records = [
    { ...record, id: 'basemap', type: 'basemap', url: null, builtin: true, asset: null, map_attached: true, order: 0 },
    { ...record, builtin: true, asset: { asset_id: 'asset-one', version: '2.0.0' }, object_count: 27, unit: 'm', legend: [{ label: '建筑', color: '#123456' }], order: 3, orderable: false, campus: 'university-town', static: true },
  ]
  const { app, catalog } = setup()
  await flush()
  assert.deepEqual(catalog.layers.value.map((layer) => layer.id), ['basemap', record.id])
  const base = catalog.layers.value[0]
  assert.equal(base.type, 'geojson')
  assert.equal(base.url, '')
  const layer = catalog.layers.value[1]
  assert.deepEqual([layer.asset_id, layer.asset_version, layer.builtin, layer.object_count, layer.unit, layer.order, layer.color], ['asset-one', '2.0.0', true, 27, 'm', 3, '#123456'])
  assert.equal(layer.orderable, false)
  app.unmount()
})

test('late catalog successes and failures cannot overwrite a newer campus or an unmounted catalog', async () => {
  const initial = deferred()
  const huangpu = deferred()
  let initialSignal
  getLayersResult = (campus, signal) => {
    if (campus === 'huangpu') return huangpu.promise
    initialSignal = signal
    return initial.promise
  }
  const { app, catalog } = setup()
  const switching = catalog.switchCampus('huangpu')
  huangpu.resolve([{ ...record, id: 'new-campus' }])
  await switching
  assert.equal(initialSignal.aborted, true)
  initial.reject(new Error('旧校区连接失败'))
  await flush()
  assert.equal(catalog.backend.value, 'online')
  assert.equal(catalog.catalogError.value, '')
  assert.deepEqual(catalog.layers.value.map((item) => item.id), ['new-campus'])
  const late = deferred()
  getLayersResult = () => late.promise
  const refresh = catalog.refreshCatalog()
  app.unmount()
  late.resolve([{ ...record, id: 'after-unmount' }])
  await refresh
  assert.deepEqual(catalog.layers.value.map((item) => item.id), ['new-campus'])
})

test('switching campus preserves a pending builtin state against stale server values', async () => {
  const write = deferred()
  records = [{ ...record, id: 'demo-points', builtin: true, asset: { asset_id: 'town-points', version: '1.0.0' }, map_attached: true, map_visible: true, map_opacity: 1 }]
  const { app, catalog } = setup()
  await flush()
  const layer = catalog.layers.value[0]
  saveResult = () => write.promise
  catalog.removeFromMap(layer)
  await flush()
  records = [{ ...records[0], asset: { asset_id: 'huangpu-points', version: '1.0.0' } }]
  await catalog.switchCampus('huangpu')
  assert.equal(catalog.layers.value[0], layer)
  assert.equal(layer.asset_id, 'huangpu-points')
  assert.equal(layer.map_attached, false)
  assert.equal(layer.attached, false)
  write.resolve()
  await flush()
  app.unmount()
})

test('initial offline sample fallback loads local samples without fabricating asset ids', async () => {
  getLayersResult = async () => { throw new Error('服务离线') }
  const { app, catalog, calls } = setup()
  await flush()
  await catalog.controllerReady()
  assert.equal(catalog.backend.value, 'offline')
  assert.match(catalog.catalogError.value, /服务离线/)
  assert.equal(calls.load, 4)
  assert.ok(catalog.layers.value.every((layer) => layer.builtin && !layer.asset_id))
  catalog.removeFromMap(catalog.layers.value[0])
  await flush()
  assert.deepEqual(saves, [])
  app.unmount()
})

test('refresh while a resource is loading preserves its pending saved appearance without a second load', async () => {
  const resource = deferred()
  records = [{ ...record, map_attached: true, map_visible: false, map_opacity: 0.4 }]
  const { app, catalog, calls } = setup({ loadPending: resource.promise, removeDuringLoad: true })
  await flush()
  const layer = catalog.layers.value.find((item) => item.id === record.id)
  assert.equal(layer.status, 'loading')
  await catalog.refreshCatalog()
  await catalog.controllerReady()
  assert.equal(calls.load, 1)
  assert.deepEqual([layer.visible, layer.opacity], [false, 0.4])
  resource.resolve()
  await flush()
  assert.equal(layer.status, 'ready')
  assert.deepEqual([layer.visible, layer.opacity], [false, 0.4])
  assert.deepEqual(saves, [])
  app.unmount()
})

test('deleting a registration cancels its pending opacity save and removes its map state', async (t) => {
  records = [{ ...record, map_attached: true }]
  globalThis.window = { confirm: () => true }
  t.after(() => { delete globalThis.window })
  const { app, catalog } = setup()
  await flush()
  const layer = catalog.layers.value.find((item) => item.id === record.id)
  catalog.changeOpacity(layer, 0.4)
  await catalog.removeRecord(layer)
  await new Promise((resolve) => setTimeout(resolve, 330))
  assert.deepEqual(records, [])
  assert.deepEqual(saves, [])
  assert.ok(!catalog.layers.value.some((item) => item.id === record.id))
  assert.ok(!catalog.mapStateErrors.value[record.id])
  app.unmount()
})

test('source changes during an opacity debounce supersede old state and require an explicit join', async () => {
  records = [{ ...record, map_attached: true, map_visible: true, map_opacity: 1 }]
  const { app, catalog, calls } = setup()
  await flush()
  const layer = catalog.layers.value.find((item) => item.id === record.id)
  assert.equal(calls.load, 1)
  catalog.changeOpacity(layer, 0.2)
  records = [{ ...records[0], url: '/data-files/replaced/data.geojson', map_attached: false }]
  await catalog.refreshCatalog()
  await new Promise((resolve) => setTimeout(resolve, 330))
  await flush()
  assert.equal(layer.attached, false)
  assert.equal(layer.map_attached, false)
  assert.equal(calls.load, 1, 'the new source must wait for an explicit join')
  assert.equal(records[0].map_attached, false)
  assert.ok(saves.every((state) => state.map_attached === false), 'the old opacity timer must not reattach the changed source')
  await catalog.refreshCatalog()
  assert.equal(calls.load, 1)
  app.unmount()
})

test('source changes while a state save is in flight serialize a detached state after the old write', async () => {
  records = [{ ...record, map_attached: true, map_visible: true, map_opacity: 1 }]
  const oldWrite = deferred()
  saveResult = async () => {
    if (saves.length === 1) await oldWrite.promise
  }
  const { app, catalog, calls } = setup()
  await flush()
  const layer = catalog.layers.value.find((item) => item.id === record.id)
  catalog.toggleVisibility(layer)
  await flush()
  assert.equal(saves.length, 1)
  records = [{ ...records[0], url: '/data-files/replaced/data.geojson', map_attached: false }]
  await catalog.refreshCatalog()
  assert.equal(layer.attached, false)
  assert.equal(layer.map_attached, false)
  assert.equal(calls.load, 1)
  assert.equal(saves.length, 1, 'the detached state must wait for the old write')
  oldWrite.resolve()
  await flush()
  assert.equal(saves.length, 2)
  assert.equal(saves[0].map_attached, true)
  assert.equal(saves[1].map_attached, false)
  assert.equal(records[0].map_attached, false)
  assert.equal(layer.map_attached, false)
  await catalog.refreshCatalog()
  assert.equal(calls.load, 1)
  app.unmount()
})

test('an explicit join during hidden auto-restoration reuses the resource and waits until it is ready', async () => {
  const resource = deferred()
  records = [{ ...record, map_attached: true, map_visible: false, map_opacity: 0.4 }]
  const { app, catalog, calls } = setup({ loadPending: resource.promise, removeDuringLoad: true })
  await flush()
  const layer = catalog.layers.value.find((item) => item.id === record.id)
  assert.equal(layer.status, 'loading')
  assert.equal(layer.visible, false)
  let joined = false
  const joining = catalog.joinLayer(layer).then(() => { joined = true })
  await flush()
  assert.equal(layer.visible, true)
  assert.deepEqual(
    [records[0].map_attached, records[0].map_visible, records[0].map_opacity],
    [true, true, 0.4],
  )
  assert.equal(joined, false, 'explicit join must await the existing resource load')
  assert.equal(calls.load, 1)
  resource.resolve()
  await joining
  await flush()
  assert.equal(joined, true)
  assert.equal(layer.status, 'ready')
  assert.equal(layer.visible, true)
  assert.equal(calls.load, 1)
  assert.equal(calls.locate, 0, 'the hook leaves locating to its caller')
  app.unmount()
})

test('ordering uses server-reindexed catalog and ignores a duplicate click while saving', async () => {
  records = ['first', 'second'].map((id, order) => ({ ...record, id, order, orderable: true, map_attached: true }))
  const saving = deferred()
  saveResult = () => saving.promise
  const { app, catalog, calls } = setup()
  await flush()
  const first = catalog.layers.value[0]
  const moving = catalog.moveLayer(first, 1)
  assert.equal(catalog.ordering.value, true)
  await catalog.moveLayer(first, 1)
  assert.equal(saves.length, 1)
  saving.resolve()
  await moving
  assert.deepEqual(catalog.layers.value.map(layer => layer.id), ['second', 'first'])
  assert.deepEqual(catalog.layers.value.map(layer => layer.order), [0, 1])
  assert.equal(calls.load, 2, 'reordering must retain loaded resources')
  assert.equal(catalog.ordering.value, false)
  await catalog.refreshCatalog()
  assert.deepEqual(catalog.layers.value.map(layer => layer.id), ['second', 'first'])
  app.unmount()
})

test('order failure preserves the current order and can be retried; 3D cannot be reordered', async () => {
  records = ['first', 'second'].map((id, order) => ({ ...record, id, order, orderable: true, map_attached: true }))
  const { app, catalog } = setup()
  await flush()
  const first = catalog.layers.value[0]
  saveResult = () => { throw new Error('trace_id: order-error') }
  await catalog.moveLayer(first, 1)
  assert.deepEqual(catalog.layers.value.map(layer => layer.id), ['first', 'second'])
  assert.match(catalog.orderError.value, /order-error/)
  saveResult = undefined
  await catalog.moveLayer(first, 1)
  assert.equal(catalog.orderError.value, '')
  assert.deepEqual(catalog.layers.value.map(layer => layer.id), ['second', 'first'])
  first.orderable = false
  const count = saves.length
  await catalog.moveLayer(first, -1)
  assert.equal(saves.length, count)
  app.unmount()
})
