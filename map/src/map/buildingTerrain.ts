import {
  Cartographic,
  EllipsoidTerrainProvider,
  sampleTerrainMostDetailed,
} from 'cesium'
import type {
  JulianDate,
  PolygonGraphics,
  PolygonHierarchy,
  TerrainProvider,
} from 'cesium'

type Ring = { points: Cartographic[]; holes: Ring[] }
export type TerrainBounds = { minimum: number; maximum: number }

function toRing(hierarchy: PolygonHierarchy): Ring {
  return {
    points: hierarchy.positions.map((position) =>
      Cartographic.fromCartesian(position),
    ),
    holes: (hierarchy.holes ?? []).map(toRing),
  }
}

function contains(ring: Ring, longitude: number, latitude: number): boolean {
  let inside = false
  const points = ring.points
  for (let i = 0, j = points.length - 1; i < points.length; j = i++) {
    const a = points[i]!,
      b = points[j]!
    if (
      a.latitude > latitude !== b.latitude > latitude &&
      longitude <
        ((b.longitude - a.longitude) * (latitude - a.latitude)) /
          (b.latitude - a.latitude) +
          a.longitude
    )
      inside = !inside
  }
  return (
    inside && !ring.holes.some((hole) => contains(hole, longitude, latitude))
  )
}

function samplePositions(ring: Ring): Cartographic[] {
  const positions: Cartographic[] = []
  const append = (part: Ring) => {
    positions.push(...part.points)
    part.holes.forEach(append)
  }
  append(ring)
  const west = Math.min(...ring.points.map((p) => p.longitude))
  const east = Math.max(...ring.points.map((p) => p.longitude))
  const south = Math.min(...ring.points.map((p) => p.latitude))
  const north = Math.max(...ring.points.map((p) => p.latitude))
  let columns = Math.max(
    1,
    Math.ceil(((east - west) * 6378137 * Math.cos((south + north) / 2)) / 20),
  )
  let rows = Math.max(1, Math.ceil(((north - south) * 6378137) / 20))
  // Keep large user polygons bounded; campus buildings normally use the 20m grid.
  const scale = Math.max(1, Math.sqrt((columns * rows) / 1024))
  columns = Math.ceil(columns / scale)
  rows = Math.ceil(rows / scale)
  for (let row = 0; row < rows; row++)
    for (let column = 0; column < columns; column++) {
      const longitude = west + ((column + 0.5) * (east - west)) / columns
      const latitude = south + ((row + 0.5) * (north - south)) / rows
      if (contains(ring, longitude, latitude))
        positions.push(new Cartographic(longitude, latitude))
    }
  return positions
}

/** Sample boundaries and interiors so a single low anchor cannot bury the roof. */
export async function sampleBuildingTerrain(
  polygons: PolygonGraphics[],
  terrain: TerrainProvider,
  time: JulianDate,
): Promise<TerrainBounds[]> {
  if (terrain instanceof EllipsoidTerrainProvider)
    return polygons.map(() => ({ minimum: 0, maximum: 0 }))
  const groups = polygons.map((polygon) => {
    const hierarchy = polygon.hierarchy?.getValue(time)
    if (!hierarchy?.positions.length)
      throw new Error('白模缺少有效轮廓，无法确定地形基准')
    return samplePositions(toRing(hierarchy))
  })
  await sampleTerrainMostDetailed(terrain, groups.flat(), true)
  return groups.map((positions) => {
    const heights = positions.map((point) => point.height)
    if (!heights.length || heights.some((height) => !Number.isFinite(height)))
      throw new Error('白模地形采样不完整，请检查网络后重试图层')
    return { minimum: Math.min(...heights), maximum: Math.max(...heights) }
  })
}
