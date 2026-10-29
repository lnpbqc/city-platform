import type { CameraState } from './mapNavigation'

export interface AssetVersionRef { asset_id: string; version: string }
export interface SceneLayerState {
  layer_id: string
  asset: AssetVersionRef | null
  map_attached: boolean
  map_visible: boolean
  map_opacity: number
  order: number
}
export interface SceneInput {
  name: string
  camera: CameraState
  layers: SceneLayerState[]
  network: AssetVersionRef | null
  origin: string | null
  destination: string | null
  blocked_edges: string[]
  params: { mode: 'car' }
  seed: number
  current_time: string | null
  run_id: string | null
}
export interface SceneRecord extends SceneInput {
  id: string
  version: number
  created_at: string
  updated_at: string
}
export interface NetworkRecord extends AssetVersionRef {
  name: string
  directed: false
  crs: string
  synthetic: boolean
  nodes: { id: string; coordinates: number[] }[]
  edges: { id: string; source: string; target: string; length_m: number; speed_mps: number }[]
}
export interface RunInput {
  scene_id: string
  network: AssetVersionRef
  origin: string
  destination: string
  blocked_edges: string[]
  params: { mode: 'car' }
  seed: number
}
export interface RunRecord {
  run_id: string
  status: 'queued' | 'running' | 'succeeded' | 'failed' | 'cancelled'
  inputs_sha256: string
  model_version: string
  data_version: string
  scene_id: string
  scene_version: number
  submitted_at: string
  started_at: string | null
  finished_at: string | null
  elapsed_ms: number | null
  error: { code: string; message: string; detail: unknown; trace_id: string } | null
  trace_id: string
}
export interface PathResult {
  path: string[]
  length_m: number | null
  duration_s: number | null
  reachable: boolean
}
export interface RunResult {
  run_id: string
  baseline: PathResult
  blocked: PathResult
  metrics: { increase_percent: number | null; rerouted: boolean }
  created_at: string
}
export interface RunSnapshot {
  request: RunInput
  scene: SceneRecord
  model_version: string
  data_version: string
}
export interface RunQuery {
  page?: number
  page_size?: number
  scene_id?: string
  status?: RunRecord['status'] | ''
  from?: string
  to?: string
}
