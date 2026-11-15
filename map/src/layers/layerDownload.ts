import type { MapLayer } from './types'

const safeFileName = (value: string) => value.replace(/[\\/:*?"<>|\u0000-\u001f]/g, '_') || '图层'

export function tilesZipTarget(id: string, version: string, name: string, calibrated = false, revision?: number) {
  return {
    url: `/api/assets/${encodeURIComponent(id)}/versions/${encodeURIComponent(version)}/download${revision === undefined ? '' : `?revision=${revision}`}`,
    filename: `${safeFileName(name.replace(/\.zip$/i, ''))}.zip`,
    label: calibrated ? '下载校准后的 ZIP' : '下载完整 ZIP',
    external: false,
    native: true,
  }
}

export function layerDownload(layer: MapLayer) {
  const filename = `${safeFileName(layer.name)}.${layer.type === '3dtiles' ? 'zip' : 'geojson'}`
  if (layer.type === 'geojson' && layer.asset_id && layer.asset_version && layer.render?.source_state === 'expired')
    return { url: `/api/assets/${encodeURIComponent(layer.asset_id)}/versions/${encodeURIComponent(layer.asset_version)}/geojson`,
      filename, label: '原文件已到期，导出 GeoJSON', external: false }
  const source = new URL(layer.url, 'http://127.0.0.1:5173')
  const managed = source.pathname.startsWith('/data-files/') &&
    ['localhost', '127.0.0.1', '[::1]'].includes(source.hostname) &&
    ['8000', '5173', '4173'].includes(source.port)
  if (layer.type === '3dtiles' && layer.asset_id && layer.asset_version && (layer.tiles_calibrated || managed))
    return tilesZipTarget(layer.asset_id, layer.asset_version, layer.name, layer.tiles_calibrated, layer.tiles_revision)
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

export async function startTilesZipDownload({ url, filename }: {url: string; filename: string}) {
  const response = await fetch(url, { method: 'HEAD' })
  if (!response.ok) {
    const detail = response.headers.get('X-Download-Error')
    throw new Error(detail ? decodeURIComponent(detail) : `模型 ZIP 暂不可下载（HTTP ${response.status}）`)
  }
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = filename
  document.body.append(anchor)
  anchor.click()
  anchor.remove()
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
