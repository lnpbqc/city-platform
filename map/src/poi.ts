import type { GeometryDocument, MapLayer } from './types'

export interface PoiFeature {
  type: 'Feature'
  geometry: GeometryDocument
  properties: Record<string, unknown> | null
}
export interface PoiData {
  type: 'FeatureCollection'
  features: PoiFeature[]
}

export function propertyText(properties: Record<string, unknown>, ...keys: string[]) {
  for (const key of keys) {
    const value = properties[key]
    if (typeof value === 'string' && value.trim()) return value.trim()
  }
  return ''
}

export const poiCategory = (properties: Record<string, unknown>) =>
  propertyText(properties, 'category', '类别', '類別', 'amenity', 'shop', 'tourism') || '其他'
export const poiAddress = (properties: Record<string, unknown>) =>
  typeof properties.address === 'string' ? properties.address.trim() :
    propertyText(properties, '地址', 'addr:full') ||
    [propertyText(properties, 'addr:street'), propertyText(properties, 'addr:housenumber')].filter(Boolean).join(' ')

export function poiGlyph(category: string) {
  if (/餐饮|餐飲|restaurant|cafe|food|bar/.test(category)) return '餐'
  if (/交通|parking|station|bus|fuel/.test(category)) return '行'
  if (/购物|購物|商|mall|supermarket|convenience|shop/.test(category)) return '购'
  if (/医疗|醫療|hospital|clinic|pharmacy/.test(category)) return '医'
  if (/景点|景點|attraction|museum|viewpoint|park/.test(category)) return '景'
  return '点'
}

export const roadLevel = (properties: Record<string, unknown>) =>
  propertyText(properties, 'highway', 'level', '等级', '等級')

export function roadWidth(level: string) {
  if (/^(motorway|trunk|primary)(?:_link)?$|高速|主干/.test(level)) return 6
  if (/^(secondary|tertiary)(?:_link)?$|次干/.test(level)) return 4
  if (/^(residential|service|footway|cycleway|path|track|living_street)$|支路|步行/.test(level)) return 2
  return 4
}

export const editablePoi = (layer: MapLayer) => layer.category === 'POI' && layer.type === 'geojson' &&
  !layer.builtin && layer.url.startsWith('/data-files/') && !!layer.asset_id && !!layer.asset_version

export const poiFile = (data: PoiData = { type: 'FeatureCollection', features: [] }) =>
  new File([JSON.stringify(data)], 'poi.geojson', { type: 'application/geo+json' })
