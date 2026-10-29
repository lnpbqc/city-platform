import type { MapLayer } from './types'

export function layerDownload(layer: MapLayer) {
  const filename = `${layer.name.replace(/[\\/:*?"<>|\u0000-\u001f]/g, '_') || '图层'}.${layer.type === '3dtiles' ? 'zip' : 'geojson'}`
  const source = new URL(layer.url, 'http://127.0.0.1:5173')
  const managed = source.pathname.startsWith('/data-files/') &&
    ['localhost', '127.0.0.1', '[::1]'].includes(source.hostname) &&
    ['8000', '5173', '4173'].includes(source.port)
  if (layer.asset_id && managed)
    return {
      url: `/api/assets/${encodeURIComponent(layer.asset_id)}/download`,
      filename,
      label: layer.type === '3dtiles' ? '下载完整 ZIP' : '下载 GeoJSON',
      external: false,
    }
  if (layer.type === 'geojson')
    return { url: layer.url, filename, label: '下载 GeoJSON', external: false }
  if (layer.builtin && layer.id === 'demo-buildings')
    return {
      url: layer.url.replace(/buildings\/tileset\.json$/, 'buildings-demo.zip'),
      filename,
      label: '下载完整 ZIP',
      external: false,
    }
  return { url: layer.url, filename, label: '打开数据源', external: true }
}

export async function fetchLayerDownload(url: string) {
  const response = await fetch(url)
  if (!response.ok) {
    let message = `下载失败 (${response.status})`
    try {
      const body = await response.json()
      if (typeof body.detail === 'string') message = body.detail
    } catch {
      // A disconnected proxy may return plain text.
    }
    throw new Error(message)
  }
  return response.blob()
}
