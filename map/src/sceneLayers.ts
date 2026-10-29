import { ApiError, getAssetVersion, getLayerTimes, getObjects } from './api.ts'
import { mapLayer, type MapLayer } from './types.ts'
import type { SceneLayerState } from './simulationTypes'

export const captureLayers = (layers: MapLayer[]): SceneLayerState[] => layers.map((layer, index) => ({
  layer_id: layer.id,
  asset: layer.asset_id && layer.asset_version ? { asset_id: layer.asset_id, version: layer.asset_version } : null,
  map_attached: layer.map_attached ?? layer.attached, map_visible: layer.visible, map_opacity: layer.opacity, order: layer.order ?? index,
}))

export async function prepareSceneLayers(states: SceneLayerState[], catalog: MapLayer[], signal?: AbortSignal) {
  return Promise.all(states.map(async state => {
    const asset = state.asset ? await getAssetVersion(state.asset.asset_id, state.asset.version, signal) : null
    if (asset && (asset.status !== 'ready' || !asset.entry_url || !['geojson', '3dtiles'].includes(asset.type)))
      throw new ApiError('场景资产版本不可加载', 409, { asset: state.asset, status: asset.status }, 'ASSET_UNAVAILABLE', `client-${crypto.randomUUID()}`)
    if (!asset && state.layer_id !== 'basemap')
      throw new ApiError('场景图层没有固定资产版本', 409, { layer_id: state.layer_id }, 'SCENE_ASSET_UNAVAILABLE', `client-${crypto.randomUUID()}`)
    const metadata = catalog.find(layer => layer.id === state.layer_id
      && (layer.asset_id === asset?.asset_id && layer.asset_version === asset?.version || asset?.source_kind === 'default' && layer.builtin))
    const layer = mapLayer({ id: state.layer_id, name: metadata?.name ?? asset?.name ?? '底图', category: asset ? metadata?.category ?? '专题' : '底图',
      type: asset?.type === '3dtiles' ? '3dtiles' : 'geojson', url: asset?.entry_url ?? '', source: asset?.source ?? '',
      asset_id: asset?.asset_id, asset_version: asset?.version, asset_source_kind: asset?.source_kind,
      map_attached: state.map_attached, map_visible: state.map_visible, map_opacity: state.map_opacity }, asset?.source_kind === 'default' || !asset)
    layer.order = state.order
    if (!asset) layer.object_count = 0
    layer.static = true
    layer.unit = metadata?.unit
    layer.legend = metadata?.legend
    if (asset?.type === 'geojson') {
      const times = await getLayerTimes(layer.id, { asset_id: asset.asset_id, version: asset.version }, signal)
      layer.static = times.length === 0
    }
    if (asset && asset.source_kind !== 'external') {
      try { layer.object_count = (await getObjects({ asset_id: asset.asset_id, version: asset.version, page_size: 1 }, signal)).total }
      catch (cause) { if (!(cause instanceof ApiError && cause.code === 'OBJECT_INDEX_UNAVAILABLE')) throw cause }
    }
    return layer
  }))
}
