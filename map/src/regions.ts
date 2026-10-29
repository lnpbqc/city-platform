export type RegionLevel = 'country' | 'province' | 'city' | 'district'
export interface Region {
  id: string
  name: string
  level: RegionLevel
  parent: string | null
  longitude: number
  latitude: number
}
export interface RegionCatalog {
  source: string
  retrievedAt: string
  coverageNote: string
  regions: Region[]
}
export interface RegionTarget {
  sampleKey?: CampusKey
  id: string
  label: string
  longitude: number
  latitude: number
  range: number
  pitch: number
}
export const campusRegions: RegionTarget[] = campuses.map((campus) => ({
  id: `demo-${campus.key}`,
  sampleKey: campus.key,
  label: `${campus.name} · 校园白模`,
  longitude: campus.longitude,
  latitude: campus.latitude,
  range: campus.range,
  pitch: -52,
}))
export const demoRegion = campusRegions.find(
  (region) => region.sampleKey === defaultCampus.key,
)!
export const demonstrationRegions: RegionTarget[] = [
  { id: 'demo-victoria-harbour', label: '香港维港', longitude: 114.1705, latitude: 22.2935, range: 6500, pitch: -48 },
  { id: 'demo-zhujiang-new-town', label: '广州珠江新城', longitude: 113.3235, latitude: 23.119, range: 4500, pitch: -48 },
]
export const chinaRegion: RegionTarget = {
  id: '100000',
  label: '中国 · 全国概览',
  longitude: 104.5,
  latitude: 35.7,
  range: 9_000_000,
  pitch: -90,
}

export function createRegionIndex(regions: Region[]) {
  const byId = new Map(regions.map((region) => [region.id, region]))
  const childMap = new Map<string, Region[]>()
  for (const region of regions) {
    if (region.parent) {
      const children = childMap.get(region.parent) ?? []
      children.push(region)
      childMap.set(region.parent, children)
    }
  }
  function path(id: string) {
    const result: Region[] = []
    let region = byId.get(id)
    while (region) {
      result.unshift(region)
      region = region.parent ? byId.get(region.parent) : undefined
    }
    return result
  }
  const searchEntries = regions.map((region) => ({
    region,
    text: path(region.id)
      .map((item) => item.name)
      .join(' ')
      .toLowerCase(),
  }))
  function search(query: string) {
    const words = query.trim().toLowerCase().split(/\s+/).filter(Boolean)
    if (!words.length) return []
    return searchEntries
      .filter((item) =>
        words.every(
          (word) => item.text.includes(word) || item.region.id.includes(word),
        ),
      )
      .sort(
        (a, b) =>
          Number(b.region.name === query || b.region.id === query) -
          Number(a.region.name === query || a.region.id === query),
      )
      .map((item) => item.region)
  }
  function target(id: string): RegionTarget {
    if (id === chinaRegion.id) return chinaRegion
    const region = byId.get(id)
    if (!region) throw new Error('地区目录中不存在该代码')
    return {
      id,
      label: path(id)
        .filter((item) => item.level !== 'country')
        .map((item) => item.name)
        .join(' · '),
      longitude: region.longitude,
      latitude: region.latitude,
      range: {
        country: 9_000_000,
        province: 850_000,
        city: 140_000,
        district: 25_000,
      }[region.level],
      pitch: -90,
    }
  }
  return {
    byId,
    children: (id: string) => childMap.get(id) ?? [],
    path,
    search,
    target,
  }
}
export type RegionIndex = ReturnType<typeof createRegionIndex>

export async function resolveRegionTarget(id: string): Promise<RegionTarget> {
  if (id === chinaRegion.id) return chinaRegion
  const campus = [...campusRegions, ...demonstrationRegions].find((region) => region.id === id)
  if (campus) return campus
  const response = await fetch('/data/regions.json')
  if (!response.ok) throw new Error(`地区目录加载失败：HTTP ${response.status}`)
  const catalog: RegionCatalog = await response.json()
  if (!catalog || !Array.isArray(catalog.regions))
    throw new Error('地区目录格式无效')
  return createRegionIndex(catalog.regions).target(id)
}
import { campuses, defaultCampus, type CampusKey } from './campuses.ts'
