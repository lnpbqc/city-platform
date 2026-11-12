import { test, mock } from 'node:test'
import assert from 'node:assert/strict'

let features = [], requested = []
mock.module('pmtiles', { namedExports: {
  FetchSource: class { constructor(url) { this.url = url } getKey() { return this.url } },
  PMTiles: class {
    async getHeader() { return { minZoom: 0, maxZoom: 16 } }
    async getZxy(z) { requested.push(z); return { data: new Uint8Array() } }
  },
} })
mock.module('pbf', { namedExports: { PbfReader: class {} } })
mock.module('@mapbox/vector-tile', { namedExports: { VectorTile: class {
  layers = { data: { length: features.length, feature: index => ({
    properties: { object_id: 'original', feature_index: 0, road_rank: 0 },
    toGeoJSON: () => structuredClone(features[index]),
  }) } }
} } })

globalThis.self = { postMessage() {} }
await import('../src/tileViewport.worker.ts')
const receive = self.onmessage
delete globalThis.self

async function load(t, render, view, data = []) {
  features = data; requested = []
  const previous = globalThis.self
  let response
  globalThis.self = { postMessage: value => { response = value } }
  t.after(() => { if (previous === undefined) delete globalThis.self; else globalThis.self = previous })
  await receive({ data: { id: 1, render: { status: 'succeeded', url: `/${t.name}`, ...render },
    view: { asset_id: 'asset', version: '1', road_max_level: 2, ...view } } })
  return response
}

test('roads exceeding the tile budget fail over instead of reading coarse geometry', async t => {
  const response = await load(t, { profile: 'roads', contains_roads: true },
    { bbox: [113,23,114,24], meters_per_pixel: 2 })
  assert.ok(response.error, 'a wide road view must use the faithful viewport fallback')
  assert.deepEqual(requested, [])
})

test('mixed road layers also refuse coarse fallback', async t => {
  const response = await load(t, { profile: 'generic', contains_roads: true },
    { bbox: [113,23,114,24], meters_per_pixel: 2 })
  assert.ok(response.error)
  assert.deepEqual(requested, [])
})

test('road vertex overflow never retries a lower zoom', async t => {
  const coordinates = Array.from({ length: 100001 }, (_, i) => [113.0012 + (i % 2) * .0001, 23.0012])
  const response = await load(t, { profile: 'roads', contains_roads: true },
    { bbox: [113.001,23.001,113.002,23.002], meters_per_pixel: 10 },
    [{ type: 'Feature', properties: {}, geometry: { type: 'LineString', coordinates } }])
  assert.ok(response.error)
  assert.equal(requested.length, 1, 'retain current precision and ask the server to select whole roads')
})

test('pure polygon layers retain the existing budget coarsening path', async t => {
  const response = await load(t, { profile: 'generic', contains_roads: false },
    { bbox: [113,23,114,24], meters_per_pixel: 2 })
  assert.equal(response.error, undefined)
  assert.equal(response.data.truncated, true)
  assert.ok(requested.length > 0)
})
