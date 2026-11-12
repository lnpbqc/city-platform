import coordtransform from 'coordtransform'

export interface BoundaryState {
  status: 'idle' | 'loading' | 'ready' | 'error'
  error?: string
}

interface BoundaryFeature {
  properties: { adcode: number | string }
  geometry: { type: string; coordinates: number[][][] | number[][][][] }
}

// Render each ring as a line: ground polygon outlines are unsupported by Cesium.
// This also keeps the region's interior available for picking user data.
export function boundaryLines(data: unknown, id: string) {
  const input = data as { type?: string; features?: BoundaryFeature[] } | null
  if (input?.type !== 'FeatureCollection' || !Array.isArray(input.features))
    throw new Error('边界数据不是有效的 FeatureCollection')
  const feature = input.features.find(
    (item) => String(item?.properties?.adcode) === id,
  )
  const geometry = feature?.geometry
  if (!geometry || !['Polygon', 'MultiPolygon'].includes(geometry.type))
    throw new Error('数据源未提供所选地区的面边界')
  const polygons =
    geometry.type === 'Polygon'
      ? [geometry.coordinates as number[][][]]
      : (geometry.coordinates as number[][][][])
  if (!polygons.length) throw new Error('边界为空')
  const lines = polygons.flatMap((polygon) => {
    if (!Array.isArray(polygon) || !polygon.length)
      throw new Error('边界面无效')
    return polygon.map((ring) => {
      if (!Array.isArray(ring) || ring.length < 4) throw new Error('边界环无效')
      const coordinates = ring.map((point) => {
        const [longitude, latitude] = point
        if (
          !Number.isFinite(longitude) ||
          !Number.isFinite(latitude) ||
          Math.abs(longitude!) > 180 ||
          Math.abs(latitude!) > 90
        )
          throw new Error('边界坐标无效')
        // Match the directory's coordinate convention; Taiwan is not offset.
        return id.startsWith('71')
          ? [longitude!, latitude!]
          : coordtransform.gcj02towgs84(longitude!, latitude!)
      })
      if (ring[0]![0] !== ring.at(-1)![0] || ring[0]![1] !== ring.at(-1)![1])
        throw new Error('边界环未闭合')
      return {
        type: 'Feature' as const,
        properties: {},
        geometry: {
          type: 'LineString' as const,
          coordinates,
        },
      }
    })
  })
  return { type: 'FeatureCollection' as const, features: lines }
}

export async function fetchRegionBoundary(id: string, signal: AbortSignal) {
  if (!/^\d{6}$/.test(id)) throw new Error('行政区代码无效')
  const response = await fetch(
    `https://geo.datav.aliyun.com/areas_v3/bound/${id}.json`,
    { signal },
  )
  if (!response.ok) throw new Error(`边界服务 HTTP ${response.status}`)
  return boundaryLines(await response.json(), id)
}
