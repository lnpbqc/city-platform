import type { AssetDetail, AssetRecord, AssetQuery, AssetRegisterInput, AssetVersionRecord, Page, StatsOverview, LayerInput, LayerRecord, LayerCatalogRecord, LayerMapState, Bookmark, BookmarkInput, ObjectRecord, ObjectQuery, GeometryDocument } from './types'
import type { CampusKey } from './campuses'
import type { SceneInput, SceneRecord, NetworkRecord, RunInput, RunRecord, RunSnapshot, RunResult, RunQuery } from './simulationTypes'
import type { TemporalContext, TimeLayerQuery, TimeSeriesQuery, TimeSeriesRecord } from './temporalTypes'
import { publishApiEvent } from './apiEvents.ts'

export class ApiError extends Error {
  status: number
  detail: unknown
  code: string
  traceId: string
  description: string
  constructor(message: string, status: number, detail: unknown, code = 'HTTP_ERROR', traceId = '') {
    super(traceId ? `${message} (${code} · trace_id: ${traceId})` : message)
    this.status = status
    this.detail = detail
    this.code = code
    this.traceId = traceId
    this.description = message
  }
}

function responseError(status: number, body: unknown, headerTrace = '') {
  const envelope = body && typeof body === 'object' ? body as Record<string, unknown> : {}
  const detail = envelope.detail
  const code = typeof envelope.code === 'string' ? envelope.code : 'HTTP_ERROR'
  const traceId = typeof envelope.trace_id === 'string' ? envelope.trace_id : headerTrace
  const message = typeof envelope.message === 'string'
    ? envelope.message
    : typeof detail === 'string'
      ? detail
      : Array.isArray(detail)
        ? detail.map((item: { msg: string }) => item.msg).join('；')
        : detail && typeof detail === 'object' && 'message' in detail && typeof detail.message === 'string'
          ? detail.message
          : `请求失败 (${status})`
  const error = new ApiError(status === 401 || status === 403 ? `无权限：${message}` : message, status, detail, code, traceId)
  publishApiEvent({ reachable: true, error })
  return error
}
const networkError = () => {
  const error = new ApiError('无法连接数据服务', 0, null, 'NETWORK_ERROR', `client-${crypto.randomUUID()}`)
  publishApiEvent({ reachable: false, error })
  return error
}

async function request<T>(url: string, options?: RequestInit, format: 'json' | 'blob' = 'json'): Promise<T> {
  let response: Response
  try {
    response = await fetch(url, options)
  } catch (cause) {
    if (cause instanceof Error && cause.name === 'AbortError') throw cause
    throw networkError()
  }
  if (!response.ok) {
    let body: unknown
    try {
      body = await response.json()
    } catch {
      /* A disconnected proxy may return plain text. */
    }
    throw responseError(response.status, body, response.headers.get('X-Trace-ID') || '')
  }
  try {
    const result = response.status === 204 ? undefined : format === 'blob' ? await response.blob() : await response.json()
    publishApiEvent({ reachable: true })
    return result as T
  } catch (cause) {
    if (cause instanceof Error && cause.name === 'AbortError') throw cause
    if (cause instanceof TypeError) throw networkError()
    const error = new ApiError('服务响应内容无法解析', 502, null, 'INVALID_RESPONSE', response.headers.get('X-Trace-ID') || `client-${crypto.randomUUID()}`)
    publishApiEvent({ reachable: true, error })
    throw error
  }
}
export const getLayers = () => request<LayerRecord[]>('/api/layers')
export const getLayerCatalog = (campus: CampusKey, signal?: AbortSignal) =>
  request<LayerCatalogRecord[]>(`/api/layers/catalog?campus=${encodeURIComponent(campus)}`, { signal })
export const saveCatalogMapState = (id: string, body: Partial<LayerMapState> & { order?: number }, campus: CampusKey = 'university-town') =>
  request<LayerCatalogRecord>(`/api/layers/catalog/${encodeURIComponent(id)}/map-state?campus=${encodeURIComponent(campus)}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
    keepalive: true,
  })
export const saveLayer = (body: LayerInput, id?: string) =>
  request<LayerRecord>(id ? `/api/layers/${id}` : '/api/layers', {
    method: id ? 'PATCH' : 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
export const deleteLayer = (id: string) =>
  request<void>(`/api/layers/${id}`, { method: 'DELETE' })
export interface UploadOptions {
  signal?: AbortSignal
  onProgress?: (loaded: number, total: number) => void
  onUploaded?: () => void
}
export function uploadLayer(body: FormData, options: UploadOptions = {}): Promise<LayerRecord> {
  const aborted = () => new DOMException('上传已取消', 'AbortError')
  if (options.signal?.aborted) return Promise.reject(aborted())
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest()
    const abort = () => xhr.abort()
    const cleanup = () => {
      options.signal?.removeEventListener('abort', abort)
      xhr.onload = xhr.onerror = xhr.onabort = xhr.ontimeout = null
      xhr.upload.onprogress = xhr.upload.onload = null
    }
    xhr.open('POST', '/api/layers/upload')
    xhr.upload.onprogress = (event) => options.onProgress?.(event.loaded, event.lengthComputable ? event.total : 0)
    xhr.upload.onload = () => options.onUploaded?.()
    xhr.onload = () => {
      let result: unknown
      try { result = JSON.parse(xhr.responseText) } catch { /* Proxy errors may be plain text. */ }
      cleanup()
      if (xhr.status >= 200 && xhr.status < 300) { publishApiEvent({ reachable: true }); resolve(result as LayerRecord) }
      else reject(responseError(xhr.status, result, xhr.getResponseHeader('X-Trace-ID') || ''))
    }
    xhr.onerror = xhr.ontimeout = () => { cleanup(); reject(networkError()) }
    xhr.onabort = () => { cleanup(); reject(aborted()) }
    options.signal?.addEventListener('abort', abort, { once: true })
    try { xhr.send(body) } catch { cleanup(); reject(networkError()) }
  })
}
export const saveLayerMapState = (id: string, body: LayerMapState) =>
  request<LayerRecord>(`/api/layers/${id}/map-state`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
    keepalive: true,
  })
export const getBookmarks = () => request<Bookmark[]>('/api/bookmarks')
export const createBookmark = (body: BookmarkInput) =>
  request<Bookmark>('/api/bookmarks', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
export const renameBookmark = (id: string, name: string) =>
  request<Bookmark>(`/api/bookmarks/${id}`, {
    method: 'PATCH', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ name }),
  })
export const deleteBookmark = (id: string) =>
  request<void>(`/api/bookmarks/${id}`, { method: 'DELETE' })
export const getAssets = () => request<AssetRecord[]>('/api/assets')
export const getAssetPage = (query: AssetQuery = {}) => {
  const params = new URLSearchParams()
  for (const [key, value] of Object.entries({ ...query, page: query.page ?? 1, page_size: query.page_size ?? 20 })) {
    if (value !== undefined && value !== '') params.set(key, String(value))
  }
  return request<Page<AssetRecord>>(`/api/assets?${params}`)
}
export const getStats = () => request<StatsOverview>('/api/stats/overview')
export const getAssetVersions = (id: string) =>
  request<AssetVersionRecord[]>(`/api/assets/${encodeURIComponent(id)}/versions`)
export const getAssetVersion = (id: string, version: string, signal?: AbortSignal) =>
  request<AssetVersionRecord>(`/api/assets/${encodeURIComponent(id)}/versions/${encodeURIComponent(version)}`, { signal })
export const registerAsset = (body: AssetRegisterInput) =>
  request<AssetVersionRecord>('/api/assets/register', {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
  })
export const getAsset = (id: string) =>
  request<AssetDetail>(`/api/assets/${id}`)
export const reconcileAssets = () =>
  request<{ assets: AssetRecord[]; discovered: number }>(
    '/api/assets/reconcile',
    { method: 'POST' },
  )
export const deleteAsset = (id: string) =>
  request<void>(`/api/assets/${id}`, { method: 'DELETE' })
export const getObjects = (query: ObjectQuery = {}, signal?: AbortSignal) => {
  const params = new URLSearchParams()
  for (const [key, value] of Object.entries(query)) {
    if (value !== undefined && value !== '') params.set(key, String(value))
  }
  return request<Page<ObjectRecord>>(`/api/objects?${params}`, { signal })
}
export const getObject = (id: string, signal?: AbortSignal, temporal?: TemporalContext | null) => {
  const params = temporal ? `?${new URLSearchParams({ time: temporal.time, resolution: temporal.resolution })}` : ''
  return request<ObjectRecord>(`/api/objects/${encodeURIComponent(id)}${params}`, { signal })
}
export const selectObjects = (query: ObjectQuery, geometry: GeometryDocument, signal?: AbortSignal) =>
  request<Page<ObjectRecord>>('/api/objects/select', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ ...query, geometry }), signal,
  })
export const getScenes = (query: { page?: number; page_size?: number } = {}, signal?: AbortSignal) =>
  request<Page<SceneRecord>>(`/api/scenes?page=${encodeURIComponent(query.page ?? 1)}&page_size=${encodeURIComponent(query.page_size ?? 20)}`, { signal })
export const getScene = (id: string, signal?: AbortSignal, version?: number) =>
  request<SceneRecord>(`/api/scenes/${encodeURIComponent(id)}${version === undefined ? '' : `?version=${encodeURIComponent(version)}`}`, { signal })
export const saveScene = (body: SceneInput, id?: string, version?: number, signal?: AbortSignal) =>
  request<SceneRecord>(id ? `/api/scenes/${encodeURIComponent(id)}` : '/api/scenes', {
    method: id ? 'PUT' : 'POST',
    headers: { 'Content-Type': 'application/json', ...(id ? { 'If-Match': `"${version}"` } : {}) },
    body: JSON.stringify(body), signal,
  })
export const deleteScene = (id: string, version: number, signal?: AbortSignal) =>
  request<void>(`/api/scenes/${encodeURIComponent(id)}`, { method: 'DELETE', headers: { 'If-Match': `"${version}"` }, signal })
export const getNetworks = (query: { page?: number; page_size?: number } = {}, signal?: AbortSignal) =>
  request<Page<NetworkRecord>>(`/api/networks?page=${encodeURIComponent(query.page ?? 1)}&page_size=${encodeURIComponent(query.page_size ?? 20)}`, { signal })
export const getNetwork = (id: string, version?: string, signal?: AbortSignal) =>
  request<NetworkRecord>(`/api/networks/${encodeURIComponent(id)}${version === undefined ? '' : `?version=${encodeURIComponent(version)}`}`, { signal })
export const submitRun = (body: RunInput, key: string, signal?: AbortSignal) =>
  request<RunRecord>('/api/runs', { method: 'POST', headers: { 'Content-Type': 'application/json', 'Idempotency-Key': key }, body: JSON.stringify(body), signal })
export const getRun = (id: string, signal?: AbortSignal) => request<RunRecord>(`/api/runs/${encodeURIComponent(id)}`, { signal })
export const getRunInput = (id: string, signal?: AbortSignal) => request<RunSnapshot>(`/api/runs/${encodeURIComponent(id)}/input`, { signal })
export const getRunResult = (id: string, signal?: AbortSignal) => request<RunResult>(`/api/runs/${encodeURIComponent(id)}/result`, { signal })
export const cancelRun = (id: string, signal?: AbortSignal) => request<RunRecord>(`/api/runs/${encodeURIComponent(id)}/cancel`, { method: 'POST', signal })
export const getRuns = (query: RunQuery = {}, signal?: AbortSignal) => {
  const params = new URLSearchParams()
  for (const [key, value] of Object.entries({ ...query, page: query.page ?? 1, page_size: query.page_size ?? 20 })) {
    if (value !== undefined && value !== '') params.set(key, String(value))
  }
  return request<Page<RunRecord>>(`/api/runs?${params}`, { signal })
}
export const rerunRun = (id: string, key: string, signal?: AbortSignal) =>
  request<RunRecord>(`/api/runs/${encodeURIComponent(id)}/rerun`, { method: 'POST', headers: { 'Idempotency-Key': key }, signal })
export const downloadRun = (id: string, format: 'json' | 'geojson', signal?: AbortSignal) =>
  request<Blob>(`/api/runs/${encodeURIComponent(id)}/download?format=${encodeURIComponent(format)}`, { signal }, 'blob')
export const getLayerTimes = (id: string, query: TimeLayerQuery = {}, signal?: AbortSignal) => {
  const params = new URLSearchParams()
  for (const [key, value] of Object.entries(query)) if (value !== undefined && value !== '') params.set(key, value)
  return request<string[]>(`/api/layers/${encodeURIComponent(id)}/times?${params}`, { signal })
}
export const getTimeSeries = (query: TimeSeriesQuery, signal?: AbortSignal) => {
  const params = new URLSearchParams()
  for (const [key, value] of Object.entries(query)) if (value !== undefined && value !== '') params.set(key, value)
  return request<TimeSeriesRecord>(`/api/timeseries?${params}`, { signal })
}
