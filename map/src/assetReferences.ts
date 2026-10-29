import type { AssetRecord, AssetReference } from './types'

export function referenceType(reference: AssetReference) {
  return reference.type === 'run' ? '历史运行' : reference.type === 'scene' ? '场景' : '图层登记'
}

export function referenceVersion(reference: AssetReference) {
  if (reference.type !== 'scene' && reference.type !== 'run') return ''
  return `${reference.type === 'run' ? '快照场景版本' : '场景版本'} ${reference.version} · 资产版本 ${reference.asset_version}`
}

export function referenceGuidance(reference: AssetReference) {
  if (reference.type === 'run') return '历史运行持续保护此版本；移除图层或删除场景后，该引用仍保留。'
  if (reference.type === 'scene') return '在场景中移除此资产对应图层并保存，或删除该场景。'
  return '在“图层登记”中修改数据地址或删除该登记。'
}

export function canRegisterAsset(asset: AssetRecord) {
  return asset.status === 'active' &&
    !asset.references.some(reference => !reference.type || reference.type === 'layer') &&
    (asset.type === 'geojson' || asset.type === '3dtiles') && !!asset.entry_url
}
