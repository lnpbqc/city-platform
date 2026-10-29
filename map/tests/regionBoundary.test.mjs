import { test } from 'node:test'
import assert from 'node:assert/strict'
import { boundaryLines, fetchRegionBoundary } from '../src/regionBoundary.ts'

const ring = [
  [113.33, 23.14],
  [113.34, 23.14],
  [113.34, 23.15],
  [113.33, 23.14],
]
const data = (type, coordinates, id = '440106') => ({
  type: 'FeatureCollection',
  features: [
    {
      type: 'Feature',
      properties: { adcode: id },
      geometry: { type, coordinates },
    },
  ],
})

test('boundary rings preserve multipolygons, islands and holes without modifying source coordinates', () => {
  const input = data('MultiPolygon', [[ring, ring], [ring]])
  const before = structuredClone(input)
  const result = boundaryLines(input, '440106')
  assert.equal(result.features.length, 3)
  assert.ok(
    result.features.every((feature) => feature.geometry.type === 'LineString'),
  )
  const converted = result.features[0].geometry.coordinates
  assert.ok(Math.abs(converted[0][0] - ring[0][0]) > 0.001)
  assert.deepEqual(converted[0], converted.at(-1))
  assert.deepEqual(input, before)
})

test('Polygon is supported and Taiwan coordinates follow the unshifted directory convention', () => {
  const result = boundaryLines(data('Polygon', [ring], '710000'), '710000')
  assert.deepEqual(result.features[0].geometry.coordinates, ring)
})

test('invalid collections, wrong region, unsupported geometry and broken rings are rejected', () => {
  for (const input of [
    null,
    {},
    { type: 'FeatureCollection', features: [] },
    data('Polygon', [ring], '440100'),
    data('Point', ring),
    data('Polygon', []),
    data('Polygon', [[[113, 23]]]),
    data('Polygon', [[[999, 23], ...ring.slice(1)]]),
    data('Polygon', [[...ring.slice(0, 3), [114, 24]]]),
  ])
    assert.throws(() => boundaryLines(input, '440106'))
})

test('boundary requests use the selected administrative code, allow cancellation, and report service errors', async (t) => {
  const abort = new AbortController()
  t.mock.method(globalThis, 'fetch', async (url, options) => {
    assert.equal(url, 'https://geo.datav.aliyun.com/areas_v3/bound/440106.json')
    assert.equal(options.signal, abort.signal)
    return { ok: false, status: 404 }
  })
  await assert.rejects(
    fetchRegionBoundary('../invalid', abort.signal),
    /行政区代码无效/,
  )
  await assert.rejects(fetchRegionBoundary('440106', abort.signal), /HTTP 404/)
})
