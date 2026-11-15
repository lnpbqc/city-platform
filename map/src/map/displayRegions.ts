import type { CameraState } from './mapNavigation.ts'
import type { WeatherPoint } from './weather.ts'

export interface DisplayRegionExtent extends WeatherPoint {
  radius_m: number
}

export interface DisplayRegionView extends DisplayRegionExtent {
  camera: CameraState
}

export interface DisplayRegion extends DisplayRegionView {
  id: string
  name: string
}

export function matchDisplayRegion(center: WeatherPoint | null, regions: readonly DisplayRegion[]) {
  if (!center) return null
  const radians = Math.PI / 180
  const latitude = center.latitude * radians
  let nearest: DisplayRegion | null = null
  let best = Infinity
  for (const region of regions) {
    const deltaLat = Math.sin((region.latitude - center.latitude) * radians / 2)
    const deltaLon = Math.sin((region.longitude - center.longitude) * radians / 2)
    const a = deltaLat ** 2 + Math.cos(latitude) * Math.cos(region.latitude * radians) * deltaLon ** 2
    const distance = 12_742_000 * Math.asin(Math.sqrt(Math.min(1, a)))
    if (distance <= region.radius_m && (!nearest || distance < best || (distance === best && region.id < nearest.id))) {
      nearest = region
      best = distance
    }
  }
  return nearest
}
