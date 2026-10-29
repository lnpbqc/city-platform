import { ApiError } from './api.ts'
import { publishApiEvent } from './apiEvents.ts'
import { validCamera, type CameraState } from './mapNavigation.ts'
import { localTime } from './temporal.ts'
import type { SceneInput } from './simulationTypes'
import type { TemporalContext, TimeResolution } from './temporalTypes'

export interface WorkspaceState {
  page: 'map' | 'simulation'
  scene_id: string
  scene_version: number
  run_id: string | null
  time: string | null
  resolution: TimeResolution
  camera: CameraState
  comparison: TemporalContext | null
}
export interface WorkspaceCapture extends Omit<WorkspaceState, 'scene_id' | 'scene_version'> { scene: SceneInput }
export interface WorkspaceAddress {
  page: WorkspaceState['page']
  scene_id?: string
  scene_version?: number
  run_id?: string
  time?: string
  resolution: TimeResolution
  camera?: CameraState
  comparison: TemporalContext | null
}
export const workspaceParams = ['scene', 'v', 'run', 't', 'resolution', 'camera', 'compare_t', 'compare_resolution']
export const workspaceError = (message: string) => {
  const error = new ApiError(message, 400, null, 'INVALID_WORKSPACE_LINK', `client-${crypto.randomUUID()}`)
  publishApiEvent({ error })
  return error
}

function parseTime(value: string) {
  const match = value.match(/^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})(?::(\d{2})(\.\d{1,3})?)?(Z|[+-]\d{2}:\d{2})?$/)
  if (!match) throw workspaceError('链接时间需要完整日期和时分；无时区按北京时间解释')
  const [, year, month, day, hour, minute, second, fraction, zone] = match
  const date = new Date(Date.UTC(Number(year), Number(month) - 1, Number(day)))
  if (date.getUTCFullYear() !== Number(year) || date.getUTCMonth() + 1 !== Number(month) || date.getUTCDate() !== Number(day)
    || Number(hour) > 23 || Number(minute) > 59 || Number(second ?? 0) > 59) throw workspaceError('链接日期或时间无效')
  const instant = zone ? Date.parse(value) : Date.parse(localTime(`${year}-${month}-${day}T${hour}:${minute}:${second ?? '00'}`)) + Number(fraction ?? 0) * 1000
  if (!Number.isFinite(instant)) throw workspaceError('链接时区无效')
  return new Date(instant).toISOString()
}
export function readWorkspaceAddress(url: URL): WorkspaceAddress | null {
  const params = url.searchParams
  if (!workspaceParams.some(key => params.has(key))) return null
  for (const key of workspaceParams) if (params.getAll(key).length > 1) throw workspaceError(`链接参数 ${key} 重复`)
  const identity = (key: string) => {
    const value = params.get(key)
    if (value === null) return undefined
    if (!value.trim() || value !== value.trim() || value.length > 120) throw workspaceError(`链接参数 ${key} 无效`)
    return value
  }
  const scene_id = identity('scene'), run_id = identity('run'), version = identity('v')
  if (version && (!/^[1-9]\d*$/.test(version) || !Number.isSafeInteger(Number(version)) || !scene_id)) throw workspaceError('场景版本必须与场景 ID 一同提供，且为正整数')
  const resolution = (key: string): TimeResolution => {
    const value = params.get(key) ?? 'hour'
    if (value !== 'hour' && value !== 'day') throw workspaceError(`链接参数 ${key} 仅支持 hour 或 day`)
    return value
  }
  let camera: CameraState | undefined
  if (params.has('camera')) {
    try { camera = JSON.parse(params.get('camera')!) } catch { throw workspaceError('链接相机参数无效') }
    if (!validCamera(camera)) throw workspaceError('链接相机参数无效')
  }
  const page = run_id || url.hash === '#/simulation' ? 'simulation' : 'map'
  if (params.has('compare_resolution') && !params.has('compare_t')) throw workspaceError('右侧分辨率需要同时提供右侧时间')
  const comparison = params.has('compare_t') ? { time: parseTime(params.get('compare_t')!), resolution: resolution('compare_resolution') } : null
  if (comparison && page !== 'map') throw workspaceError('双视图时间仅用于地图工作台')
  return { page, scene_id, scene_version: version ? Number(version) : undefined, run_id,
    time: params.has('t') ? parseTime(params.get('t')!) : undefined, resolution: resolution('resolution'), camera, comparison }
}
export function workspaceURL(state: WorkspaceState, base = window.location.href) {
  const url = new URL(base)
  for (const key of workspaceParams) url.searchParams.delete(key)
  url.searchParams.set('scene', state.scene_id)
  url.searchParams.set('v', String(state.scene_version))
  if (state.run_id) url.searchParams.set('run', state.run_id)
  if (state.time) url.searchParams.set('t', state.time)
  url.searchParams.set('resolution', state.resolution)
  url.searchParams.set('camera', JSON.stringify(state.camera))
  if (state.comparison) {
    url.searchParams.set('compare_t', state.comparison.time)
    url.searchParams.set('compare_resolution', state.comparison.resolution)
  }
  url.hash = `/${state.page}`
  return url.href
}
