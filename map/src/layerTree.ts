import type { MapLayer } from './types'

const categories = ['底图', '建筑', '道路', '水体', '专题', '仿真结果']
export function orderedLayers(layers: MapLayer[]) {
  return [...layers].sort((left, right) => (left.order ?? 0) - (right.order ?? 0) || left.id.localeCompare(right.id))
}
export function layerGroups(layers: MapLayer[]) {
  const aliases: Record<string, string> = { 三维建筑: '建筑', 三维模型: '建筑', 线状网络: '道路' }
  const group = (layer: MapLayer) => categories.includes(layer.category) ? layer.category : aliases[layer.category] ?? '专题'
  const ordered = orderedLayers(layers)
  return categories.map(category => ({ category, layers: ordered.filter(layer => group(layer) === category) }))
}
export function moveTarget(layers: MapLayer[], layer: MapLayer, direction: number) {
  if (!layer.orderable || !layer.attached || layers.some(item => item.order == null)) return null
  const ordered = orderedLayers(layers)
  const candidates = ordered.filter(item => item.orderable && item.attached)
  const index = candidates.findIndex(item => item.id === layer.id)
  if (index < 0) return null
  const neighbor = candidates[index + (direction < 0 ? -1 : 1)]
  return neighbor ? ordered.findIndex(item => item.id === neighbor.id) : null
}
export function objectCountLabel(layer: Pick<MapLayer, 'object_count' | 'type'>) {
  return layer.object_count == null ? '对象数未知' : `${layer.object_count.toLocaleString()} 个${layer.type === '3dtiles' ? '模型资源' : '对象'}`
}
