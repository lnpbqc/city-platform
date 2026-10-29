import type { GeometryDocument } from './types'

export type TimeResolution = 'hour' | 'day'
export interface TemporalContext { time: string; resolution: TimeResolution }
export interface ObjectTemporal extends TemporalContext { unit: string; value: number | null; missing: boolean }
export interface TimeSeriesRecord extends TemporalContext {
  layer_id: string
  asset: { asset_id: string; version: string }
  unit: string
  items: { object_id: string; geometry: GeometryDocument | null; value: number | null; missing: boolean }[]
}
export interface TimeLayerQuery { asset_id?: string; version?: string; campus?: string }
export interface TimeSeriesQuery extends TimeLayerQuery, TemporalContext { layer_id: string; bbox?: string }
