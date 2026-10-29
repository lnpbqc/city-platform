import { test } from 'node:test'
import assert from 'node:assert/strict'
import { readMapView, saveMapView, scaleForDistance } from '../src/mapNavigation.ts'

const camera = { longitude: 113.4, latitude: 23.1, height: 850, heading: 0.8, pitch: -0.9, roll: 0, scene_mode: '2d' }
const region = { id: 'demo-university-town', sampleKey: 'university-town', label: '大学城', longitude: 113.4, latitude: 23.1, range: 2000, pitch: -52 }

test('camera and selected campus round-trip with mode and full orientation', () => {
  const values = new Map()
  const storage = { getItem: (key) => values.get(key), setItem: (key, value) => values.set(key, value) }
  assert.equal(saveMapView(storage, { camera, region }), true)
  assert.deepEqual(readMapView(storage), { camera, region })
})

for (const value of [null, '{}', 'invalid JSON', JSON.stringify({ camera: { ...camera, latitude: 91 }, region }),
  JSON.stringify({ camera: { ...camera, heading: null }, region }), JSON.stringify({ camera, region: { ...region, range: -1 } })]) {
  test(`invalid or stale stored view falls back safely: ${value}`, () => {
    assert.equal(readMapView({ getItem: () => value }), null)
  })
}

test('blocked browser storage does not interrupt navigation', () => {
  const storage = { getItem() { throw new Error('disabled') }, setItem() { throw new Error('quota') } }
  assert.equal(readMapView(storage), null)
  assert.equal(saveMapView(storage, { camera, region }), false)
})

test('scale uses measured ground distance with readable length and proportional width', () => {
  assert.deepEqual(scaleForDistance(350), { label: '200 m', pixels: 200 / 350 * 100 })
  assert.deepEqual(scaleForDistance(2600), { label: '2 km', pixels: 2000 / 2600 * 100 })
  assert.deepEqual(scaleForDistance(0.7), { label: '0.5 m', pixels: 0.5 / 0.7 * 100 })
  assert.equal(scaleForDistance(0), null)
  assert.equal(scaleForDistance(Number.NaN), null)
})
