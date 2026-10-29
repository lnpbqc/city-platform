import { beforeEach, mock, test } from 'node:test'
import assert from 'node:assert/strict'

const deferred = () => {
  let resolve
  let reject
  const promise = new Promise((yes, no) => {
    resolve = yes
    reject = no
  })
  return { promise, resolve, reject }
}
let geoRequest, tileRequest, viewer, addGate, click, move, down, up, geoSource, tileSource
beforeEach(t => { t.mock.method(globalThis, 'fetch', async () => new Response('{"type":"FeatureCollection","features":[]}')) })
const event = () => {
  const listeners = new Set()
  return { addEventListener(fn) { listeners.add(fn); return () => listeners.delete(fn) }, fire(...args) { for (const fn of listeners) fn(...args) } }
}
let terrainBounds, terrainGate, terrainStarted, terrainError
mock.module('../src/buildingTerrain.ts', {
  exports: {
    sampleBuildingTerrain: async (polygons) => {
      terrainStarted.resolve()
      if (terrainGate) await terrainGate.promise
      if (terrainError) throw terrainError
      return polygons.map(() => terrainBounds)
    },
  },
})
class GeoJsonDataSource {
  static load(source) {
    geoSource = source
    return geoRequest.promise
  }
  entities = { values: [], contains: () => false }
}
class Cesium3DTileset {
  static fromUrl(source) {
    tileSource = source
    return tileRequest.promise
  }
  destroyed = false
  tileFailed = event()
  loadProgress = event()
  initialTilesLoaded = event()
  tileUnload = event()
  boundingSphere = { center: { longitude: 113, latitude: 23, height: 0 }, radius: 500 }
  isDestroyed() {
    return this.destroyed
  }
  destroy() {
    this.destroyed = true
  }
}
const color = {
  withAlpha(alpha) {
    return { ...color, alpha }
  },
}
class Viewer {
  clock = { currentTime: 0 }
  resources = new Set()
  scene = {
    mode: 3,
    canvas: { clientWidth: 800, clientHeight: 600 },
    globe: { pick: () => undefined, ellipsoid: {} },
    pick: () => undefined,
    morphTo3D: () => { this.scene.mode = 3 },
    morphTo2D: () => { this.scene.mode = 2 },
    morphComplete: event(),
    backgroundColor: null,
    renderError: { addEventListener() {} },
    screenSpaceCameraController: { enableInputs: true },
    requestRender() {},
    primitives: {
      add: (resource) => this.resources.add(resource),
      remove: (resource) => {
        const found = this.resources.delete(resource)
        if (found) resource.destroy()
        return found
      },
    },
  }
  camera = {
    changed: event(),
    moveEnd: event(),
    positionCartographic: { longitude: 113, latitude: 23, height: 900 },
    roll: 0,
    pitch: -52,
    heading: 0.4,
    positionWC: { x: 0, y: 0, z: 100 },
    getPickRay: (center) => ({ center }),
    pickEllipsoid: () => undefined,
    lookUp: () => {
      this.lookedUp = true
    },
    flyToBoundingSphere: (sphere, options) => {
      this.lastFlight = { sphere, options }
    },
    setView: (options) => { this.lastView = options; this.camera.positionCartographic = options.destination; Object.assign(this.camera, options.orientation) },
  }
  imageryLayers = { addImageryProvider() {} }
  entities = {
    values: [],
    add: (options) => {
      const entity = Object.assign(new Noop(), options)
      this.entities.values.push(entity)
      return entity
    },
    remove: (entity) => {
      const index = this.entities.values.indexOf(entity)
      if (index !== -1) this.entities.values.splice(index, 1)
    },
  }
  dataSources = {
    raiseToTop: (resource) => { this.raisedSources ??= []; this.raisedSources.push(resource) },
    add: async (resource) => {
      this.resources.add(resource)
      if (addGate) await addGate.promise
      return resource
    },
    remove: (resource) => this.resources.delete(resource),
  }
  constructor() {
    viewer = this
  }
  async flyTo(resource, options) {
    this.lastResourceFlight = { resource, options }
    return true
  }
  destroy() {
    for (const resource of this.resources) resource.destroy?.()
    this.resources.clear()
  }
}
class Noop {}
class Cartesian2 {
  constructor(x, y) {
    Object.assign(this, { x, y })
  }
}
class ConstantProperty {
  constructor(value) {
    this.value = value
  }
  getValue() {
    return this.value
  }
}
class ConstantPositionProperty extends ConstantProperty {
  setValue(value) { this.value = value }
}
class ColorMaterialProperty {
  constructor(value) {
    this.color = value
  }
}
class BoundingSphere {
  constructor(center, radius) {
    this.center = center
    this.radius = radius
  }
}
class HeadingPitchRange {
  constructor(heading, pitch, range) {
    Object.assign(this, { heading, pitch, range })
  }
}
class Handler {
  constructor(target) { this.target = target; viewer.handlers ??= []; viewer.handlers.push(this) }
  actions = new Map()
  getInputAction(type) { return this.actions.get(type) }
  setInputAction(action, type) { this.actions.set(type, action); if (type === 1) click = action; else if (type === 2) move = action; else if (type === 3) down = action; else if (type === 4) up = action }
  destroy() { this.destroyed = true }
}
mock.module('cesium', {
  exports: {
    Viewer,
    Ion: {},
    Math: { toRadians: (value) => value, toDegrees: (value) => value },
    Cartographic: { fromCartesian: (value) => value },
    EllipsoidGeodesic: class { surfaceDistance = 350 },
    Cartesian2,
    Cartesian3: {
      distance: (a, b) => Math.hypot(a.x - b.x, a.y - b.y, a.z - b.z),
      fromDegrees: (longitude, latitude, height) => ({
        longitude,
        latitude,
        height,
      }),
    },
    Color: { fromCssColorString: () => color, WHITE: color },
    GeoJsonDataSource,
    Cesium3DTileset,
    Cesium3DTileStyle: Noop,
    ColorMaterialProperty,
    ConstantProperty,
    ConstantPositionProperty,
    Credit: Noop,
    VerticalOrigin: { BOTTOM: 1 },
    HeightReference: {
      NONE: 0,
      CLAMP_TO_TERRAIN: 3,
      RELATIVE_TO_TERRAIN: 4,
      RELATIVE_TO_GROUND: 2,
    },
    ClassificationType: { TERRAIN: 0 },
    ScreenSpaceEventHandler: Handler,
    ScreenSpaceEventType: { LEFT_CLICK: 1, MOUSE_MOVE: 2, LEFT_DOWN: 3, LEFT_UP: 4 },
    Entity: Noop,
    SceneMode: { SCENE3D: 3, SCENE2D: 2, MORPHING: 0 },
    createWorldImageryAsync() {},
    createWorldTerrainAsync() {},
    TileMapServiceImageryProvider: {
      fromUrl: async () => ({ errorEvent: { addEventListener() {} } }),
    },
    buildModuleUrl: (path) => path,
    HeadingPitchRange,
    BoundingSphere,
  },
})
const { createMapController } = await import('../src/mapController.ts')

for (const sample of [
  { name: 'local planar polygons', kind: 'upload', geometry: { type: 'Polygon', coordinates: [[[113, 23], [114, 23], [114, 24], [113, 23]]] }, expected: true },
  { name: 'local XYZ polygon', kind: 'upload', geometry: { type: 'Polygon', coordinates: [[[113, 23, 0], [114, 23, 0], [114, 24, 0], [113, 23, 0]]] }, expected: false },
  { name: 'extruded local polygon', kind: 'default', height: 20, geometry: { type: 'Polygon', coordinates: [[[113, 23], [114, 23], [114, 24], [113, 23]]] }, expected: false },
  { name: 'point height attribute', kind: 'upload', height: 20, geometry: { type: 'Point', coordinates: [113, 23] }, expected: true },
  { name: 'external planar data', kind: 'external', geometry: { type: 'Point', coordinates: [113, 23] }, expected: undefined },
  { name: 'existing catalog restriction', kind: 'upload', orderable: false, geometry: { type: 'Point', coordinates: [113, 23] }, expected: false },
]) test(`scene order restoration checks actual pinned geometry: ${sample.name}`, async t => {
  const { controller, layer } = setup()
  Object.assign(layer, { asset_source_kind: sample.kind, order: 3 })
  if ('orderable' in sample) layer.orderable = sample.orderable
  t.mock.method(globalThis, 'fetch', async () => new Response(JSON.stringify({ type: 'FeatureCollection',
    features: [{ type: 'Feature', geometry: sample.geometry, properties: { map_extrude_height_m: sample.height } }] })))
  const source = new GeoJsonDataSource()
  const loading = controller.load(layer)
  geoRequest.resolve(source)
  await loading
  assert.equal(layer.orderable, sample.expected)
  controller.syncOrder([layer])
  assert.equal(viewer.raisedSources?.includes(source) ?? false, sample.expected === true)
  controller.destroy()
})

function setup(type = 'geojson', onBoundaryState = () => {}, onNavigation = () => {}) {
  geoRequest = deferred()
  tileRequest = deferred()
  addGate = undefined
  terrainBounds = { minimum: -8, maximum: 12 }
  terrainGate = undefined
  terrainStarted = deferred()
  terrainError = undefined
  const notices = []
  const picks = []
  const controller = createMapController(
    { ownerDocument: { createElement: () => ({ style: {}, setAttribute() {}, remove() { this.removed = true } }) },
      appendChild(element) { element.parent = this } },
    (selection) => picks.push(selection),
    (message) => notices.push(message),
    onBoundaryState,
    onNavigation,
  )
  const layer = {
    type,
    url: '/test',
    color: '#347af0',
    opacity: 1,
    visible: true,
    attached: false,
    status: 'idle',
    error: '',
  }
  return { controller, layer, notices, picks }
}

test('time updates reuse dynamic entities, preserve zero, hide missing and keep opacity/highlighting coherent', async t => {
  const { controller, layer } = setup()
  const objectId = '2f3982d2-41e0-519a-ad92-23346a334ed2'
  Object.assign(layer, { id: 'dynamic', static: false, source: '', asset_id: 'asset-one', asset_version: '1.0.0', object_count: 1 })
  const data = { type: 'FeatureCollection', features: [{ type: 'Feature', properties: {}, geometry: { type: 'Point', coordinates: [113, 23] } }] }
  t.mock.method(globalThis, 'fetch', async url => new Response(JSON.stringify(String(url).includes('/versions/') ? { status: 'ready', entry_url: '/pinned' } : data)))
  const source = new GeoJsonDataSource()
  const entity = Object.assign(new Noop(), { id: objectId, point: {} })
  source.entities.values = [entity]
  geoRequest.resolve(source)
  await controller.load(layer)
  assert.equal(entity.show, false, 'pending values hide the static sample value')
  const frame = value => ({ layer_id: layer.id, asset: { asset_id: 'asset-one', version: '1.0.0' }, time: '2026-10-25T00:00:00Z', resolution: 'hour', unit: 'cm',
    items: [{ object_id: objectId, geometry: value === null ? null : { type: 'Point', coordinates: [113, 23] }, value, missing: value === null }] })
  controller.showTemporal(layer, frame(0))
  assert.equal(entity.show, true)
  controller.highlightObjects(layer.id, [objectId], objectId)
  controller.showTemporal(layer, frame(null))
  assert.equal(entity.show, false, 'highlight does not turn missing into a value')
  controller.highlightObjects(null, [])
  controller.showTemporal(layer, frame(20))
  layer.opacity = 0.4
  controller.appearance(layer)
  assert.equal(entity.show, true)
  assert.equal(entity.point.color.value.alpha, 0.4)
  assert.equal(source.entities.values[0], entity)
  assert.equal(viewer.resources.size, 1)
  controller.showTemporal(layer, null)
  assert.equal(entity.show, false)
  controller.destroy()
})

test('navigation publishes the completed scene mode and skips intermediate morph cameras', () => {
  const readings = []
  const { controller } = setup('geojson', () => {}, value => readings.push(value))
  const count = readings.length
  viewer.scene.mode = 0
  viewer.camera.changed.fire()
  viewer.camera.moveEnd.fire()
  assert.equal(readings.length, count)
  viewer.scene.mode = 2
  viewer.scene.morphComplete.fire()
  assert.equal(readings.at(-1).camera.scene_mode, '2d')
  controller.destroy()
})

test('point picking prioritizes terrain, adds a marker and returns WGS84 coordinates once', () => {
  const { controller, picks } = setup()
  const points = []
  viewer.scene.globe.pick = () => ({ longitude: 113.315959, latitude: 23.121995 })
  viewer.camera.pickEllipsoid = () => { throw new Error('terrain should take precedence') }
  controller.beginPointPicking((point) => points.push(point))
  click({ position: new Cartesian2(100, 200) })
  assert.deepEqual(points, [{ longitude: 113.315959, latitude: 23.121995 }])
  assert.equal(viewer.entities.values.length, 1)
  assert.deepEqual(viewer.entities.values[0].position, {
    longitude: 113.315959, latitude: 23.121995, height: 0,
  })
  assert.deepEqual(picks, [null])
  click({ position: new Cartesian2(100, 200) })
  assert.equal(points.length, 1)
  assert.deepEqual(picks, [null, null])
  controller.destroy()
})

test('simulation overlay uses result edges, maps road and cross picks to the formal ID, and cleans old entities', () => {
  const { controller, picks } = setup()
  const network = { nodes: [{ id: 'S', coordinates: [113, 23] }, { id: 'T', coordinates: [114, 23] }],
    edges: [{ id: 'S-T', source: 'S', target: 'T' }] }
  const selected = []
  controller.showSimulation(network, ['S-T'], {
    baseline: { reachable: true, path: ['S', 'T'] }, blocked: { reachable: false, path: [] },
  }, id => selected.push(id))
  const route = viewer.entities.values.find(entity => entity.properties?.simulation_role === 'baseline')
  assert.deepEqual(route.polyline.positions.map(position => [position.longitude, position.latitude]), [[113, 23], [114, 23]])
  const cross = viewer.entities.values.find(entity => entity.properties?.simulation_role === 'blocked_edge')
  assert.equal(cross.label.text, '×')
  viewer.scene.pick = () => ({ id: cross })
  click({ position: new Cartesian2(20, 30) })
  assert.deepEqual(selected, ['S-T'])
  assert.deepEqual(picks, [])
  const previous = [...viewer.entities.values]
  controller.showSimulation(network)
  assert.ok(previous.every(entity => !viewer.entities.values.includes(entity)))
  assert.equal(viewer.entities.values.length, 3)
  controller.showSimulation(null)
  assert.equal(viewer.entities.values.length, 0)
  controller.destroy()
})

test('replay updates two existing map markers and removes them on reset and destroy', () => {
  const { controller, picks } = setup()
  controller.showReplay({ baseline: [113, 23], blocked: [114, 24] })
  assert.equal(viewer.entities.values.length, 2)
  const [baseline, blocked] = viewer.entities.values
  assert.equal(baseline.properties.simulation_role, 'replay_baseline')
  for (let index = 0; index < 100; index++)
    controller.showReplay({ baseline: [113 + index / 100, 23], blocked: [114, 24] })
  assert.equal(viewer.entities.values.length, 2)
  assert.equal(viewer.entities.values[0], baseline)
  assert.deepEqual(baseline.position.getValue(), { longitude: 113.99, latitude: 23, height: 0 })
  viewer.scene.pick = () => ({ id: blocked })
  click({ position: new Cartesian2(20, 30) })
  assert.deepEqual(picks, [], 'a replay marker is not a source object')
  controller.showReplay({ baseline: null, blocked: [114, 24] })
  assert.deepEqual(viewer.entities.values, [blocked])
  controller.destroy()
  assert.equal(viewer.entities.values.length, 0)
})

test('point picking falls back to the ellipsoid and intercepts object selection', () => {
  const { controller, picks } = setup()
  viewer.scene.pick = () => { throw new Error('property picking must be paused') }
  viewer.camera.pickEllipsoid = () => ({ longitude: 114, latitude: 24 })
  let selected
  controller.beginPointPicking((point) => { selected = point })
  click({ position: new Cartesian2(10, 20) })
  assert.deepEqual(selected, { longitude: 114, latitude: 24 })
  assert.deepEqual(picks, [null])
  controller.destroy()
})

test('a sky click keeps point picking active and cancellation restores normal picking', () => {
  const { controller, notices, picks } = setup()
  let count = 0
  controller.beginPointPicking(() => { count++ })
  click({ position: new Cartesian2(10, 20) })
  assert.equal(count, 0)
  assert.match(notices[0], /地面/)
  assert.equal(viewer.entities.values.length, 0)
  viewer.camera.pickEllipsoid = () => ({ longitude: 114, latitude: 24 })
  click({ position: new Cartesian2(10, 20) })
  assert.equal(count, 1)
  assert.equal(viewer.entities.values.length, 1)
  controller.beginPointPicking(() => { count++ })
  assert.equal(viewer.entities.values.length, 0)
  controller.cancelPointPicking()
  const entity = Object.assign(new Noop(), { name: '普通对象' })
  viewer.scene.pick = () => ({ id: entity })
  click({ position: new Cartesian2(10, 20) })
  assert.equal(count, 1)
  assert.equal(picks.at(-1).title, '普通对象')
  controller.destroy()
})

test('point navigation enters 3D with a marker and fixed camera, and region navigation clears it', () => {
  const { controller } = setup()
  viewer.scene.mode = 2
  controller.goToPoint({ longitude: 113, latitude: 23 })
  assert.equal(viewer.scene.mode, 3)
  assert.deepEqual(viewer.lastFlight.sphere.center, { longitude: 113, latitude: 23, height: 0 })
  assert.deepEqual(viewer.lastFlight.options.offset, new HeadingPitchRange(0, -60, 1000))
  assert.equal(viewer.entities.values.length, 1)
  controller.clearPoint()
  assert.equal(viewer.entities.values.length, 0)
  controller.goToPoint({ longitude: 114, latitude: 24 })
  controller.goToRegion({ longitude: 115, latitude: 25, pitch: -90, range: 25000 })
  assert.equal(viewer.entities.values.length, 0)
  controller.destroy()
})

test('destroy cancels point picking and removes its marker', () => {
  const { controller } = setup()
  controller.goToPoint({ longitude: 113, latitude: 23 })
  controller.destroy()
  assert.equal(viewer.entities.values.length, 0)
  controller.beginPointPicking(() => { throw new Error('destroyed controller cannot pick') })
  assert.equal(viewer.entities.values.length, 0)
})

test('ordinary 3D feature picking still reads properties with no bookmark marker', () => {
  const { controller, picks } = setup()
  viewer.scene.pick = () => ({
    getPropertyIds: () => ['name'],
    getProperty: () => '三维楼宇',
  })
  click({ position: new Cartesian2(10, 20) })
  assert.deepEqual(picks, [{
    title: '三维对象', layerName: '3D Tiles', properties: { name: '三维楼宇' },
  }])
  controller.goToPoint({ longitude: 113, latitude: 23 })
  viewer.scene.pick = () => ({ id: viewer.entities.values[0] })
  click({ position: new Cartesian2(10, 20) })
  assert.equal(picks.at(-1), null)
  controller.destroy()
})

test('point markers respect depth instead of rendering through solid buildings', async () => {
  const { controller, layer } = setup()
  const data = new GeoJsonDataSource()
  const entity = { billboard: {} }
  data.entities.values = [entity]
  const loading = controller.load(layer)
  geoRequest.resolve(data)
  await loading
  assert.equal(entity.billboard.disableDepthTestDistance.getValue(), 0)
  assert.equal(entity.billboard.verticalOrigin.getValue(), 1)
  assert.equal(entity.point, undefined)
  layer.opacity = 0.4
  controller.appearance(layer)
  assert.equal(entity.billboard.color.getValue().alpha, 0.4)
  controller.destroy()
})

test('tilt orbits the visible ground target and keeps its distance and heading', () => {
  const { controller } = setup()
  const target = { x: 0, y: 0, z: 0 }
  viewer.scene.globe.pick = (ray) => {
    assert.deepEqual(ray.center, new Cartesian2(400, 300))
    return target
  }
  controller.tilt()
  assert.deepEqual(viewer.lastFlight.sphere.center, target)
  assert.equal(viewer.lastFlight.options.offset.range, 100)
  assert.equal(viewer.lastFlight.options.offset.heading, 0.4)
  assert.equal(viewer.lastFlight.options.offset.pitch, -30)
  assert.equal(viewer.lookedUp, undefined)
  viewer.camera.pitch = -30
  controller.tilt()
  assert.equal(viewer.lastFlight.options.offset.pitch, -65)
  controller.destroy()
})

test('tilt falls back to the ellipsoid; a sky-only center keeps the current camera', () => {
  const { controller, notices } = setup()
  viewer.scene.globe.pick = () => undefined
  const target = { x: 0, y: 0, z: 0 }
  viewer.camera.pickEllipsoid = () => target
  controller.tilt()
  assert.deepEqual(viewer.lastFlight.sphere.center, target)
  viewer.lastFlight = undefined
  viewer.camera.pickEllipsoid = () => undefined
  controller.tilt()
  assert.equal(viewer.lastFlight, undefined)
  assert.equal(notices.length, 1)
  controller.destroy()
})

test('removing a pending GeoJSON prevents late attachment', async () => {
  const { controller, layer } = setup()
  const loading = controller.load(layer)
  controller.remove(layer)
  geoRequest.resolve(new GeoJsonDataSource())
  await loading
  assert.equal(viewer.resources.size, 0)
  assert.equal(layer.status, 'idle')
  controller.destroy()
})

test('removing a white model during terrain sampling prevents late attachment', async () => {
  const { controller, layer } = setup()
  terrainGate = deferred()
  const data = new GeoJsonDataSource()
  data.entities.values = [{ polygon: {}, properties: { map_extrude_height_m: new ConstantProperty(9) } }]
  const loading = controller.load(layer)
  geoRequest.resolve(data)
  await terrainStarted.promise
  controller.remove(layer)
  terrainGate.resolve()
  await loading
  assert.equal(viewer.resources.size, 0)
  assert.equal(layer.status, 'idle')
  controller.destroy()
})

test('terrain sampling failure reports a retryable layer error without attaching a model', async () => {
  const { controller, layer } = setup()
  terrainError = new Error('白模地形采样不完整')
  const data = new GeoJsonDataSource()
  data.entities.values = [{ polygon: {}, properties: { map_extrude_height_m: new ConstantProperty(9) } }]
  const loading = controller.load(layer)
  geoRequest.resolve(data)
  await loading
  assert.equal(layer.status, 'error')
  assert.match(layer.error, /地形采样不完整/)
  assert.equal(viewer.resources.size, 0)
  controller.destroy()
})

test('terrain occludes geometry instead of drawing underground faces on top of imagery', () => {
  const { controller } = setup()
  assert.equal(viewer.scene.globe.depthTestAgainstTerrain, true)
  controller.destroy()
})

test('explicit building height extrudes above terrain while ordinary or invalid polygons stay flat', async () => {
  const { controller, layer } = setup()
  const data = new GeoJsonDataSource()
  const entities = [21, undefined, -3, '30', Infinity, 1001].map((height) => ({
    polygon: {},
    properties: { map_extrude_height_m: new ConstantProperty(height) },
  }))
  data.entities.values = entities
  const loading = controller.load(layer)
  geoRequest.resolve(data)
  await loading
  const building = entities[0].polygon
  assert.equal(building.height.getValue(), 33)
  assert.equal(building.extrudedHeight.getValue(), -8.1)
  assert.equal(building.heightReference.getValue(), 0)
  assert.equal(building.extrudedHeightReference.getValue(), 0)
  assert.equal(building.closeTop.getValue(), true)
  assert.equal(building.closeBottom.getValue(), true)
  assert.equal(building.perPositionHeight.getValue(), false)
  for (const entity of entities.slice(1))
    assert.equal(entity.polygon.extrudedHeight, undefined)
  layer.opacity = 0.4
  layer.visible = false
  controller.appearance(layer)
  assert.equal(data.show, false)
  assert.equal(building.height.getValue(), 33)
  assert.equal(building.extrudedHeight.getValue(), -8.1)
  assert.equal(building.material.color.alpha, 0.4)
  assert.equal(entities[1].polygon.material.color.alpha, 0.4 * 0.36)
  controller.destroy()
})

test('removing during asynchronous collection insertion removes the late resource', async () => {
  const { controller, layer } = setup()
  addGate = deferred()
  const loading = controller.load(layer)
  geoRequest.resolve(new GeoJsonDataSource())
  await Promise.resolve()
  controller.remove(layer)
  addGate.resolve()
  await loading
  assert.equal(viewer.resources.size, 0)
  assert.equal(layer.attached, false)
  controller.destroy()
})

test('reloading discards an older tileset result and destroys it', async () => {
  const { controller, layer } = setup('3dtiles')
  const oldRequest = tileRequest
  const oldLoad = controller.load(layer)
  tileRequest = deferred()
  const newLoad = controller.load(layer)
  const oldTile = new Cesium3DTileset()
  const newTile = new Cesium3DTileset()
  oldRequest.resolve(oldTile)
  tileRequest.resolve(newTile)
  await Promise.all([oldLoad, newLoad])
  assert.equal(oldTile.destroyed, true)
  assert.deepEqual([...viewer.resources], [newTile])
  newTile.initialTilesLoaded.fire()
  assert.equal(layer.status, 'ready')
  controller.destroy()
})

test('destroying the map discards pending loads without adding to a dead viewer', async () => {
  const { controller, layer } = setup('3dtiles')
  const loading = controller.load(layer)
  controller.destroy()
  const tile = new Cesium3DTileset()
  tileRequest.resolve(tile)
  await loading
  assert.equal(tile.destroyed, true)
  assert.equal(viewer.resources.size, 0)
})

test('region navigation uses the selected target and preserves loaded layers', async () => {
  const { controller, layer } = setup()
  const loading = controller.load(layer)
  geoRequest.resolve(new GeoJsonDataSource())
  await loading
  controller.goToRegion({
    id: '440106',
    label: '广东省 · 广州市 · 天河区',
    longitude: 113.33,
    latitude: 23.14,
    range: 25000,
    pitch: -90,
  })
  assert.equal(viewer.lastFlight.sphere.center.longitude, 113.33)
  assert.equal(viewer.lastFlight.sphere.center.latitude, 23.14)
  assert.equal(viewer.lastFlight.options.offset.range, 25000)
  assert.equal(layer.status, 'ready')
  assert.equal(viewer.resources.size, 1)
  controller.destroy()
})

const boundaryData = (id) => ({
  type: 'FeatureCollection',
  features: [
    {
      properties: { adcode: id },
      geometry: {
        type: 'Polygon',
        coordinates: [
          [
            [113, 23],
            [114, 23],
            [114, 24],
            [113, 23],
          ],
        ],
      },
    },
  ],
})
const response = (id) => ({ ok: true, json: async () => boundaryData(id) })
const flush = () => new Promise(setImmediate)

test('switching regions aborts and discards old boundaries while preserving user layers', async (t) => {
  const states = []
  const { controller, layer } = setup('geojson', (state) =>
    states.push(state.status),
  )
  const userLayer = new GeoJsonDataSource()
  const loading = controller.load(layer)
  geoRequest.resolve(userLayer)
  await loading
  geoRequest = deferred()
  const oldFetch = deferred()
  let oldSignal
  t.mock.method(globalThis, 'fetch', (url, { signal }) => {
    if (url.includes('440000')) {
      oldSignal = signal
      return oldFetch.promise
    }
    return Promise.resolve(response('440106'))
  })
  const old = controller.setRegionBoundary('440000')
  const latest = controller.setRegionBoundary('440106')
  await flush()
  const boundary = new GeoJsonDataSource()
  geoRequest.resolve(boundary)
  await latest
  oldFetch.resolve(response('440000'))
  await old
  assert.equal(oldSignal.aborted, true)
  assert.deepEqual([...viewer.resources], [userLayer, boundary])
  assert.deepEqual(states, ['loading', 'loading', 'ready'])
  await controller.setRegionBoundary('demo')
  assert.deepEqual([...viewer.resources], [userLayer])
  assert.equal(states.at(-1), 'idle')
  controller.destroy()
})

test('hiding the boundary during collection insertion removes the late resource', async (t) => {
  const states = []
  const { controller } = setup('geojson', (state) => states.push(state.status))
  t.mock.method(globalThis, 'fetch', async () => response('440106'))
  addGate = deferred()
  const loading = controller.setRegionBoundary('440106')
  await flush()
  geoRequest.resolve(new GeoJsonDataSource())
  await flush()
  await controller.setRegionBoundary(null)
  addGate.resolve()
  await loading
  assert.equal(viewer.resources.size, 0)
  assert.deepEqual(states, ['loading', 'idle'])
  controller.destroy()
})

test('boundary failures clear old outlines, report an error and allow retry', async (t) => {
  const states = []
  const { controller } = setup('geojson', (state) => states.push(state))
  const fetchMock = t.mock.method(globalThis, 'fetch', async () =>
    response('440106'),
  )
  geoRequest.resolve(new GeoJsonDataSource())
  await controller.setRegionBoundary('440106')
  assert.equal(viewer.resources.size, 1)
  fetchMock.mock.mockImplementation(async () => ({ ok: false, status: 503 }))
  await controller.setRegionBoundary('440100')
  assert.equal(viewer.resources.size, 0)
  assert.equal(states.at(-1).status, 'error')
  assert.match(states.at(-1).error, /503/)
  fetchMock.mock.mockImplementation(async () => response('440100'))
  geoRequest = deferred()
  geoRequest.resolve(new GeoJsonDataSource())
  await controller.setRegionBoundary('440100')
  assert.equal(viewer.resources.size, 1)
  assert.equal(states.at(-1).status, 'ready')
  controller.destroy()
})

test('destroying the map aborts boundary loading and prevents late updates', async (t) => {
  const states = []
  const { controller } = setup('geojson', (state) => states.push(state.status))
  t.mock.method(globalThis, 'fetch', async () => response('440106'))
  const loading = controller.setRegionBoundary('440106')
  await flush()
  controller.destroy()
  geoRequest.resolve(new GeoJsonDataSource())
  await loading
  assert.equal(viewer.resources.size, 0)
  assert.deepEqual(states, ['loading'])
})

test('region selection frames the boundary extent, while toggling keeps the camera unchanged', async (t) => {
  const { controller } = setup()
  t.mock.method(globalThis, 'fetch', async () => response('440106'))
  const boundary = new GeoJsonDataSource()
  geoRequest.resolve(boundary)
  await controller.setRegionBoundary('440106', true)
  assert.equal(viewer.lastResourceFlight.resource, boundary)
  assert.equal(viewer.lastResourceFlight.options.offset.range, 0)
  assert.equal(viewer.lastResourceFlight.options.offset.pitch, -90)
  viewer.lastResourceFlight = undefined
  await controller.setRegionBoundary(null)
  geoRequest = deferred()
  geoRequest.resolve(new GeoJsonDataSource())
  await controller.setRegionBoundary('440106')
  assert.equal(viewer.lastResourceFlight, undefined)
  controller.destroy()
})

test('campus sample targets clear administrative outlines without requesting campus boundaries', async (t) => {
  const states = []
  const { controller } = setup('geojson', (state) => states.push(state.status))
  const fetching = t.mock.method(globalThis, 'fetch', async () => {
    throw new Error('No administrative campus boundary should be requested')
  })
  await controller.setRegionBoundary('demo-university-town')
  await controller.setRegionBoundary('demo-huangpu')
  assert.equal(fetching.mock.callCount(), 0)
  assert.deepEqual(states, ['idle', 'idle'])
  controller.destroy()
})

test('asset version loading uses the pinned entry and leaves unavailable versions traceable', async (t) => {
  const { controller, layer } = setup()
  Object.assign(layer, { asset_id: 'asset-one', asset_version: '1.0.0', url: '/stale' })
  const requests = []
  t.mock.method(globalThis, 'fetch', async url => {
    requests.push(url)
    return new Response(JSON.stringify(String(url).includes('/versions/')
      ? { status: 'ready', entry_url: '/pinned.geojson' }
      : { type: 'FeatureCollection', features: [] }))
  })
  geoRequest.resolve(new GeoJsonDataSource())
  await controller.load(layer)
  assert.deepEqual(requests, ['/api/assets/asset-one/versions/1.0.0', '/pinned.geojson'])
  assert.equal(geoSource.type, 'FeatureCollection')
  assert.equal(layer.progress, 100)
  t.mock.method(globalThis, 'fetch', async () => new Response(JSON.stringify({ code: 'ASSET_VERSION_NOT_FOUND', message: '版本不存在', trace_id: 'version-trace' }), { status: 404 }))
  await controller.load(layer)
  assert.equal(layer.status, 'error')
  assert.equal(layer.traceId, 'version-trace')
  assert.match(layer.error, /ASSET_VERSION_NOT_FOUND/)
  controller.destroy()
})

test('tiles report pending work and complete only after visible content; late events cannot resurrect removed layers', async () => {
  const { controller, layer } = setup('3dtiles')
  const resource = new Cesium3DTileset()
  tileRequest.resolve(resource)
  await controller.load(layer)
  assert.equal(tileSource, '/test')
  assert.equal(layer.status, 'loading')
  resource.loadProgress.fire(4, 2)
  assert.match(layer.loadPhase, /4.*2/)
  assert.equal(layer.progress, null)
  resource.initialTilesLoaded.fire()
  assert.equal(layer.status, 'ready')
  controller.remove(layer)
  resource.loadProgress.fire(1, 1)
  resource.initialTilesLoaded.fire()
  assert.equal(layer.status, 'idle')
  assert.equal(resource.destroyed, true)
  controller.destroy()
})

test('camera restore preserves 2D mode and north reset preserves position and pitch', () => {
  const readings = []
  const { controller } = setup('geojson', () => {}, (value, settled) => readings.push({ ...value, settled }))
  const camera = { longitude: 114, latitude: 22, height: 1500, heading: 0.6, pitch: -0.7, roll: 0.1, scene_mode: '2d' }
  assert.equal(controller.setCamera(camera), true)
  assert.equal(viewer.scene.mode, 2)
  assert.deepEqual(controller.getCamera(), camera)
  controller.north()
  assert.equal(viewer.lastView.orientation.heading, 0)
  assert.equal(viewer.lastView.orientation.pitch, camera.pitch)
  assert.equal(readings.at(-1).settled, true)
  assert.deepEqual(viewer.lastView.destination, { longitude: 114, latitude: 22, height: 1500 })
  assert.equal(controller.setCamera({ ...camera, latitude: 200 }), false)
  controller.destroy()
})

test('pointer readings prefer visible depth, use measured ground scale and clear over sky', () => {
  const readings = []
  const { controller } = setup('geojson', () => {}, value => readings.push(value))
  viewer.scene.pickPositionSupported = true
  viewer.scene.pickPosition = () => ({ longitude: 113.4, latitude: 23.2, height: 28 })
  viewer.scene.globe.pick = () => ({ longitude: 113.4, latitude: 23.2, height: 0 })
  move({ endPosition: new Cartesian2(100, 100) })
  assert.deepEqual(readings.at(-1).pointer, { longitude: 113.4, latitude: 23.2, height: 28 })
  assert.equal(readings.at(-1).scale.label, '200 m')
  viewer.scene.pickPosition = () => undefined
  viewer.scene.globe.pick = () => undefined
  move({ endPosition: new Cartesian2(100, 100) })
  assert.equal(readings.at(-1).pointer, null)
  assert.equal(readings.at(-1).scale, null)
  controller.destroy()
})

test('restored camera is not overwritten by a late asset and flight completion publishes settled state', async () => {
  const readings = []
  const { controller, layer } = setup('3dtiles', () => {}, (_state, settled) => readings.push(settled))
  Object.assign(layer, { id: 'campus-buildings', builtin: true, campus: 'university-town' })
  controller.initialize({ id: 'demo-university-town', sampleKey: 'university-town', longitude: 113, latitude: 23, pitch: -52, range: 2300 },
    { longitude: 114, latitude: 22, height: 1500, heading: 0.6, pitch: -0.7, roll: 0.1, scene_mode: '3d' })
  const resource = new Cesium3DTileset()
  tileRequest.resolve(resource)
  await controller.load(layer)
  assert.equal(viewer.lastFlight, undefined)
  controller.home()
  assert.equal(viewer.lastFlight.sphere, resource.boundingSphere)
  controller.goToRegion({ longitude: 113, latitude: 23, pitch: -52, range: 2300 })
  viewer.lastFlight.options.complete()
  assert.equal(readings.at(-1), true)
  controller.destroy()
})

test('2D ordering changes ground zIndex and source draw order while preserving 3D depth', async () => {
  const { controller, layer } = setup()
  Object.assign(layer, { order: 4, orderable: true })
  const source = new GeoJsonDataSource()
  source.entities.values = [{ polygon: {}, polyline: {} }]
  geoRequest.resolve(source)
  await controller.load(layer)
  assert.equal(source.entities.values[0].polygon.zIndex.getValue(), -4)
  assert.equal(source.entities.values[0].polyline.zIndex.getValue(), -4)
  assert.equal(viewer.raisedSources.at(-1), source)
  layer.order = 1
  controller.syncOrder([layer])
  assert.equal(source.entities.values[0].polygon.zIndex.getValue(), -1)
  source.entities.values[0].polygon.perPositionHeight = new ConstantProperty(true)
  layer.order = 0
  controller.syncOrder([layer])
  assert.equal(source.entities.values[0].polygon.zIndex.getValue(), -1, 'XYZ surface keeps its 3D depth')
  assert.equal(viewer.scene.globe.depthTestAgainstTerrain, true)
  layer.orderable = false
  const before = viewer.raisedSources.length
  controller.syncOrder([layer])
  assert.equal(viewer.raisedSources.length, before)
  controller.destroy()
})

test('polygon selection collects a closed ground footprint and restores camera controls', () => {
  const { controller } = setup()
  viewer.scene.globe.pick = ray => ({ longitude: 113 + ray.center.x / 1000, latitude: 23 + ray.center.y / 1000 })
  viewer.scene.pick = () => { throw new Error('normal picking must pause while drawing') }
  const results = []
  controller.beginAreaSelection('polygon', geometry => results.push(geometry))
  assert.equal(viewer.scene.screenSpaceCameraController.enableInputs, false)
  click({ position: new Cartesian2(10, 10) })
  click({ position: new Cartesian2(20, 10) })
  assert.equal(controller.finishAreaSelection(), false)
  click({ position: new Cartesian2(20, 20) })
  assert.equal(controller.finishAreaSelection(), true)
  assert.deepEqual(results, [{ type: 'Polygon', coordinates: [[[113.01, 23.01], [113.02, 23.01], [113.02, 23.02], [113.01, 23.01]]] }])
  assert.equal(viewer.scene.screenSpaceCameraController.enableInputs, true)
  assert.equal(viewer.entities.values.length, 0)
  controller.destroy()
})

test('drawing gestures use a separate surface so the camera never receives the drag', () => {
  const { controller } = setup()
  controller.beginAreaSelection('box', () => {})
  const drawingHandler = viewer.handlers.at(-1)
  assert.notEqual(drawingHandler.target, viewer.scene.canvas)
  assert.equal(drawingHandler.target.style.touchAction, 'none')
  controller.cancelAreaSelection()
  assert.equal(drawingHandler.destroyed, true)
  assert.equal(drawingHandler.target.removed, true)
  assert.equal(viewer.scene.screenSpaceCameraController.enableInputs, true)
  controller.destroy()
})

test('box selection uses all four screen corners; cancellation and sky keep results empty', () => {
  const { controller } = setup()
  viewer.scene.globe.pick = ray => ({ longitude: 113 + ray.center.x / 1000, latitude: 23 + ray.center.y / 1000 })
  const results = []
  controller.beginAreaSelection('box', geometry => results.push(geometry))
  down({ position: new Cartesian2(10, 10) })
  move({ endPosition: new Cartesian2(30, 20) })
  up({ position: new Cartesian2(30, 20) })
  assert.deepEqual(results[0].coordinates[0], [[113.01, 23.01], [113.03, 23.01], [113.03, 23.02], [113.01, 23.02], [113.01, 23.01]])
  controller.beginAreaSelection('polygon', geometry => results.push(geometry))
  viewer.scene.globe.pick = () => undefined
  click({ position: new Cartesian2(10, 10) })
  assert.equal(controller.finishAreaSelection(), false)
  controller.cancelAreaSelection()
  assert.equal(results.length, 1)
  assert.equal(viewer.scene.screenSpaceCameraController.enableInputs, true)
  controller.destroy()
})

test('multipart features share backend ID, highlight all parts and restore current opacity', async (t) => {
  const { controller, layer, picks } = setup()
  const objectId = '2f3982d2-41e0-519a-ad92-23346a334ed2'
  Object.assign(layer, { id: 'layer-one', name: '多部件', source: '', asset_id: 'asset-one', asset_version: '1.0.0', object_count: 1 })
  const data = { type: 'FeatureCollection', features: [{ type: 'Feature', id: 'native', properties: { name: '原始对象' }, geometry: { type: 'MultiPolygon', coordinates: [] } }] }
  t.mock.method(globalThis, 'fetch', async url => new Response(JSON.stringify(String(url).includes('/versions/') ? { status: 'ready', entry_url: '/pinned' } : data)))
  const source = new GeoJsonDataSource()
  const parts = [objectId, `${objectId}_2`].map(id => Object.assign(new Noop(), { id, polygon: {}, properties: { getValue: () => ({ name: '原始对象' }) } }))
  source.entities.values = parts
  source.entities.contains = entity => parts.includes(entity)
  geoRequest.resolve(source)
  await controller.load(layer)
  const originalMaterials = parts.map(part => part.polygon.material)
  assert.equal(geoSource.features[0].id, objectId)
  assert.equal(data.features[0].id, 'native')
  viewer.scene.pick = () => ({ id: parts[1] })
  click({ position: new Cartesian2(10, 10) })
  assert.equal(picks.at(-1).objectId, objectId)
  assert.equal(picks.at(-1).layerId, 'layer-one')
  assert.equal(controller.objectPage(objectId, 'layer-one', 20), 1)
  assert.notEqual(parts[0].polygon.material, originalMaterials[0])
  assert.notEqual(parts[1].polygon.material, originalMaterials[1])
  layer.opacity = 0.4
  controller.appearance(layer)
  controller.highlightObjects(null, [])
  assert.equal(parts[0].polygon.material.color.alpha, 0.4 * 0.36)
  controller.highlightObjects(layer.id, [objectId], objectId)
  await controller.focusObject('layer-one', { object_id: objectId, type: 'area', geometry: { type: 'MultiPolygon', coordinates: [] } })
  assert.deepEqual(viewer.lastResourceFlight.resource, parts)
  controller.remove(layer)
  assert.equal(picks.at(-1), null)
  controller.destroy()
})

test('semantic-free 3D picking links to the model resource without inventing building properties', async (t) => {
  const { controller, layer, picks } = setup('3dtiles')
  Object.assign(layer, { id: 'model-layer', name: '几何模型', asset_id: 'asset-one', asset_version: '1.0.0', object_count: 1 })
  t.mock.method(globalThis, 'fetch', async () => new Response('{"status":"ready","entry_url":"/model/tileset.json"}'))
  await controller.load({ id: 'basemap', visible: true, opacity: 1 })
  const resource = new Cesium3DTileset()
  tileRequest.resolve(resource)
  await controller.load(layer)
  const previous = resource.style
  viewer.scene.pick = () => ({ content: { tileset: resource }, getPropertyIds: () => [] })
  click({ position: new Cartesian2(10, 10) })
  assert.equal(picks.at(-1).objectId, '0bdeee8a-0109-5520-8e8c-2e0d09a945d8')
  assert.deepEqual(picks.at(-1).properties, {})
  assert.equal(picks.at(-1).resourceType, '3dtiles')
  assert.notEqual(resource.style, previous)
  controller.highlightObjects(null, [])
  assert.equal(resource.style, previous)
  controller.destroy()
})

test('unindexed tile highlighting restores its original color before tile content unloads', async () => {
  const { controller, layer, picks } = setup('3dtiles')
  Object.assign(layer, { id: 'external-model', object_count: null })
  const resource = new Cesium3DTileset()
  tileRequest.resolve(resource)
  await controller.load(layer)
  const original = { original: true }
  const feature = { tileset: resource, color: original, getPropertyIds: () => [] }
  viewer.scene.pick = () => feature
  click({ position: new Cartesian2(10, 10) })
  assert.notEqual(feature.color, original)
  resource.tileUnload.fire()
  assert.equal(feature.color, original)
  assert.equal(picks.at(-1), null)
  controller.destroy()
})
