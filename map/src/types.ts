export type LayerKind = 'geojson' | '3dtiles'
export interface LayerRecord {
  id: string
  name: string
  category: string
  type: LayerKind
  url: string
  source: string
  created_at?: string
  asset_id?: string | null
  asset_version?: string | null
  asset_source_kind?: 'default' | 'upload' | 'external' | null
  map_attached?: boolean
  map_visible?: boolean
  map_opacity?: number
}
export type LayerInput = Omit<LayerRecord, 'id' | 'created_at' | 'asset_id' | 'asset_version' | 'asset_source_kind' | keyof LayerMapState>
export interface LayerMapState {
  map_attached: boolean
  map_visible: boolean
  map_opacity: number
}
export interface Bookmark {
  id: string
  name: string
  kind: 'region' | 'point' | 'scene'
  region_id: string | null
  longitude: number | null
  latitude: number | null
  created_at: string
  state?: import('./workspaceState').WorkspaceState | null
}
export type BookmarkInput =
  | { name: string; kind: 'region'; region_id: string }
  | { name: string; kind: 'point'; longitude: number; latitude: number }
  | { name: string; kind: 'scene'; state: import('./workspaceState').WorkspaceState }
export type AssetReference =
  | { type?: 'layer'; id: string; name: string }
  | { type: 'scene' | 'run'; id: string; name: string; version: number; asset_version: string }
export interface AssetRecord {
  id: string
  original_name: string | null
  type: LayerKind | 'network' | 'unknown'
  entry_url: string | null
  byte_size: number | null
  file_count: number | null
  uploaded_at: string | null
  discovered_at: string
  status: 'active' | 'deleting' | 'delete_error' | 'missing' | 'unsafe'
  error: string
  references: AssetReference[]
  reference_count: number
  current_version?: string
  source_kind?: 'default' | 'upload' | 'external'
  protected?: boolean
  name?: string
  source?: string
  coordinate_description?: string
  sha256?: string | null
  bounds?: { west: number; south: number; east: number; north: number; min_height: number | null; max_height: number | null } | null
}
export interface AssetDetail extends AssetRecord {
  files: { path: string; size: number }[]
  file_checksums?: { path: string; size: number; sha256: string }[]
}
export interface Page<T> {
  items: T[]
  total: number
  page: number
  page_size: number
}
export interface AssetQuery {
  page?: number
  page_size?: number
  type?: AssetRecord['type'] | ''
  status?: AssetRecord['status'] | 'ready' | ''
  q?: string
  from?: string
  to?: string
  sort?: 'byte_size' | '-byte_size' | ''
}
export type AssetFilters = Omit<AssetQuery, 'page' | 'page_size'>
export interface StatsOverview {
  asset_count: number
  object_count: number
  run_count: number
  total_byte_size: number
  assets_by_type: Record<string, number>
  assets_added_last_7_days: number
}
export interface AssetRegisterInput {
  name: string
  type: LayerKind | 'network'
  location: string
  source?: string
  coordinate_description?: string
}
export interface AssetVersionRecord {
  asset_id: string
  version: string
  name: string
  type: AssetRecord['type']
  source_kind: 'default' | 'upload' | 'external'
  protected: boolean
  source: string
  coordinate_description: string
  entry_url: string | null
  byte_size: number | null
  file_count: number | null
  sha256: string | null
  bounds: Exclude<AssetRecord['bounds'], undefined>
  status: 'ready' | 'missing' | 'unsafe'
  created_at: string
}
export interface LayerCatalogRecord extends Omit<LayerRecord, 'type' | 'url'> {
  type: LayerKind | 'basemap'
  url: string | null
  asset: { asset_id: string; version: string } | null
  builtin: boolean
  campus: string | null
  static: boolean
  orderable: boolean
  object_count: number | null
  unit: string | null
  legend: { label: string; color: string; value?: string | number | null }[]
  order: number
}
export interface MapLayer extends LayerRecord {
  builtin: boolean
  attached: boolean
  visible: boolean
  opacity: number
  status: 'idle' | 'loading' | 'ready' | 'error'
  error: string
  color: string
  object_count?: number | null
  unit?: string | null
  legend?: LayerCatalogRecord['legend']
  order?: number
  orderable?: boolean
  campus?: string | null
  static?: boolean
  progress?: number | null
  loadPhase?: string
  traceId?: string
  errorCode?: string
}
export interface Selection {
  title: string
  layerName: string
  properties: Record<string, unknown>
  resourceType?: LayerKind
  objectId?: string
  layerId?: string
  asset?: { asset_id: string; version: string }
  object?: ObjectRecord | null
  detailLoading?: boolean
  detailError?: string
}
export interface GeometryDocument {
  type: 'Point' | 'MultiPoint' | 'LineString' | 'MultiLineString' | 'Polygon' | 'MultiPolygon' | 'GeometryCollection'
  coordinates?: unknown[] | null
  geometries?: GeometryDocument[] | null
}
export interface ObjectRecord {
  object_id: string
  asset: { asset_id: string; version: string }
  layer_id: string | null
  type: string
  name: string | null
  height_m: number | null
  level: string | null
  semantic_source: string
  confidence: number | null
  coordinates: number[] | null
  geometry: GeometryDocument | null
  properties: Record<string, unknown>
  feature_index: number | null
  temporal?: import('./temporalTypes').ObjectTemporal | null
}
export interface ObjectQuery {
  asset_id?: string
  version?: string
  layer_id?: string
  campus?: CampusKey
  type?: string
  q?: string
  bbox?: string
  time?: string
  resolution?: import('./temporalTypes').TimeResolution
  page?: number
  page_size?: number
}
const sampleTemplates: LayerRecord[] = [
  {
    id: 'campus-buildings',
    name: '校园建筑白模',
    category: '三维建筑',
    type: 'geojson',
    url: '/samples/campus-buildings.geojson',
    source: 'OSM公开轮廓 · 高度含估计 · 非测绘模型',
  },
  {
    id: 'demo-points',
    name: '积水监测点',
    category: '点状观测',
    type: 'geojson',
    url: '/samples/water-points.geojson',
    source: '合成演示 · 非实测数据',
  },
  {
    id: 'demo-roads',
    name: '道路流量',
    category: '线状网络',
    type: 'geojson',
    url: '/samples/roads.geojson',
    source: '合成演示 · 非真实路网',
  },
  {
    id: 'demo-areas',
    name: '积水范围',
    category: '面状区域',
    type: 'geojson',
    url: '/samples/areas.geojson',
    source: '合成演示 · 非风险预测',
  },
  {
    id: 'demo-buildings',
    name: '三维建筑小样',
    category: '三维模型',
    type: '3dtiles',
    url: '/samples/buildings/tileset.json',
    source: '合成演示 · 非真实建筑',
  },
]
export function samplesForCampus(key: CampusKey): LayerRecord[] {
  const campus = campuses.find((item) => item.key === key)!
  return sampleTemplates.map((record) => ({
    ...record,
    url: record.url.replace('/samples/', `/samples/${key}/`),
    source: `${campus.shortName} · ${record.source}`,
  }))
}
export const samples = samplesForCampus(defaultCampus.key)
export function mapLayer(record: LayerRecord | LayerCatalogRecord, builtin = false): MapLayer {
  const catalog = 'asset' in record ? record : undefined
  return {
    ...record,
    type: record.type === 'basemap' ? 'geojson' : record.type,
    url: record.url ?? '',
    asset_id: catalog ? catalog.asset?.asset_id ?? null : record.asset_id,
    asset_version: catalog ? catalog.asset?.version ?? null : record.asset_version,
    builtin: catalog?.builtin ?? builtin,
    attached: false,
    visible: record.map_visible ?? true,
    opacity: record.map_opacity ?? 1,
    status: 'idle',
    error: '',
    color:
      catalog?.legend?.[0]?.color ?? (record.id === 'demo-roads'
        ? '#e2a23b'
        : record.id === 'demo-areas'
          ? '#36b9ba'
          : record.type === '3dtiles' || record.id === 'campus-buildings'
            ? '#9eafc1'
            : '#347af0'),
  }
}
import { campuses, defaultCampus, type CampusKey } from './campuses.ts'
