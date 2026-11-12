import type { RegionTarget } from './regions'

export interface CameraState {
  longitude: number
  latitude: number
  height: number
  heading: number
  pitch: number
  roll: number
  scene_mode: '2d' | '3d'
}
export interface MapView { camera: CameraState; region: RegionTarget }
export interface NavigationReading {
  camera: CameraState
  pointer: { longitude: number; latitude: number; height: number } | null
  scale: { label: string; pixels: number } | null
}
const storageKey = 'city.map.view.v1'
const finite = (value: unknown): value is number => typeof value === 'number' && Number.isFinite(value)
export function validCamera(value: unknown): value is CameraState {
  if (!value || typeof value !== 'object') return false
  const camera = value as CameraState
  return [camera.longitude, camera.latitude, camera.height, camera.heading, camera.pitch, camera.roll].every(finite)
    && Math.abs(camera.longitude) <= 180 && Math.abs(camera.latitude) <= 90
    && (camera.scene_mode === '2d' || camera.scene_mode === '3d')
}
export function readMapView(storage: Pick<Storage, 'getItem'>): MapView | null {
  try {
    const view = JSON.parse(storage.getItem(storageKey) || 'null') as MapView | null
    const region = view?.region
    if (!validCamera(view?.camera) || !region || typeof region.id !== 'string' || typeof region.label !== 'string'
      || ![region.longitude, region.latitude, region.range, region.pitch].every(finite)
      || Math.abs(region.longitude) > 180 || Math.abs(region.latitude) > 90 || region.range <= 0
      || region.pitch < -90 || region.pitch > 0
      || (region.sampleKey !== undefined && !['university-town', 'huangpu'].includes(region.sampleKey))) return null
    return view
  } catch { return null }
}
export function saveMapView(storage: Pick<Storage, 'setItem'>, view: MapView) {
  try { storage.setItem(storageKey, JSON.stringify(view)); return true } catch { return false }
}
export function scaleForDistance(distance: number, width = 100) {
  if (!finite(distance) || distance <= 0) return null
  const magnitude = 10 ** Math.floor(Math.log10(distance))
  const length = [5, 2, 1].find(value => value * magnitude <= distance)! * magnitude
  return { label: length >= 1000 ? `${length / 1000} km` : `${Number(length.toPrecision(3))} m`, pixels: length / distance * width }
}
