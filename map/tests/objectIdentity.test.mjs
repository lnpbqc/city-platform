import { test } from 'node:test'
import assert from 'node:assert/strict'
import { objectIdentity, identifyFeatures } from '../src/objectIdentity.ts'

test('object identity agrees with Python uuid5 including Unicode and model ordinal', async () => {
  assert.equal(await objectIdentity('asset-one', '1.0.0', 0), '2f3982d2-41e0-519a-ad92-23346a334ed2')
  assert.notEqual(await objectIdentity('asset-one', '1.0.0', 0), await objectIdentity('asset-one', '2.0.0', 0))
  assert.equal(await objectIdentity('中文资产', '1.0.0', -1), '99b589f1-d993-5cbc-8460-5f218efbd739')
})

test('feature identity preserves source ids and nested attributes, returning ids in backend rank order', async () => {
  const original = { type: 'FeatureCollection', name: '样例', features: [
    { type: 'Feature', id: 'osm-1', geometry: { type: 'Point', coordinates: [113, 23] }, properties: { id: 'business-id', nested: { value: null } } },
    { type: 'Feature', id: 42, geometry: null, properties: null },
  ] }
  const before = structuredClone(original)
  const result = await identifyFeatures(original, 'asset-one', '1.0.0')
  assert.deepEqual(original, before)
  const expected = await Promise.all([0, 1].map(index => objectIdentity('asset-one', '1.0.0', index)))
  assert.deepEqual(result.data.features.map(feature => feature.id), expected)
  assert.deepEqual(result.ids, [...expected].sort())
  assert.deepEqual(result.data.features[0].properties, before.features[0].properties)
  result.data.features[0].properties.nested.value = 7
  assert.equal(original.features[0].properties.nested.value, null)
})

test('unsupported bare geometry retains its document without inventing indexed objects', async () => {
  const original = { type: 'Point', coordinates: [113, 23] }
  assert.deepEqual(await identifyFeatures(original, 'asset-one', '1.0.0'), { data: original, ids: [] })
})
