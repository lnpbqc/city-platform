import { test } from 'node:test'
import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import { parse } from 'vue/compiler-sfc'
import ts from 'typescript'
import * as vue from 'vue'
import * as poi from '../src/map/poi.ts'
import { useWeatherView } from '../src/composables/useWeatherView.ts'

const source = await readFile(new URL('../src/views/MapWorkspace.vue', import.meta.url), 'utf8')
const { descriptor } = parse(source)
const javascript = ts.transpileModule(descriptor.scriptSetup.content, {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
}).outputText
const create = new Function('require', 'defineProps', 'defineEmits', 'defineExpose', 'exports', 'window', 'document', `${javascript}
  return { onMapSelection, inspectedSelection, onMapReady, clearObjectSelection, beginDraw, drawing, objectsOpen, toggleObjects, onNavigation, toggleMode, cameraMoving, shownWeather, restoreWorkspace, captureWorkspace, clearScene, changeLayer, setOpacity, viewLayers, timeAxis, timeAxisHeight, queryNearby, selectNearby, nearbyOpen, nearbyItems, nearbyLoading, nearbyUnavailable, nearbyError, captureDisplayView, openDisplayRegion, home,
    startCalibration, changeCalibration, pickCalibrationPivot, publishCalibration, cancelCalibration, blockedTilesAsset, calibrationError, calibrationMatrix }
`)
const geometry = { type: 'Polygon', coordinates: [[[113, 23], [114, 23], [114, 24], [113, 23]]] }
function setup(options = {}) {
  const hooks = [], queries = [], events = []
  const props = vue.reactive({ active: true, backend: 'online', layers: [
    { id: 'a', attached: true, asset_id: 'asset-a', asset_version: '1.0.0' },
    { id: 'b', attached: true, asset_id: 'asset-b', asset_version: '1.0.0' },
  ] })
  const objects = Object.fromEntries(['activeLayerId', 'items', 'total', 'page', 'pageSize', 'loading', 'error',
    'type', 'q', 'selectedId', 'selected', 'detailLoading', 'detailError', 'areaGeometry', 'areaIds',
    'selectionProgress'].map(key => [key, vue.ref(null)]))
  objects.activeLayerId.value = 'a'
  objects.areaIds.value = []
  for (const key of ['refresh', 'setLayer', 'setPage', 'applyFilters', 'select', 'showPicked', 'clearArea', 'clearSelection', 'returnToResults']) objects[key] = () => {}
  objects.selectArea = value => queries.push({ layer: objects.activeLayerId.value, geometry: value })
  options.objectActions?.(objects)
  const controller = {
    cancellations: 0,
    initialize() {}, highlights: [], highlightObjects(...args) { this.highlights.push(args) }, objectPage() {}, setMode() {}, resume() {},
    cancelAreaSelection() { this.cancellations++; this.cancelled?.() },
    cancelPointPicking() { this.pointMarker = null },
    beginAreaSelection(mode, callback, cancelled) { this.callback = callback; this.cancelled = cancelled },
    getCamera() { return this.camera ?? { longitude: 113, latitude: 23, height: 800, heading: 0, pitch: -1, roll: 0, scene_mode: '3d' } },
    getWeatherPoint() { return options.weatherPoint?.() ?? null },
    getDisplayRegionExtent() { return options.extent?.() ?? null },
    setRegionBoundary() {},
    setCamera(camera) { this.camera = camera; return true },
    flyToCamera(camera) { return options.fly ? options.fly(camera) : this.setCamera(camera) },
    beginTilesCalibration(_layer, callbacks) { this.calibration = callbacks; this.groundChanged = false; return true },
    updateTilesCalibration(offsets) { this.offsets = { ...offsets }; return this.picking ? null : Object.values(offsets) },
    hasTilesCalibrationChanges() {
      return this.groundChanged || Object.entries(this.offsets).some(([key, value]) => key === 'yaw' ? value % 360 !== 0 : value !== 0)
    },
    async prepareTilesCalibration() { return { matrix: Object.values(this.offsets), terrain_anchor: { longitude: 113, latitude: 23, height: 40 } } },
    pickTilesCalibrationPivot() { this.picking = true; this.calibration.notice('选择表面') },
    endTilesCalibration() { this.calibration = null },
    removed: [], remove(layer) { this.removed.push(layer.id); layer.attached = false },
    async load(layer) { layer.attached = true; layer.status = 'ready' }, appearance() {}, syncOrder() {},
  }
  const scope = vue.effectScope()
  const panel = scope.run(() => create(name => {
    if (name === '../api/api') return { calibrateTiles: options.calibrateTiles, getNearbyPois: options.nearby ?? (async () => ({ items: [], unavailable_layers: [] })) }
    if (name === 'vue') return { ...vue, onMounted() {}, onBeforeUnmount: hook => hooks.push(hook) }
    if (name === '../composables/useObjects') return { useObjects: () => objects }
    if (name === '../composables/useWeatherView') return { useWeatherView }
    if (name === '../composables/useDisplayRegions') return { useDisplayRegions: () => ({ regions: vue.ref(options.displayRegions ?? []) }) }
    if (name === '../composables/useTemporalLayers') return { useTemporalLayers: () => { const time = vue.ref(''); return { time, resolution: vue.ref('hour'), times: vue.ref(['2026-10-25T00:00:00Z']), pause() {}, paint() {}, setTime(value) { time.value = value } } } }
    if (name === '../map/poi') return poi
    if (name === '../simulation/sceneLayers') return {
      captureLayers: layers => layers.map(layer => ({ layer_id: layer.id, asset: { asset_id: layer.asset_id, version: layer.asset_version }, map_attached: layer.attached, map_visible: layer.visible, map_opacity: layer.opacity })),
      prepareSceneLayers: options.prepare ?? (async states => states.map(state => ({ id: state.layer_id, asset_id: state.asset.asset_id, asset_version: state.asset.version, map_attached: state.map_attached, visible: state.map_visible, opacity: state.map_opacity, order: state.order, attached: false }))),
    }
    if (name === '../layers/layerTree') return {}
    if (name === '../map/mapNavigation') return { readMapView: () => null }
    if (name === '../map/regions') return { demoRegion: {}, campusRegions: [{ id: 'demo-huangpu', sampleKey: 'huangpu' }] }
    if (name.endsWith('.vue')) return {}
    throw new Error(`Unexpected workspace dependency: ${name}`)
  }, () => props, () => (...args) => events.push(args), () => {}, {}, { localStorage: {}, removeEventListener() {} }, { removeEventListener() {} }))
  panel.onMapReady(controller)
  return { panel, props, objects, controller, queries, events, cleanup() { hooks.forEach(hook => hook()); scope.stop() } }
}

test('calibration previews six offsets, preserves failed drafts and blocks old ZIPs through reload', async t => {
  const publishes = []
  let fail = true
  const ctx = setup({ calibrateTiles: async (...args) => {
    publishes.push(args)
    if (fail) throw new Error('资产版本已更新')
    return { version: '1.0.0', revision: 1 }
  } })
  t.after(ctx.cleanup)
  const { panel, controller, props } = ctx
  const target = props.layers[0]
  target.tiles_calibration_allowed = true
  props.layers[1].asset_id = target.asset_id
  panel.startCalibration(target)
  assert.equal(panel.blockedTilesAsset.value, 'asset-a')
  panel.pickCalibrationPivot()
  assert.equal(panel.calibrationMatrix.value, null)
  await panel.publishCalibration('update')
  assert.equal(publishes.length, 0)
  controller.picking = false
  controller.calibration.notice('')
  controller.calibration.moved(1.25, -2.83)
  for (const [key, value] of Object.entries({ up: 3, yaw: 4, pitch: 5, roll: 6 })) panel.changeCalibration(key, value)
  props.active = false
  await vue.nextTick()
  assert.equal(panel.blockedTilesAsset.value, 'asset-a', 'data view cannot silently download the pre-calibration model')
  assert.ok(controller.calibration)
  props.active = true
  await vue.nextTick()
  await panel.publishCalibration('update')
  assert.equal(panel.calibrationError.value, '资产版本已更新')
  assert.ok(controller.calibration)
  assert.deepEqual(publishes[0], ['asset-a', {
    mode: 'update', base_version: '1.0.0', base_revision: 0, matrix: [1.25, -2.83, 3, 4, 5, 6],
    terrain_anchor: { longitude: 113, latitude: 23, height: 40 },
  }])
  fail = false
  await panel.publishCalibration('update')
  assert.equal(controller.calibration, null)
  assert.equal(panel.blockedTilesAsset.value, 'asset-a')
  assert.deepEqual(ctx.events.at(-1), ['refresh'])
  Object.assign(target, { tiles_revision: 1, tiles_calibrated: true })
  await vue.nextTick()
  assert.equal(panel.blockedTilesAsset.value, 'asset-a')
  Object.assign(props.layers[1], { tiles_revision: 1, tiles_calibrated: true })
  await vue.nextTick()
  assert.equal(panel.blockedTilesAsset.value, undefined)
  panel.startCalibration(target)
  panel.cancelCalibration()
  assert.equal(controller.calibration, null)
  assert.equal(panel.blockedTilesAsset.value, undefined)
})

test('saving a named calibration copy releases the original layer without waiting for a replacement', async t => {
  const publishes = []
  const ctx = setup({ calibrateTiles: async (...args) => {
    publishes.push(args)
    return { asset_id: 'new-asset', revision: 1, name: '校准样本' }
  } })
  t.after(ctx.cleanup)
  const { panel, props, controller } = ctx
  const target = props.layers[0]
  target.tiles_calibration_allowed = true
  target.tiles_revision = 2
  panel.startCalibration(target)
  panel.changeCalibration('up', 2)
  await panel.publishCalibration('copy', '  校准样本  ')
  assert.equal(publishes[0][1].name, '校准样本')
  assert.equal(publishes[0][1].base_revision, 2)
  assert.equal(publishes[0][1].mode, 'copy')
  assert.equal(panel.blockedTilesAsset.value, undefined)
  assert.equal(controller.calibration, null)
  assert.equal(target.tiles_revision, 2)
  assert.deepEqual(ctx.events.at(-1), ['refresh'])
})

test('numeric adjustments can be saved directly by either action', async t => {
  const publishes = []
  const ctx = setup({ calibrateTiles: async (...args) => { publishes.push(args); return { revision: 1 } } })
  t.after(ctx.cleanup)
  const { panel, props } = ctx
  const target = props.layers[0]
  target.tiles_calibration_allowed = true
  for (const mode of ['copy', 'update']) {
    panel.startCalibration(target)
    panel.changeCalibration('yaw', 6)
    await panel.publishCalibration(mode, '微调模型')
  }
  assert.deepEqual(publishes.map(([, body]) => [body.mode, body.matrix[3]]), [['copy', 6], ['update', 6]])
})

test('opening calibration, replacing only the pivot, and undoing offsets do not publish', async t => {
  const publishes = []
  const ctx = setup({ calibrateTiles: async (...args) => { publishes.push(args); return { revision: 1 } } })
  t.after(ctx.cleanup)
  const { controller, panel, props } = ctx
  const target = props.layers[0]
  target.tiles_calibration_allowed = true
  panel.startCalibration(target)
  await panel.publishCalibration('update')
  await panel.publishCalibration('copy', '原模型副本')
  assert.equal(publishes.length, 0)
  panel.changeCalibration('yaw', 360)
  await panel.publishCalibration('update')
  assert.equal(publishes.length, 0)
  panel.changeCalibration('yaw', 0)

  panel.pickCalibrationPivot()
  controller.picking = false
  controller.calibration.notice('')
  panel.changeCalibration('yaw', 6)
  panel.changeCalibration('yaw', 0)
  await panel.publishCalibration('update')
  assert.equal(publishes.length, 0)

  panel.pickCalibrationPivot('ground')
  controller.picking = false
  controller.groundChanged = true
  controller.calibration.notice('')
  await panel.publishCalibration('update')
  assert.equal(publishes.length, 1)
})

test('time axis height follows wrapping and releases its observer when hidden or unmounted', async t => {
  const observers = []
  const previous = globalThis.ResizeObserver
  globalThis.ResizeObserver = class {
    constructor(callback) { this.callback = callback; observers.push(this) }
    observe(element) { this.element = element }
    disconnect() { this.disconnected = true }
  }
  t.after(() => { globalThis.ResizeObserver = previous })
  const ctx = setup()
  t.after(() => ctx.cleanup())
  let height = 180
  const element = { getBoundingClientRect: () => ({ height }) }
  ctx.panel.timeAxis.value = { $el: element }
  await vue.nextTick()
  observers[0].callback([{ target: element }])
  assert.equal(ctx.panel.timeAxisHeight.value, 180)
  height = 340
  observers[0].callback([{ target: element }])
  assert.equal(ctx.panel.timeAxisHeight.value, 340)
  ctx.panel.timeAxis.value = null
  await vue.nextTick()
  assert.equal(ctx.panel.timeAxisHeight.value, 0)
  assert.equal(observers[0].disconnected, true)
  ctx.panel.timeAxis.value = { $el: element }
  await vue.nextTick()
  ctx.cleanup()
  assert.equal(observers[1].disconnected, true)
})

test('nearby queries only enabled POI layers and reports unavailable local indexes', async () => {
  const calls = []
  const ctx = setup({ nearby: async body => { calls.push(body); return { items: [], unavailable_layers: ['external'] } } })
  ctx.props.layers = [
    { id: 'poi', category: 'POI', attached: true, visible: true, asset_id: 'asset', asset_version: '1' },
    { id: 'hidden', category: 'POI', attached: true, visible: false, asset_id: 'hidden', asset_version: '1' },
    { id: 'external', category: 'POI', attached: true, visible: true },
    { id: 'building', category: '建筑', attached: true, visible: true, asset_id: 'building', asset_version: '1' },
  ]
  await vue.nextTick()
  await ctx.panel.queryNearby({ longitude: 113, latitude: 23 })
  assert.deepEqual(calls[0], { longitude: 113, latitude: 23, radius_m: 1000, limit: 20,
    layers: [{ layer_id: 'poi', asset_id: 'asset', version: '1' }] })
  assert.equal(ctx.panel.nearbyOpen.value, true)
  assert.deepEqual([...ctx.panel.nearbyUnavailable.value], ['external'])
  ctx.props.layers[3].visible = false
  await vue.nextTick()
  assert.equal(ctx.panel.nearbyOpen.value, true, 'unrelated layer changes must preserve nearby results')
  ctx.cleanup()
})

test('new ground clicks and layer visibility changes invalidate stale nearby responses', async () => {
  const pending = []
  const ctx = setup({ nearby: () => new Promise(resolve => pending.push(resolve)) })
  ctx.props.layers = [{ id: 'poi', category: 'POI', attached: true, visible: true, asset_id: 'asset', asset_version: '1' }]
  await vue.nextTick()
  const first = ctx.panel.queryNearby({ longitude: 113, latitude: 23 })
  const second = ctx.panel.queryNearby({ longitude: 114, latitude: 23 })
  pending[1]({ items: [{ object_id: 'latest' }], unavailable_layers: [] })
  await second
  pending[0]({ items: [{ object_id: 'stale' }], unavailable_layers: [] })
  await first
  assert.equal(ctx.panel.nearbyItems.value[0].object_id, 'latest')
  const third = ctx.panel.queryNearby({ longitude: 115, latitude: 23 })
  ctx.props.layers[0].visible = false
  await vue.nextTick()
  pending[2]({ items: [{ object_id: 'hidden' }], unavailable_layers: [] })
  await third
  assert.equal(ctx.panel.nearbyOpen.value, false)
  assert.deepEqual([...ctx.panel.nearbyItems.value], [])
  ctx.cleanup()
})

test('removing the drawing layer cancels and stale completion cannot select the replacement layer', async () => {
  const ctx = setup()
  ctx.panel.beginDraw('polygon')
  const complete = ctx.controller.callback
  ctx.props.layers[0].attached = false
  ctx.objects.activeLayerId.value = 'b'
  await vue.nextTick()
  assert.equal(ctx.panel.drawing.value, null)
  assert.equal(ctx.controller.cancellations, 1)
  complete(geometry)
  assert.deepEqual(ctx.queries, [])
  ctx.cleanup()
})

test('asset version changes invalidate a drawing before the watch callback runs', async () => {
  const ctx = setup()
  ctx.panel.beginDraw('box')
  const complete = ctx.controller.callback
  ctx.props.layers[0].asset_version = '2.0.0'
  complete(geometry)
  assert.deepEqual(ctx.queries, [])
  await vue.nextTick()
  assert.equal(ctx.panel.drawing.value, null)
  ctx.cleanup()
})

test('completed areas keep their scope and closing the object panel cancels drafting', () => {
  const ctx = setup()
  ctx.panel.beginDraw('polygon')
  ctx.controller.callback(geometry)
  assert.deepEqual(ctx.queries, [{ layer: 'a', geometry }])
  ctx.panel.objectsOpen.value = true
  ctx.panel.beginDraw('box')
  ctx.panel.toggleObjects()
  assert.equal(ctx.panel.drawing.value, null)
  assert.equal(ctx.panel.objectsOpen.value, false)
  assert.equal(ctx.controller.cancellations, 1)
  ctx.cleanup()
})

test('the workspace renders a single map and keeps its thematic timeline', () => {
  const template = descriptor.template.content
  assert.equal((template.match(/<MapCanvas\b/g) ?? []).length, 1)
  assert.equal((template.match(/<TimeAxis\b/g) ?? []).length, 1)
  assert.doesNotMatch(template, /ComparisonView|时间对比/)
})

const fixedScene = id => ({ id, version: 1, name: id, camera: { longitude: 114, latitude: 24, height: 500, heading: 0.2, pitch: -1.4, roll: 0, scene_mode: '3d' },
  current_time: '2026-10-25T01:00:00Z', layers: [{ layer_id: 'fixed', asset: { asset_id: id, version: '2.0.0' }, map_attached: true, map_visible: false, map_opacity: 0.35, order: 0 }] })
const address = { page: 'map', resolution: 'hour', time: '2026-10-25T05:00:00Z', comparison: { time: '2026-10-26T01:00:00Z', resolution: 'day' } }
test('restored map layers edit independently and exiting releases their resources', async () => {
  const ctx = setup()
  ctx.props.layers[0].map_attached = true
  ctx.props.layers[0].visible = true
  ctx.props.layers[0].opacity = 0.8
  const original = ctx.controller.getCamera()
  await ctx.panel.restoreWorkspace(fixedScene('snapshot'), address)
  const local = ctx.panel.viewLayers.value[0]
  assert.equal(local.asset_id, 'snapshot')
  assert.equal(local.visible, false)
  assert.equal(local.opacity, 0.35)
  const captured = ctx.panel.captureWorkspace()
  assert.equal(captured.time, address.time)
  assert.equal(captured.resolution, address.resolution)
  assert.deepEqual(captured.camera, fixedScene('snapshot').camera)
  assert.equal(Object.hasOwn(captured, 'comparison'), false)
  ctx.panel.changeLayer(local, 'toggle')
  ctx.panel.setOpacity(local, 0.6)
  assert.equal(ctx.props.layers[0].visible, true)
  assert.equal(ctx.props.layers[0].opacity, 0.8)
  assert.equal(ctx.props.layers[0].map_attached, true)
  assert.equal(ctx.events.some(event => ['toggle', 'opacity'].includes(event[0])), false)
  assert.equal(ctx.panel.captureWorkspace().scene.layers[0].map_opacity, 0.6)
  ctx.panel.clearScene()
  assert.ok(ctx.controller.removed.includes('fixed'))
  assert.equal(ctx.panel.viewLayers.value, ctx.props.layers)
  assert.deepEqual(ctx.controller.camera, original)
  ctx.cleanup()
})
test('failed or superseded scene preflight cannot replace the current map', async () => {
  let release
  const ctx = setup({ prepare: states => states[0].asset.asset_id === 'slow' ? new Promise(resolve => { release = resolve }) : Promise.reject(new Error('missing fixed asset')) })
  const slow = ctx.panel.restoreWorkspace(fixedScene('slow'), address)
  await assert.rejects(ctx.panel.restoreWorkspace(fixedScene('missing'), address), /missing fixed asset/)
  release([{ id: 'slow', map_attached: true }])
  await slow
  assert.equal(ctx.panel.viewLayers.value, ctx.props.layers)
  assert.deepEqual(ctx.controller.removed, [])
  ctx.cleanup()
})

test('display areas capture and reopen both camera modes and keep the campus shortcut', t => {
  let extent = null
  const ctx = setup({ extent: () => extent })
  t.after(ctx.cleanup)
  assert.equal(ctx.panel.captureDisplayView(), null)
  extent = { latitude: 23, longitude: 114, radius_m: 1700 }
  const first = ctx.panel.captureDisplayView()
  assert.deepEqual(first, { ...extent, camera: ctx.controller.getCamera() })
  const flat = { ...first.camera, longitude: 114, height: 3500, scene_mode: '2d' }
  ctx.controller.pointMarker = { longitude: 113, latitude: 23 }
  ctx.panel.openDisplayRegion({ id: 'new', name: '广场', ...extent, camera: flat })
  assert.deepEqual(ctx.panel.captureDisplayView().camera, flat)
  assert.equal(ctx.controller.pointMarker, null)
  ctx.panel.openDisplayRegion({ id: 'demo-huangpu', name: '黄埔校区', ...first })
  assert.deepEqual(ctx.panel.captureDisplayView().camera, first.camera)
  assert.deepEqual(ctx.events.filter(([type]) => type === 'campus'), [['campus', 'huangpu']])
})

test('display-region clicks and home fly without sampling weather or capturing an intermediate view', async t => {
  t.mock.timers.enable({ apis: ['Date', 'setTimeout'], now: 1_790_000_000_000 })
  const requests = [], flights = []
  t.mock.method(globalThis, 'fetch', async url => {
    requests.push(url)
    return { ok: true, json: async () => ({ latitude: 24, longitude: 115, code: 71, is_day: true, valid_at: '2026-01-01T00:00:00Z' }) }
  })
  const target = { latitude: 24, longitude: 115, height: 700, heading: 0.5, pitch: -0.8, roll: 0, scene_mode: '3d' }
  const region = { id: 'test-flight', name: '区域', latitude: 24, longitude: 115, radius_m: 1600, camera: target }
  let point = null
  const ctx = setup({
    displayRegions: [region],
    extent: () => point && region,
    weatherPoint: () => point,
    fly(camera) { flights.push(camera); ctx.panel.cameraMoving(); return true },
  })
  t.after(ctx.cleanup)
  assert.equal(ctx.panel.openDisplayRegion(region), true)
  assert.deepEqual(flights, [target])
  point = region
  ctx.panel.onNavigation({ camera: target }, false)
  t.mock.timers.tick(2200)
  assert.equal(ctx.panel.captureDisplayView(), null)
  assert.deepEqual(requests, [])
  ctx.panel.onNavigation({ camera: target }, true)
  t.mock.timers.tick(600)
  await new Promise(setImmediate)
  assert.deepEqual(requests, ['/api/weather/current?lat=24&lon=115'])
  assert.equal(ctx.panel.shownWeather.value.effect, 'snow')
  ctx.panel.home()
  assert.deepEqual(flights, [target, target])
})

test('the primary map waits for the camera to settle and queries weather once', async t => {
  t.mock.timers.enable({ apis: ['Date', 'setTimeout'], now: 1_800_000_000_000 })
  const requests = []
  t.mock.method(globalThis, 'fetch', async url => {
    requests.push(url)
    return { ok: true, json: async () => ({ latitude: 23, longitude: 114, code: 71, is_day: true, valid_at: '2026-01-01T00:00:00Z' }) }
  })
  let point = { latitude: 23, longitude: 113 }
  const ctx = setup({ weatherPoint: () => point, displayRegions: [{ id: 'preview', name: '展示区域', latitude: 23, longitude: 114, radius_m: 5000 }] })
  t.after(() => ctx.cleanup())
  const initial = ctx.controller.getCamera()
  ctx.panel.onNavigation({ camera: initial }, true)
  ctx.panel.cameraMoving()
  point = { latitude: 23, longitude: 114 }
  const target = { ...initial, longitude: 114 }
  ctx.panel.onNavigation({ camera: target }, false)
  t.mock.timers.tick(800)
  assert.deepEqual(requests, [])
  ctx.panel.onNavigation({ camera: target }, true)
  t.mock.timers.tick(600)
  await new Promise(setImmediate)
  assert.deepEqual(requests, ['/api/weather/current?lat=23&lon=114'])
  assert.equal(ctx.panel.shownWeather.value.effect, 'snow')
})

test('the workspace keeps map-picked 3D feedback until leaving its detail card', async t => {
  const ctx = setup({ objectActions(objects) {
    objects.showPicked = id => { objects.selectedId.value = id }
    objects.clearSelection = () => { objects.selectedId.value = '' }
  } })
  t.after(() => ctx.cleanup())
  const pick = { title: '三维对象', layerId: 'a', layerName: '模型', properties: {}, resourceType: '3dtiles' }
  await ctx.panel.onMapSelection({ ...pick, objectId: 'asset-object' })
  await vue.nextTick()
  assert.equal(ctx.objects.selectedId.value, 'asset-object')
  assert.deepEqual(ctx.controller.highlights, [], 'the asset ID must not replace the map pick')
  await ctx.panel.onMapSelection(pick)
  await vue.nextTick()
  assert.deepEqual(ctx.controller.highlights, [])
  ctx.panel.clearObjectSelection()
  await vue.nextTick()
  assert.deepEqual(ctx.controller.highlights.at(-1), ['a', [], undefined], 'return clears even an unindexed map pick')
})

test('an older unindexed 3D pick cannot clear a newer indexed model detail', async t => {
  let finish
  const ctx = setup({ objectActions(objects) {
    objects.setLayer = id => { objects.activeLayerId.value = id; return new Promise(resolve => { finish = resolve }) }
    objects.showPicked = (id, layer) => { objects.activeLayerId.value = layer; objects.selectedId.value = id }
    objects.clearSelection = () => { objects.selectedId.value = '' }
  } })
  t.after(() => ctx.cleanup())
  const model = { title: '三维对象', layerName: '模型', properties: {}, resourceType: '3dtiles' }
  const older = ctx.panel.onMapSelection({ ...model, layerId: 'b' })
  await ctx.panel.onMapSelection({ ...model, layerId: 'a', objectId: 'new-model' })
  finish()
  await older
  assert.equal(ctx.objects.selectedId.value, 'new-model')
})

test('raw picked properties disappear when the pinned resource changes or is removed', async t => {
  const ctx = setup()
  t.after(ctx.cleanup)
  await ctx.panel.onMapSelection({ title: '原始模型', layerId: 'a', layerName: '模型', asset: { asset_id: 'asset-a', version: '1.0.0' }, properties: { name: '原始属性' } })
  assert.equal(ctx.panel.inspectedSelection.value.title, '原始模型')
  ctx.props.layers[0].asset_version = '2.0.0'
  assert.equal(ctx.panel.inspectedSelection.value, null)
  await vue.nextTick()
  ctx.props.layers[0].asset_version = '1.0.0'
  await vue.nextTick()
  assert.equal(ctx.panel.inspectedSelection.value, null)
  await ctx.panel.onMapSelection({ title: '原始模型', layerId: 'a', layerName: '模型', properties: {} })
  ctx.props.layers[0].attached = false
  assert.equal(ctx.panel.inspectedSelection.value, null)
})
