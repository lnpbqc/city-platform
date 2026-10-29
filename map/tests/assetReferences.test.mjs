import { test } from 'node:test'
import assert from 'node:assert/strict'
import { canRegisterAsset, referenceType, referenceVersion, referenceGuidance } from '../src/assetReferences.ts'

const asset = { status: 'active', type: 'geojson', entry_url: '/data-files/id/data.geojson', references: [] }

test('scene and history references permit registration while a layer reference keeps the existing entry', () => {
  for (const type of ['scene', 'run']) {
    assert.equal(canRegisterAsset({ ...asset, reference_count: 1, references: [{ type, id: type, name: type, version: 2, asset_version: '1.0.0' }] }), true)
  }
  assert.equal(canRegisterAsset({ ...asset, references: [{ id: 'layer', name: 'legacy layer' }] }), false)
  assert.equal(canRegisterAsset({ ...asset, references: [{ type: 'layer', id: 'layer', name: 'layer' }] }), false)
  assert.equal(canRegisterAsset({ ...asset, status: 'missing' }), false)
  assert.equal(canRegisterAsset({ ...asset, type: 'unknown' }), false)
  assert.equal(canRegisterAsset({ ...asset, entry_url: null }), false)
})

test('reference labels and guidance identify the owner and pinned version', () => {
  const layer = { id: 'layer', name: 'old layer' }
  const scene = { type: 'scene', id: 'scene', name: 'scene', version: 3, asset_version: '1.0.0' }
  const run = { ...scene, type: 'run', id: 'run' }
  assert.equal(referenceType(layer), '图层登记')
  assert.equal(referenceVersion(layer), '')
  assert.equal(referenceType(scene), '场景')
  assert.equal(referenceVersion(scene), '场景版本 3 · 资产版本 1.0.0')
  assert.equal(referenceType(run), '历史运行')
  assert.equal(referenceVersion(run), '快照场景版本 3 · 资产版本 1.0.0')
  assert.match(referenceGuidance(layer), /图层登记/)
  assert.match(referenceGuidance(scene), /场景.*移除.*图层/)
  assert.match(referenceGuidance(run), /持续保护/)
  assert.doesNotMatch(referenceGuidance(run), /删除运行/)
})
