import { beforeEach, mock, test } from 'node:test'
import assert from 'node:assert/strict'

const event = () => {
  const listeners = []
  return { addEventListener(fn) { listeners.push(fn) }, fire() { listeners.forEach(fn => fn()) } }
}
const provider = () => ({ errorEvent: event() })
let ionImageryCalls, ionTerrainCalls, localUrls, localGate, wmtsError, ionTerrainError
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
    },
    createWorldImageryAsync: async () => { ionImageryCalls++; return provider() },
    createWorldTerrainAsync: async () => { ionTerrainCalls++; if (ionTerrainError) throw ionTerrainError; return provider() },
    TileMapServiceImageryProvider: {
      fromUrl: async url => { localUrls.push(url); if (localGate) await localGate; return provider() },
    },
    buildModuleUrl: path => path,
  },
})
const { initializeBasemap } = await import('../src/map/basemap.ts')

beforeEach(() => {
  ionImageryCalls = ionTerrainCalls = 0
  localUrls = []
  localGate = wmtsError = ionTerrainError = undefined
  delete Ion.defaultAccessToken
})
function setup() {
  const imagery = [], notices = []
  let alive = true
  const viewer = {
    imageryLayers: { addImageryProvider: value => imagery.push(value) },
    scene: { requestRender() {} },
    terrainProvider: 'ellipsoid',
  }
  return { viewer, imagery, notices, destroy() { alive = false },
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
