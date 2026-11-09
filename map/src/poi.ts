import type { GeometryDocument, MapLayer } from './types'
import { Utensils, ShoppingBag, HeartPulse, GraduationCap, TrainFront, BedDouble, Landmark, Building2, MapPin, type LucideIcon, type LucideIconData } from '@lucide/vue'
import type { VNode } from 'vue'

export interface PoiFeature {
  type: 'Feature'
  geometry: GeometryDocument & { bbox?: number[] }
  properties: Record<string, unknown> | null
  bbox?: number[]
}
export interface PoiData {
  type: 'FeatureCollection'
  features: PoiFeature[]
  bbox?: number[]
}

export function propertyText(properties: Record<string, unknown>, ...keys: string[]) {
  for (const key of keys) {
    const value = properties[key]
    if (typeof value === 'string' && value.trim()) return value.trim()
  }
  return ''
}

export const poiRawCategory = (properties: Record<string, unknown>) =>
  propertyText(properties, 'category', '类别', '類別', 'amenity', 'shop', 'tourism', 'railway', 'aeroway', 'leisure', 'historic', 'fclass') || '其他'
export function poiCategory(properties: Record<string, unknown>) {
  const category = poiRawCategory(properties).toLowerCase()
  if (/餐饮|餐飲|restaurant|cafe|food|bar|pub|fast_food/.test(category)) return '餐饮'
  if (/住宿|hotel|hostel|motel|guest_house/.test(category)) return '住宿'
  if (/医疗|醫療|hospital|clinic|pharmacy|doctors|dentist/.test(category)) return '医疗'
  if (/教育|school|university|college|kindergarten|library/.test(category)) return '教育'
  if (/fire_station|police/.test(category)) return '公共服务'
  if (/交通|parking|station|bus|fuel|aerodrome|airport|halt|stop_position/.test(category)) return '交通'
  if (/购物|購物|商|mall|supermarket|convenience|shop/.test(category) || typeof properties.shop === 'string') return '购物'
  if (/文旅|景点|景點|attraction|museum|viewpoint|park|garden|artwork|historic|memorial|monument/.test(category)) return '文旅'
  if (/公共|police|fire_station|post_office|townhall|community_centre|toilets|drinking_water|waste|recycling/.test(category)) return '公共服务'
  return '其他'
}
export function poiName(properties: Record<string, unknown>) {
  const name = propertyText(properties, 'name:zh', '名称', '名稱', 'name').trim()
  return /^(?:未命名(?:\s*POI)?|其他|餐馆|餐厅|商店|学校|医院|停车场|图书馆|酒店|便利店|卫生间|restaurant|cafe|shop|school|hospital|parking|library|hotel|toilets|atm|\d+)$/i.test(name) ? '' : name
}
const iconStyles: Record<string, [LucideIcon, string]> = {
  餐饮: [Utensils, '#b66c35'], 购物: [ShoppingBag, '#a45d88'], 医疗: [HeartPulse, '#bd5260'],
  教育: [GraduationCap, '#526fa8'], 交通: [TrainFront, '#397d9e'], 住宿: [BedDouble, '#8a65a5'],
  文旅: [Landmark, '#518c65'], 公共服务: [Building2, '#697d8b'], 其他: [MapPin, '#798793'],
}
const iconCache = new Map<string, string>()
export function poiIcon(category: string) {
  const key = category in iconStyles ? category : '其他'
  if (iconCache.has(key)) return iconCache.get(key)!
  const [component, color] = iconStyles[key]!
  const vnode = component({}, { slots: {} } as Parameters<LucideIcon>[1]) as VNode
  const icon = vnode.props!.icon as LucideIconData
  const paths = icon.node.map(([tag, attributes]) => `<${tag} ${Object.entries(attributes).filter(([name]) => name !== 'key')
    .map(([name, value]) => `${name}="${String(value)}"`).join(' ')}/>`).join('')
  const svg = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke-linecap="round" stroke-linejoin="round"><g stroke="white" stroke-width="5">${paths}</g><g stroke="${color}" stroke-width="2">${paths}</g></svg>`
  const url = `data:image/svg+xml,${encodeURIComponent(svg)}`
  iconCache.set(key, url)
  return url
}
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
  propertyText(properties, 'highway', 'level', '等级', '等級', 'fclass')

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
