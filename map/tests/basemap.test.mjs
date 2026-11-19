import { beforeEach, mock, test } from 'node:test'
import assert from 'node:assert/strict'

const event = () => {
  const listeners = new Set()
  return { addEventListener(fn) { listeners.add(fn); return () => listeners.delete(fn) }, fire() { listeners.forEach(fn => fn()) }, get size() { return listeners.size } }
}
const provider = () => ({ errorEvent: event() })
let ionImageryCalls, ionTerrainCalls, localUrls, localGate, wmtsError, ionTerrainError, tileCalls, tileResponse
const Ion = {}
class WebMercatorTilingScheme {}
class Credit {
  constructor(html, showOnScreen) { Object.assign(this, { html, showOnScreen }) }
}
mock.module('cesium', {
  exports: {
    Ion,
    Credit,
    WebMercatorTilingScheme,
    WebMapTileServiceImageryProvider: class {
      constructor(options) {
        if (wmtsError) throw wmtsError
        Object.assign(this, options, provider())
      }
      requestImage(x, y, level) {
        tileCalls.push([this.layer, x, y, level])
        return tileResponse()
      }
    },
    createWorldImageryAsync: async () => { ionImageryCalls++; return provider() },
    createWorldTerrainAsync: async () => { ionTerrainCalls++; if (ionTerrainError) throw ionTerrainError; return provider() },
    TileMapServiceImageryProvider: {
      fromUrl: async url => { localUrls.push(url); if (localGate) await localGate; return provider() },
    },
    buildModuleUrl: path => path,
  },
})
const { initializeBasemap, createBasemapSwitcher } = await import('../src/map/basemap.ts')

beforeEach(() => {
  ionImageryCalls = ionTerrainCalls = 0
  localUrls = []
  localGate = wmtsError = ionTerrainError = undefined
  tileCalls = []
  tileResponse = () => Promise.resolve({ width: 256, height: 256 })
  delete Ion.defaultAccessToken
})
function setup() {
  const imagery = [], notices = []
  let alive = true
  const viewer = {
    canvas: { clientWidth: 800, clientHeight: 600 },
    camera: { moveStart: event(), moveEnd: event() },
    imageryLayers: {
      addImageryProvider(value, index = imagery.length) { value.show = true; imagery.splice(index, 0, value); return value },
      remove(value) { imagery.splice(imagery.indexOf(value), 1) },
    },
    scene: { requestRender() {} },
    terrainProvider: 'ellipsoid',
  }
  return { viewer, imagery, notices, destroy() { alive = false },
    switcher: env => createBasemapSwitcher(viewer, env, () => alive, message => notices.push(message)),
    run: env => initializeBasemap(viewer, env, () => alive, message => notices.push(message)) }
}

test('Tianditu loads imagery without duplicate baked POI annotation layer and never requests ion', async () => {
  const app = setup()
  const terrain = await app.run({ VITE_BASEMAP_PROVIDER: 'tianditu', VITE_TIANDITU_KEY: ' key+/ ', VITE_CESIUM_ION_TOKEN: 'ignored' })
  assert.equal(terrain, undefined)
  assert.equal(app.imagery.length, 1)
  for (const [index, layer] of ['img'].entries()) {
    const imagery = app.imagery[index]
    assert.equal(imagery.url, `https://t{s}.tianditu.gov.cn/${layer}_w/wmts?tk=key%2B%2F`)
    assert.equal(imagery.layer, layer)
    assert.equal(imagery.tileMatrixSetID, 'w')
    assert.equal(imagery.style, 'default')
    assert.equal(imagery.format, 'tiles')
    assert.ok(imagery.tilingScheme instanceof WebMercatorTilingScheme)
    assert.equal(imagery.minimumLevel, 1)
    assert.equal(imagery.maximumLevel, 18)
    assert.deepEqual(imagery.tileMatrixLabels, Array.from({ length: 19 }, (_, i) => String(i)))
    assert.deepEqual(imagery.subdomains, ['0', '1', '2', '3', '4', '5', '6', '7'])
    assert.match(imagery.credit.html, /天地图/)
    assert.equal(imagery.credit.showOnScreen, true)
  }
  assert.equal(ionImageryCalls, 0)
  assert.equal(ionTerrainCalls, 0)
  assert.equal(Ion.defaultAccessToken, undefined)
  assert.deepEqual(localUrls, [])
  assert.equal(app.viewer.terrainProvider, 'ellipsoid')
})

test('missing or blank Tianditu key falls back to local imagery even with an ion token', async () => {
  for (const key of [undefined, '  ']) {
    const app = setup()
    assert.equal(await app.run({ VITE_BASEMAP_PROVIDER: 'tianditu', VITE_TIANDITU_KEY: key, VITE_CESIUM_ION_TOKEN: 'ignored' }), undefined)
    assert.equal(app.imagery.length, 1)
    assert.match(app.notices[0], /VITE_TIANDITU_KEY/)
    assert.equal(app.viewer.terrainProvider, 'ellipsoid')
  }
  assert.deepEqual(localUrls, ['Assets/Textures/NaturalEarthII', 'Assets/Textures/NaturalEarthII'])
  assert.equal(ionImageryCalls + ionTerrainCalls, 0)
})

test('default and explicit cesium modes preserve local imagery and return ion terrain for the caller', async () => {
  for (const mode of [undefined, 'cesium']) {
    const local = setup()
    assert.equal(await local.run({ VITE_BASEMAP_PROVIDER: mode }), undefined)
    assert.equal(local.imagery.length, 1)
    assert.match(local.notices[0], /尚未配置 ion Token/)
    const online = setup()
    const terrain = await online.run({ VITE_BASEMAP_PROVIDER: mode, VITE_CESIUM_ION_TOKEN: 'ion-token' })
    assert.equal(online.imagery.length, 1)
    assert.ok(terrain?.errorEvent)
    // The map controller decides whether the terrain is shown.
    assert.equal(online.viewer.terrainProvider, 'ellipsoid')
    terrain.errorEvent.fire()
    assert.match(online.notices.at(-1), /地形瓦片加载失败/)
  }
  assert.equal(ionImageryCalls, 2)
  assert.equal(ionTerrainCalls, 2)
  assert.equal(Ion.defaultAccessToken, 'ion-token')
})

test('ion terrain failure keeps the ellipsoid and reports the source', async () => {
  const app = setup()
  ionTerrainError = new Error('terrain failed')
  assert.equal(await app.run({ VITE_CESIUM_ION_TOKEN: 'ion-token' }), undefined)
  assert.match(app.notices.at(-1), /ion 地形不可用/)
  assert.equal(app.viewer.terrainProvider, 'ellipsoid')
})

test('Tianditu tile errors give actionable notices without switching providers and stop after destroy', async () => {
  const app = setup()
  await app.run({ VITE_BASEMAP_PROVIDER: 'tianditu', VITE_TIANDITU_KEY: 'key' })
  app.imagery.forEach(value => value.errorEvent.fire())
  assert.equal(app.notices.length, 1)
  assert.ok(app.notices.every(value => /天地图.*Key.*网络/.test(value)))
  assert.equal(ionImageryCalls + ionTerrainCalls + localUrls.length, 0)
  app.destroy()
  app.imagery.forEach(value => value.errorEvent.fire())
  assert.equal(app.notices.length, 1)
})

test('Tianditu initialization failure reports the source without ion fallback', async () => {
  wmtsError = new Error('provider failed')
  const app = setup()
  await app.run({ VITE_BASEMAP_PROVIDER: 'tianditu', VITE_TIANDITU_KEY: 'key', VITE_CESIUM_ION_TOKEN: 'ignored' })
  assert.match(app.notices[0], /天地图底图不可用/)
  assert.equal(ionImageryCalls + ionTerrainCalls, 0)
})

test('destroy during asynchronous local initialization prevents late imagery and notices', async () => {
  let resolve
  localGate = new Promise(done => { resolve = done })
  const app = setup()
  const loading = app.run({})
  app.destroy()
  resolve()
  await loading
  assert.deepEqual(app.imagery, [])
  assert.deepEqual(app.notices, [])
})

test('already destroyed viewers do not initialize Tianditu', async () => {
  const app = setup()
  app.destroy()
  await app.run({ VITE_BASEMAP_PROVIDER: 'tianditu', VITE_TIANDITU_KEY: 'key' })
  assert.deepEqual(app.imagery, [])
})

test('switching replaces only owned base layers, pairs vector labels and leaves terrain alone', async () => {
  const app = setup()
  const switching = app.switcher({ VITE_TIANDITU_KEY: 'key', VITE_CESIUM_ION_TOKEN: 'token' })
  assert.equal(await switching.setBasemap('imagery'), true)
  const overlay = { name: 'business overlay' }
  app.imagery.push(overlay)
  assert.equal(await switching.setBasemap('vector'), true)
  assert.deepEqual(app.imagery.filter(layer => layer.show !== false).map(layer => layer.layer ?? layer.name), ['vec', 'cva', 'business overlay'])
  assert.equal(app.viewer.terrainProvider, 'ellipsoid')
  assert.equal(ionTerrainCalls, 0)
  assert.equal(await switching.setBasemap('imagery'), true)
  assert.equal(app.imagery.length, 4)
  assert.equal(app.imagery.at(-1), overlay)
})

test('missing key and failed initialization preserve the displayed base layers', async () => {
  const app = setup()
  const switching = app.switcher({})
  await switching.setBasemap('imagery')
  const previous = [...app.imagery]
  assert.equal(await switching.setBasemap('vector'), false)
  assert.deepEqual(app.imagery, previous)
  const keyed = app.switcher({ VITE_TIANDITU_KEY: 'key' })
  wmtsError = new Error('denied')
  assert.equal(await keyed.setBasemap('vector'), false)
  assert.deepEqual(app.imagery, previous)
  assert.match(app.notices.at(-1), /天地图/)
})

test('only the most recent request commits and stale providers do not report tile errors', async () => {
  const app = setup()
  const switching = app.switcher({ VITE_TIANDITU_KEY: 'key' })
  let release
  localGate = new Promise(resolve => { release = resolve })
  const pending = switching.setBasemap('imagery')
  assert.equal(await switching.setBasemap('vector'), true)
  const oldVector = app.imagery[0]
  release()
  assert.equal(await pending, false)
  assert.deepEqual(app.imagery.filter(layer => layer.show).map(layer => layer.layer), ['vec', 'cva'])
  await switching.setBasemap('imagery')
  const notices = app.notices.length
  oldVector.errorEvent.fire()
  assert.equal(app.notices.length, notices)
  app.imagery.find(layer => layer.show).errorEvent.fire()
  assert.match(app.notices.at(-1), /影像/)
})

test('destroy while switching prevents later layer changes and notices', async () => {
  const app = setup()
  const switching = app.switcher({})
  let release
  localGate = new Promise(resolve => { release = resolve })
  const pending = switching.setBasemap('imagery')
  app.destroy()
  release()
  assert.equal(await pending, false)
  assert.deepEqual(app.imagery, [])
  assert.deepEqual(app.notices, [])
})

test('a partially added vector pair rolls back without removing the previous imagery', async () => {
  const app = setup()
  const switching = app.switcher({ VITE_TIANDITU_KEY: 'key' })
  await switching.setBasemap('imagery')
  const previous = [...app.imagery]
  const add = app.viewer.imageryLayers.addImageryProvider
  app.viewer.imageryLayers.addImageryProvider = function (provider, index) {
    if (provider.layer === 'cva') throw new Error('cannot add labels')
    return add.call(this, provider, index)
  }
  assert.equal(await switching.setBasemap('vector'), false)
  assert.deepEqual(app.imagery, previous)
  assert.match(app.notices.at(-1), /保留原底图/)
})

test('base layers and optional annotations are reused, hidden independently and released on destroy', async () => {
  const app = setup()
  const switching = app.switcher({ VITE_BASEMAP_PROVIDER: 'tianditu', VITE_TIANDITU_KEY: 'key' })
  await switching.setBasemap('imagery')
  const img = app.imagery[0]
  await switching.setBasemap('imagery', { annotations: true })
  const cia = app.imagery.find(layer => layer.layer === 'cia')
  assert.ok(cia?.show)
  assert.deepEqual(app.imagery.filter(layer => layer.show).map(layer => layer.layer), ['img', 'cia'])
  await switching.setBasemap('vector', { annotations: false })
  assert.equal(img.show, false)
  assert.equal(cia.show, false)
  assert.deepEqual(app.imagery.filter(layer => layer.show).map(layer => layer.layer), ['vec'])
  await switching.setBasemap('imagery', { annotations: true })
  assert.equal(app.imagery[0], img)
  assert.equal(app.imagery[1], cia)
  assert.equal(app.imagery.length, 3)
  await switching.setBasemap('imagery', { annotations: false })
  assert.equal(cia.show, false)
  const notices = app.notices.length
  cia.errorEvent.fire()
  assert.equal(app.notices.length, notices)
  switching.destroy()
  assert.deepEqual(app.imagery, [])
  assert.equal(await switching.setBasemap('vector'), false)
})

test('Tianditu level setting accepts only integers 1 through 18 for base and labels', async () => {
  for (const [value, expected] of [['16', 16], ['1', 1], ['18', 18], ['', 18], ['0', 18], ['19', 18], ['1.5', 18], ['bad', 18]]) {
    const app = setup()
    await app.switcher({ VITE_TIANDITU_KEY: 'key', VITE_TIANDITU_MAX_LEVEL: value }).setBasemap('vector')
    assert.deepEqual(app.imagery.map(layer => layer.maximumLevel), [expected, expected])
  }
})

test('Cesium imagery supports optional Tianditu annotation and missing key preserves imagery', async () => {
  const app = setup()
  await app.switcher({ VITE_CESIUM_ION_TOKEN: 'token', VITE_TIANDITU_KEY: 'key' }).setBasemap('imagery', { annotations: true })
  assert.equal(ionImageryCalls, 1)
  assert.equal(app.imagery[1].layer, 'cia')
  const unkeyed = setup()
  const switching = unkeyed.switcher({})
  await switching.setBasemap('imagery')
  const previous = [...unkeyed.imagery]
  assert.equal(await switching.setBasemap('imagery', { annotations: true }), false)
  assert.deepEqual(unkeyed.imagery, previous)
})

test('Tianditu reuses pending and completed tiles when revisiting a view or switching styles', async t => {
  const app = setup(), switching = app.switcher({ VITE_BASEMAP_PROVIDER: 'tianditu', VITE_TIANDITU_KEY: 'key' })
  t.after(() => switching.destroy())
  await switching.setBasemap('imagery')
  const img = app.imagery[0]
  let resolve
  tileResponse = () => new Promise(done => { resolve = done })
  const first = img.requestImage(1, 2, 4)
  const duplicate = img.requestImage(1, 2, 4)
  assert.equal(tileCalls.length, 1, 'a pending tile must issue only one network request')
  const image = { width: 256, height: 256 }
  resolve(image)
  assert.equal(await first, image)
  assert.equal(await duplicate, image)
  await switching.setBasemap('vector', { annotations: false })
  await switching.setBasemap('imagery')
  assert.equal(await img.requestImage(1, 2, 4), image)
  assert.equal(tileCalls.length, 1, 'switching back reuses decoded tiles')
})

test('Tianditu defers intermediate camera views, coalesces settling and skips hidden canvases', async t => {
  t.mock.timers.enable({ apis: ['setTimeout', 'Date'], now: 1000 })
  const app = setup(), switching = app.switcher({ VITE_TIANDITU_KEY: 'key' })
  t.after(() => switching.destroy())
  await switching.setBasemap('vector')
  const vec = app.imagery[0]
  app.viewer.camera.moveStart.fire()
  for (let x = 0; x < 20; x++) assert.equal(vec.requestImage(x, 0, 8), undefined)
  assert.equal(tileCalls.length, 0)
  app.viewer.camera.moveEnd.fire()
  t.mock.timers.tick(100)
  assert.equal(vec.requestImage(1, 0, 8), undefined)
  app.viewer.camera.moveStart.fire()
  t.mock.timers.tick(200)
  assert.equal(vec.requestImage(2, 0, 8), undefined)
  app.viewer.camera.moveEnd.fire()
  t.mock.timers.tick(180)
  await vec.requestImage(3, 0, 8)
  assert.equal(tileCalls.length, 1)
  app.viewer.canvas.clientWidth = 0
  assert.equal(vec.requestImage(4, 0, 8), undefined)
  assert.equal(tileCalls.length, 1)
  app.viewer.canvas.clientWidth = 800
  await vec.requestImage(4, 0, 8)
  assert.equal(tileCalls.length, 2)
  switching.destroy()
  assert.equal(app.viewer.camera.moveStart.size, 0)
  assert.equal(app.viewer.camera.moveEnd.size, 0)
})

test('Tianditu base and labels share a bounded request burst and concurrent limit', async t => {
  t.mock.timers.enable({ apis: ['setTimeout', 'Date'], now: 1000 })
  const app = setup(), switching = app.switcher({ VITE_TIANDITU_KEY: 'key' })
  t.after(() => switching.destroy())
  await switching.setBasemap('vector')
  const [vec, cva] = app.imagery
  const done = []
  tileResponse = () => new Promise(resolve => done.push(resolve))
  const pending = [vec.requestImage(0, 0, 8), cva.requestImage(0, 0, 8), vec.requestImage(1, 0, 8), cva.requestImage(1, 0, 8)]
  assert.equal(vec.requestImage(2, 0, 8), undefined)
  assert.equal(tileCalls.length, 4)
  t.mock.timers.tick(200)
  assert.equal(cva.requestImage(2, 0, 8), undefined, 'four active requests keep later tiles deferred')
  done.forEach(resolve => resolve({ width: 256, height: 256 }))
  await Promise.all(pending)
  tileResponse = () => Promise.resolve({ width: 256, height: 256 })
  await vec.requestImage(2, 0, 8)
  assert.equal(tileCalls.length, 5)
  await cva.requestImage(2, 0, 8)
  await vec.requestImage(3, 0, 8)
  await cva.requestImage(3, 0, 8)
  assert.equal(vec.requestImage(4, 0, 8), undefined, 'completed requests still count toward the current burst')
  t.mock.timers.tick(200)
  await vec.requestImage(4, 0, 8)
  assert.equal(tileCalls.length, 9)
})

test('Tianditu keeps a bounded recent-tile cache without caching failed or deferred requests', async t => {
  t.mock.timers.enable({ apis: ['setTimeout', 'Date'], now: 1000 })
  const app = setup(), switching = app.switcher({ VITE_TIANDITU_KEY: 'key' })
  t.after(() => switching.destroy())
  await switching.setBasemap('vector', { annotations: false })
  const vec = app.imagery[0]
  for (let x = 0; x < 128; x++) {
    t.mock.timers.tick(200)
    await vec.requestImage(x, 0, 8)
  }
  await vec.requestImage(0, 0, 8)
  await vec.requestImage(128, 0, 8)
  const count = tileCalls.length
  await vec.requestImage(0, 0, 8)
  assert.equal(tileCalls.length, count, 'a recently used tile remains cached')
  await vec.requestImage(1, 0, 8)
  assert.equal(tileCalls.length, count + 1, 'the least recently used tile is evicted')
  t.mock.timers.tick(200)
  tileResponse = () => Promise.reject(new Error('offline'))
  await assert.rejects(vec.requestImage(200, 0, 8), /offline/)
  tileResponse = () => undefined
  assert.equal(vec.requestImage(200, 0, 8), undefined)
  tileResponse = () => Promise.resolve({ width: 256, height: 256 })
  assert.ok(await vec.requestImage(200, 0, 8), 'failed and scheduler-deferred requests may be retried')
  const calls = tileCalls.length
  switching.destroy()
  assert.equal(vec.requestImage(201, 0, 8), undefined)
  t.mock.timers.tick(1000)
  assert.equal(tileCalls.length, calls)
})
