import { ApiError } from './api.ts'

export function planarGeoJSON(data: { features?: { geometry?: { type?: string; coordinates?: unknown } | null; properties?: Record<string, unknown> | null }[] }) {
  const hasZ = (coordinates: unknown): boolean => Array.isArray(coordinates) &&
    (typeof coordinates[0] === 'number' ? coordinates.length > 2 : coordinates.some(hasZ))
  return Array.isArray(data.features) && data.features.every(feature => {
    const geometry = feature.geometry
    if (geometry?.type === 'GeometryCollection' || hasZ(geometry?.coordinates)) return false
    const height = feature.properties?.map_extrude_height_m
    return !(['Polygon', 'MultiPolygon'].includes(geometry?.type ?? '') && typeof height === 'number' && height > 0 && height <= 1000)
  })
}

export function mapLoadError(cause: unknown) {
  if (cause instanceof ApiError) return cause
  const error = cause as { statusCode?: number; response?: string; responseHeaders?: Record<string, string>; message?: string } | null
  let body: { message?: string; code?: string; detail?: unknown; trace_id?: string } = {}
  try { body = JSON.parse(error?.response || '{}') } catch { /* Cesium or remote servers can return plain text. */ }
  const header = Object.entries(error?.responseHeaders || {}).find(([key]) => key.toLowerCase() === 'x-trace-id')?.[1]
  return new ApiError(body.message || error?.message || '资源加载失败', error?.statusCode || 0, body.detail ?? null,
    body.code || 'RESOURCE_LOAD_FAILED', body.trace_id || header || `client-${crypto.randomUUID()}`)
}

export async function fetchMapGeoJSON(url: string, signal: AbortSignal, onProgress?: (loaded: number, total: number) => void) {
  try {
    const response = await fetch(url, { signal })
    if (!response.ok) throw mapLoadError({ statusCode: response.status, response: await response.text(),
      responseHeaders: { 'x-trace-id': response.headers.get('X-Trace-ID') || '' }, message: `资源请求失败 (${response.status})` })
    const total = Number(response.headers.get('Content-Length')) || 0
    const reader = response.body?.getReader()
    let source = ''
    if (reader) {
      const decoder = new TextDecoder()
      let loaded = 0
      try {
        while (true) {
          const { done, value } = await reader.read()
          if (done) break
          loaded += value.length
          source += decoder.decode(value, { stream: true })
          onProgress?.(loaded, total)
        }
        source += decoder.decode()
      } finally { reader.releaseLock() }
    } else source = await response.text()
    try { return JSON.parse(source.replace(/^\uFEFF/, '')) } catch {
      throw new ApiError('GeoJSON内容无法解析', 422, null, 'RESOURCE_INVALID', `client-${crypto.randomUUID()}`)
    }
  } catch (cause) {
    if (cause instanceof Error && cause.name === 'AbortError') throw cause
    throw mapLoadError(cause)
  }
}
