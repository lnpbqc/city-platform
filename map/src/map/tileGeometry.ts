import type { GeometryDocument } from '../layers/types'
import polygonClipping from 'polygon-clipping'
import type { Polygon, MultiPolygon } from 'polygon-clipping'

export function clipPolygon(geometry: GeometryDocument, bbox: [number, number, number, number]): GeometryDocument {
  const [west, south, east, north] = bbox
  const rectangle: Polygon = [[[west, south], [east, south], [east, north], [west, north], [west, south]]]
  const parts = polygonClipping.intersection(geometry.coordinates as unknown as Polygon | MultiPolygon, rectangle)
  return parts.length === 1 ? { type: 'Polygon', coordinates: parts[0] } : { type: 'MultiPolygon', coordinates: parts }
}

export function tileBounds(z: number, x: number, y: number): [number, number, number, number] {
  const count = 2 ** z
  const latitude = (value: number) => Math.atan(Math.sinh(Math.PI * (1 - 2 * value / count))) * 180 / Math.PI
  return [x / count * 360 - 180, latitude(y + 1), (x + 1) / count * 360 - 180, latitude(y)]
}

export function viewTiles(bbox: number[], z: number): [number, number, number][] | null {
  const count = 2 ** z
  const x = (longitude: number) => Math.max(0, Math.min(count - 1, Math.floor((longitude + 180) / 360 * count)))
  const y = (latitude: number) => {
    const radians = Math.max(-85.05112878, Math.min(85.05112878, latitude)) * Math.PI / 180
    return Math.max(0, Math.min(count - 1, Math.floor((1 - Math.asinh(Math.tan(radians)) / Math.PI) / 2 * count)))
  }
  const [west, south, east, north] = bbox as [number, number, number, number]
  const windows = west <= east ? [[west, east]] : [[west, 180], [-180, east]]
  const tiles: [number, number, number][] = []
  const seen = new Set<string>()
  for (const [left, right] of windows) {
    const top = y(north), bottom = y(south), start = x(left!), end = x(right!)
    if ((end - start + 1) * (bottom - top + 1) + tiles.length > 64) return null
    for (let row = top; row <= bottom; row++) for (let column = start; column <= end; column++) {
      const key = `${column}/${row}`
      if (!seen.has(key)) { tiles.push([z, column, row]); seen.add(key) }
    }
  }
  return tiles
}

export function vertexCount(geometry: GeometryDocument): number {
  const count = (value: unknown): number => {
    if (!Array.isArray(value) || !value.length) return 0
    if (typeof value[0] === 'number') return 1
    return value.reduce((total: number, child: unknown) => total + count(child), 0)
  }
  return geometry.type === 'GeometryCollection'
    ? (geometry.geometries ?? []).reduce((total, part) => total + vertexCount(part), 0) : count(geometry.coordinates)
}

export function mergeParts(parts: GeometryDocument[]): GeometryDocument {
  if (parts.length === 1) return parts[0]!
  const base = parts[0]!.type.replace('Multi', '')
  if (base === 'LineString' || base === 'Polygon' || base === 'Point') {
    if (parts.every(part => part.type.replace('Multi', '') === base)) {
      return { type: `Multi${base}` as GeometryDocument['type'],
        coordinates: parts.flatMap(part => part.type.startsWith('Multi') ? part.coordinates ?? [] : [part.coordinates]) }
    }
  }
  return { type: 'GeometryCollection', geometries: parts }
}
