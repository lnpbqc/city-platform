import { mock, test } from 'node:test'
import assert from 'node:assert/strict'
const cesium = await import('cesium')
let requested = []
let heightAt = () => 0
mock.module('cesium', {
  exports: {
    ...cesium,
    sampleTerrainMostDetailed: async (_terrain, positions) => {
      requested = positions
      for (const position of positions) position.height = heightAt(position)
      return positions
    },
  },
})
const { sampleBuildingTerrain } = await import('../src/buildingTerrain.ts')
const polygon = (hole = false) =>
  new cesium.PolygonGraphics({
    hierarchy: new cesium.PolygonHierarchy(
      cesium.Cartesian3.fromDegreesArray([
        113, 23, 113.002, 23, 113.002, 23.002, 113, 23.002, 113, 23,
      ]),
      hole
        ? [
            new cesium.PolygonHierarchy(
              cesium.Cartesian3.fromDegreesArray([
                113.0005, 23.0005, 113.0015, 23.0005, 113.0015, 23.0015,
                113.0005, 23.0015, 113.0005, 23.0005,
              ]),
            ),
          ]
        : [],
    ),
  })

test('bounds include an interior high point, not just the center or boundary', async () => {
  heightAt = (point) => {
    const longitude = cesium.Math.toDegrees(point.longitude)
    const latitude = cesium.Math.toDegrees(point.latitude)
    return longitude > 113.0006 &&
      longitude < 113.0014 &&
      latitude > 23.0006 &&
      latitude < 23.0014
      ? 12
      : -8
  }
  const bounds = await sampleBuildingTerrain(
    [polygon()],
    {},
    cesium.JulianDate.now(),
  )
  assert.deepEqual(bounds, [{ minimum: -8, maximum: 12 }])
  assert.ok(requested.length > 5)
})

test('courtyard interiors are excluded from ground sampling', async () => {
  const bounds = await sampleBuildingTerrain(
    [polygon(true)],
    {},
    cesium.JulianDate.now(),
  )
  assert.deepEqual(bounds, [{ minimum: -8, maximum: -8 }])
})

test('ellipsoid fallback has a zero base; missing sampled heights fail explicitly', async () => {
  assert.deepEqual(
    await sampleBuildingTerrain(
      [polygon()],
      new cesium.EllipsoidTerrainProvider(),
      cesium.JulianDate.now(),
    ),
    [{ minimum: 0, maximum: 0 }],
  )
  heightAt = () => undefined
  await assert.rejects(
    sampleBuildingTerrain([polygon()], {}, cesium.JulianDate.now()),
    /采样不完整/,
  )
})
