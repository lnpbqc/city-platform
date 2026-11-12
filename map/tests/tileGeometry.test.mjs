import { test } from 'node:test'
import assert from 'node:assert/strict'
import { tileBounds, viewTiles, mergeParts, vertexCount, clipPolygon } from '../src/tileGeometry.ts'

test('antimeridian views cover both edge columns without spanning the intervening world', () => {
  const tiles = viewTiles([170, -10, -170, 10], 3)
  assert.deepEqual(tiles, [[3, 7, 3], [3, 7, 4], [3, 0, 3], [3, 0, 4]])
  assert.equal(new Set(tiles.map(tile => tile.join('/'))).size, tiles.length)
  assert.deepEqual(viewTiles([170, -10, -170, 10], 0), [[0, 0, 0]])
})

test('a clipped hole touching the viewport edge becomes a notch', () => {
  const source = { type: 'Polygon', coordinates: [
    [[-2,-2],[2,-2],[2,2],[-2,2],[-2,-2]],
    [[-1,-1],[-1,1],[1,1],[1,-1],[-1,-1]],
  ] }
  const result = clipPolygon(source, [0,-2,2,2])
  assert.equal(result.type, 'Polygon')
  assert.equal(result.coordinates.length, 1)
  assert.equal(source.coordinates.length, 2)
  const ring = result.coordinates[0]
  const area = Math.abs(ring.slice(1).reduce((sum, point, index) =>
    sum + ring[index][0] * point[1] - point[0] * ring[index][1], 0)) / 2
  assert.equal(area, 6)
})

test('clipping a concave polygon preserves disconnected pieces', () => {
  const source = { type: 'Polygon', coordinates: [
    [[-3,-3],[3,-3],[3,3],[1,3],[1,-1],[-1,-1],[-1,3],[-3,3],[-3,-3]],
  ] }
  const result = clipPolygon(source, [-3,0,3,3])
  assert.equal(result.type, 'MultiPolygon')
  assert.equal(result.coordinates.length, 2)
})

test('polar viewport limits clamp to valid Mercator rows with finite bounds', () => {
  assert.deepEqual(viewTiles([-170, -90, -160, -86], 4), [[4, 0, 15]])
  assert.deepEqual(viewTiles([-170, 86, -160, 90], 4), [[4, 0, 0]])
  const south = tileBounds(4, 0, 15)
  assert.ok(south.every(Number.isFinite))
  assert.ok(Math.abs(south[1] + 85.0511287798066) < 1e-10)
  assert.ok(south[1] < south[3])
})

test('a complete view accepts exactly 64 tiles and rejects larger sets', () => {
  const complete = viewTiles([-180, -90, 180, 90], 3)
  assert.equal(complete.length, 64)
  assert.deepEqual(complete[0], [3, 0, 0])
  assert.deepEqual(complete.at(-1), [3, 7, 7])
  assert.equal(viewTiles([-180, -90, 180, 90], 4), null)
})

test('cross-tile line pieces keep all segments and source coordinates', () => {
  const first = { type: 'LineString', coordinates: [[0, 0], [1, 0]] }
  const second = { type: 'MultiLineString', coordinates: [[[1, 0], [2, 0]], [[2, 0], [3, 1]]] }
  const original = structuredClone([first, second])
  const merged = mergeParts([first, second])
  assert.deepEqual(merged, { type: 'MultiLineString', coordinates: [first.coordinates, ...second.coordinates] })
  assert.equal(vertexCount(merged), 6)
  assert.deepEqual([first, second], original)
})

test('polygon merging preserves independent parts and interior rings', () => {
  const outer = [[0, 0], [3, 0], [3, 3], [0, 0]]
  const hole = [[1, 1], [2, 1], [1, 2], [1, 1]]
  const other = [[3, 0], [4, 0], [4, 3], [3, 0]]
  const merged = mergeParts([{ type: 'Polygon', coordinates: [outer, hole] }, { type: 'MultiPolygon', coordinates: [[other]] }])
  assert.deepEqual(merged, { type: 'MultiPolygon', coordinates: [[outer, hole], [other]] })
  assert.equal(vertexCount(merged), 12)
  const mixed = mergeParts([merged, { type: 'Point', coordinates: [5, 5] }])
  assert.equal(mixed.type, 'GeometryCollection')
  assert.equal(vertexCount(mixed), 13)
})
