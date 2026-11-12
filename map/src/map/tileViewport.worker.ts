import { FetchSource, PMTiles } from 'pmtiles'
import type { RangeResponse, Source } from 'pmtiles'
import { VectorTile } from '@mapbox/vector-tile'
import { PbfReader } from 'pbf'
import bboxClip from '@turf/bbox-clip'
import type { Feature, LineString, MultiLineString, MultiPolygon, Polygon } from 'geojson'
import type { GeometryDocument, MapViewportFeature, MapViewportResult } from '../layers/types'
import type { TileView, TileRender } from './tileViewport'
import { clipPolygon, mergeParts, tileBounds, vertexCount, viewTiles } from './tileGeometry.ts'

class RangeCache implements Source {
  private source: FetchSource
  private entries = new Map<string, RangeResponse>()
  private size = 0
  constructor(url: string) { this.source = new FetchSource(url) }
  getKey() { return this.source.getKey() }
  async getBytes(offset: number, length: number, signal?: AbortSignal, etag?: string) {
    const key = `${offset}/${length}/${etag ?? ''}`
    const cached = this.entries.get(key)
    if (cached) { this.entries.delete(key); this.entries.set(key, cached); return cached }
    const value = await this.source.getBytes(offset, length, signal, etag)
    if (value.data.byteLength <= 32 * 1024 ** 2) {
      this.entries.set(key, value); this.size += value.data.byteLength
      while (this.size > 32 * 1024 ** 2) {
        const oldest = this.entries.keys().next().value!
        this.size -= this.entries.get(oldest)!.data.byteLength
        this.entries.delete(oldest)
      }
    }
    return value
  }
}

let archive: PMTiles | undefined
let archiveUrl = ''
const active = new Map<number, AbortController>()

function allowed(properties: Record<string, unknown>, view: TileView, profile: string) {
  if (profile === 'roads' || typeof properties.road_rank === 'number') {
    if (properties.road_renderable === false) return false
    const rank = Number(properties.road_rank ?? 2)
    const scaleRank = view.meters_per_pixel > 20 ? 0 : view.meters_per_pixel > 5 ? 1 : view.meters_per_pixel > 1 ? 2 : 3
    return rank <= Math.min(scaleRank, (view.road_max_level ?? 2) - 1)
  }
  if (profile === 'poi') {
    const maximum = Number(properties.max_scale ?? 1)
    return properties.background_eligible === true && (maximum < 0 || view.meters_per_pixel <= maximum)
  }
  return true
}

async function load(render: TileRender, view: TileView, signal: AbortSignal): Promise<MapViewportResult> {
  if (!render.url) throw new Error('瓦片地址不可用')
  if (archiveUrl !== render.url) { archive = new PMTiles(new RangeCache(render.url)); archiveUrl = render.url }
  const header = await archive!.getHeader()
  const latitude = (view.bbox[1] + view.bbox[3]) / 2
  const targetZoom = Math.max(header.minZoom, Math.min(header.maxZoom,
    Math.floor(Math.log2(156543.03392 * Math.max(.01, Math.cos(latitude * Math.PI / 180)) / view.meters_per_pixel))))
  const roadFidelity = render.contains_roads || render.profile === 'roads'
  const minimumZoom = roadFidelity ? targetZoom : header.minZoom
  for (let zoom = targetZoom; zoom >= minimumZoom; zoom--) {
    if (signal.aborted) throw new Error('视野已取消')
    const tiles = viewTiles(view.bbox, zoom)
    if (!tiles) continue
    const byId = new Map<string, { feature: MapViewportFeature; parts: GeometryDocument[] }>()
    let vertices = 0, overflow = false
    for (const [z, x, y] of tiles) {
      const data = await archive!.getZxy(z, x, y, signal)
      if (!data) continue
      const layer = new VectorTile(new PbfReader(data.data)).layers.data
      if (!layer) throw new Error('归档缺少 data 图层')
      const bounds = tileBounds(z, x, y)
      const [west, south, east, north] = view.bbox
      const windows = west <= east ? [[west, east]] : [[west, 180], [-180, east]]
      const visibleWindows = windows.map(window => [Math.max(bounds[0], window[0]!), Math.max(bounds[1], south),
        Math.min(bounds[2], window[1]!), Math.min(bounds[3], north)] as [number, number, number, number])
        .filter(window => window[0] <= window[2] && window[1] <= window[3])
      for (let index = 0; index < layer.length; index++) {
        const item = layer.feature(index)
        if (!allowed(item.properties, view, render.profile ?? 'generic')) continue
        const identity = String(item.properties.object_id ?? '')
        if (!identity || !Number.isInteger(item.properties.feature_index)) throw new Error('瓦片缺少原始对象身份')
        let value = item.toGeoJSON(x, y, z)
        if (value.geometry.type === 'Point') {
          const [lon, lat] = value.geometry.coordinates
          if (lon! < bounds[0] || lon! >= bounds[2] || lat! < bounds[1] || lat! >= bounds[3]) continue
          if (!visibleWindows.some(window => lon! >= window[0] && lon! <= window[2] && lat! >= window[1] && lat! <= window[3])) continue
        } else if (value.geometry.type === 'MultiPoint') {
          value.geometry.coordinates = value.geometry.coordinates.filter(([lon, lat]) => lon! < bounds[2] && lat! < bounds[3] &&
            visibleWindows.some(window => lon! >= window[0] && lon! <= window[2] && lat! >= window[1] && lat! <= window[3]))
          if (!value.geometry.coordinates.length) continue
        } else {
          const polygon = value.geometry.type === 'Polygon' || value.geometry.type === 'MultiPolygon'
          const parts = visibleWindows.map(window => polygon ? clipPolygon(value.geometry as GeometryDocument, window)
            : bboxClip(value as Feature<LineString | MultiLineString | Polygon | MultiPolygon>, window).geometry as GeometryDocument)
            .filter(part => vertexCount(part) > 0)
          if (!parts.length) continue
          value.geometry = mergeParts(parts) as typeof value.geometry
        }
        const geometry = value.geometry as GeometryDocument
        const count = vertexCount(geometry)
        if (!count) continue
        vertices += count
        if (vertices > 100_000 || !byId.has(identity) && byId.size >= 2000) { overflow = true; break }
        const previous = byId.get(identity)
        if (previous) previous.parts.push(geometry)
        else byId.set(identity, { parts: [geometry], feature: {
          type: 'Feature', id: identity, geometry, properties: item.properties,
          __object: { object_id: identity, feature_index: Number(item.properties.feature_index),
            asset: { asset_id: view.asset_id, version: view.version }, weight: Number(item.properties.weight ?? 0) },
          __display: { road_class: item.properties.road_class as string | undefined,
            road_rank: item.properties.road_rank as number | undefined, poi_category: item.properties.poi_category as string | undefined,
            priority: Number(item.properties.priority ?? 0), name: item.properties.name as string | undefined } } })
      }
      if (overflow) break
    }
    if (overflow) continue
    const features = [...byId.values()].map(({ feature, parts }) => ({ ...feature, geometry: mergeParts(parts) }))
    const result: MapViewportResult = { type: 'FeatureCollection', features, truncated: zoom < targetZoom }
    if (new TextEncoder().encode(JSON.stringify(result)).byteLength <= 10 * 1024 ** 2) return result
  }
  throw new Error(roadFidelity ? '道路瓦片超出保真显示预算，使用视野数据' : '当前视野瓦片超出显示预算')
}

self.onmessage = async event => {
  if (event.data.cancel !== undefined) { active.get(event.data.cancel)?.abort(); return }
  const { id, render, view } = event.data
  for (const request of active.values()) request.abort()
  const controller = new AbortController()
  active.set(id, controller)
  try {
    const data = await load(render, view, controller.signal)
    if (!controller.signal.aborted) self.postMessage({ id, data })
  } catch (error) {
    if (!controller.signal.aborted) self.postMessage({ id, error: error instanceof Error ? error.message : String(error) })
  } finally { active.delete(id) }
}
