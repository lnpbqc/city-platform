import { test } from 'node:test'
import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import { parse } from 'vue/compiler-sfc'
import ts from 'typescript'
import * as vue from 'vue'

const source = await readFile(new URL('../src/components/MapWorkspace.vue', import.meta.url), 'utf8')
const { descriptor } = parse(source)
const javascript = ts.transpileModule(descriptor.scriptSetup.content, {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
}).outputText
const create = new Function('require', 'defineProps', 'defineEmits', 'defineExpose', 'exports', 'window', 'document', `${javascript}
  return { onMapReady, beginDraw, drawing, objectsOpen, toggleObjects, onNavigation, toggleMode, toggleComparison, comparisonOpen, restoreWorkspace, captureWorkspace, clearScene, changeLayer, setOpacity, viewLayers, timeAxis, timeAxisHeight }
`)
const geometry = { type: 'Polygon', coordinates: [[[113, 23], [114, 23], [114, 24], [113, 23]]] }
function setup(options = {}) {
  const hooks = [], queries = [], events = []
  const props = vue.reactive({ active: true, layers: [
    { id: 'a', attached: true, asset_id: 'asset-a', asset_version: '1.0.0' },
    { id: 'b', attached: true, asset_id: 'asset-b', asset_version: '1.0.0' },
  ] })
  const objects = Object.fromEntries(['activeLayerId', 'items', 'total', 'page', 'pageSize', 'loading', 'error',
    'type', 'q', 'selectedId', 'selected', 'detailLoading', 'detailError', 'areaGeometry', 'areaIds',
    'selectionProgress'].map(key => [key, vue.ref(null)]))
  objects.activeLayerId.value = 'a'
  objects.areaIds.value = []
  for (const key of ['refresh', 'setLayer', 'setPage', 'applyFilters', 'select', 'showPicked', 'clearArea', 'clearSelection']) objects[key] = () => {}
  objects.selectArea = value => queries.push({ layer: objects.activeLayerId.value, geometry: value })
  const controller = {
    cancellations: 0,
    initialize() {}, highlightObjects() {}, setMode() {}, resume() {},
    cancelAreaSelection() { this.cancellations++; this.cancelled?.() },
    beginAreaSelection(mode, callback, cancelled) { this.callback = callback; this.cancelled = cancelled },
    getCamera() { return this.camera ?? { longitude: 113, latitude: 23, height: 800, heading: 0, pitch: -1, roll: 0, scene_mode: '3d' } },
    setCamera(camera) { this.camera = camera },
    removed: [], remove(layer) { this.removed.push(layer.id); layer.attached = false },
    async load(layer) { layer.attached = true; layer.status = 'ready' }, appearance() {}, syncOrder() {},
  }
  const scope = vue.effectScope()
  const panel = scope.run(() => create(name => {
    if (name === 'vue') return { ...vue, onMounted() {}, onBeforeUnmount: hook => hooks.push(hook) }
    if (name === '../composables/useObjects') return { useObjects: () => objects }
    if (name === '../composables/useTemporalLayers') return { useTemporalLayers: () => { const time = vue.ref(''); return { time, resolution: vue.ref('hour'), times: vue.ref(['2026-10-25T00:00:00Z']), pause() {}, paint() {}, setTime(value) { time.value = value } } } }
    if (name === '../linkedCameras') return { linkedCameras: () => () => {} }
    if (name === '../sceneLayers') return {
      captureLayers: layers => layers.map(layer => ({ layer_id: layer.id, asset: { asset_id: layer.asset_id, version: layer.asset_version }, map_attached: layer.attached, map_visible: layer.visible, map_opacity: layer.opacity })),
      prepareSceneLayers: options.prepare ?? (async states => states.map(state => ({ id: state.layer_id, asset_id: state.asset.asset_id, asset_version: state.asset.version, map_attached: state.map_attached, visible: state.map_visible, opacity: state.map_opacity, order: state.order, attached: false }))),
    }
    if (name === '../layerTree') return {}
    if (name === '../mapNavigation') return { readMapView: () => null }
    if (name === '../regions') return { demoRegion: {} }
    if (name.endsWith('.vue')) return {}
    throw new Error(`Unexpected workspace dependency: ${name}`)
  }, () => props, () => (...args) => events.push(args), () => {}, {}, { localStorage: {}, removeEventListener() {} }, { removeEventListener() {} }))
  panel.onMapReady(controller)
  return { panel, props, objects, controller, queries, events, cleanup() { hooks.forEach(hook => hook()); scope.stop() } }
}

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

test('comparison waits for the requested scene mode before creating its second view', () => {
  const ctx = setup()
  const camera = { longitude: 113, latitude: 23, height: 800, heading: 0, pitch: -1, roll: 0, scene_mode: '3d' }
  ctx.panel.onNavigation({ camera }, false)
  ctx.panel.toggleMode()
  ctx.panel.toggleComparison()
  assert.equal(ctx.panel.comparisonOpen.value, false)
  ctx.panel.onNavigation({ camera: { ...camera, scene_mode: '2d' } }, false)
  ctx.panel.toggleComparison()
  assert.equal(ctx.panel.comparisonOpen.value, true)
  ctx.cleanup()
})

const fixedScene = id => ({ id, version: 1, name: id, camera: { longitude: 114, latitude: 24, height: 500, heading: 0.2, pitch: -1.4, roll: 0, scene_mode: '3d' },
  current_time: '2026-10-25T01:00:00Z', layers: [{ layer_id: 'fixed', asset: { asset_id: id, version: '2.0.0' }, map_attached: true, map_visible: false, map_opacity: 0.35, order: 0 }] })
const address = { page: 'map', resolution: 'hour', comparison: { time: '2026-10-26T01:00:00Z', resolution: 'day' } }
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
  assert.equal(ctx.panel.comparisonOpen.value, true)
  assert.deepEqual(ctx.panel.captureWorkspace().comparison, address.comparison)
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
