import { test } from 'node:test'
import assert from 'node:assert/strict'
import { layerGroups, moveTarget, objectCountLabel } from '../src/layerTree.ts'

const layers = [
  { id: 'basemap', category: '底图', attached: true, order: 0, orderable: false, object_count: 0 },
  { id: 'building', category: '建筑', name: '校园', attached: true, order: 1, orderable: false, object_count: 135 },
  { id: 'points', category: '专题', name: '点', attached: true, order: 2, orderable: true, object_count: 3 },
  { id: 'roads', category: '道路', name: '路', attached: true, order: 3, orderable: true, object_count: 2 },
  { id: 'areas', category: '专题', name: '面', attached: true, order: 4, orderable: true, object_count: null },
]
test('fixed six groups include empty categories and preserve directory order within groups', () => {
  const groups = layerGroups([...layers].reverse())
  assert.deepEqual(groups.map(group => group.category), ['底图', '建筑', '道路', '水体', '专题', '仿真结果'])
  assert.deepEqual(groups[4].layers.map(layer => layer.id), ['points', 'areas'])
  assert.deepEqual(groups[3].layers, [])
})
test('order controls skip non-orderable and detached layers and use the complete directory index', () => {
  const source = [...layers, { id: 'detached', attached: false, order: 5, orderable: true }]
  assert.equal(moveTarget(source, layers[2], -1), null)
  assert.equal(moveTarget(source, layers[2], 1), 3)
  assert.equal(moveTarget(source, layers[4], 1), null)
  assert.equal(moveTarget(source, layers[1], 1), null)
  assert.equal(moveTarget([...source, { id: 'new-registration', attached: false }], layers[2], 1), null, 'wait for directory metadata instead of inventing order 0')
})
test('unknown and model resource counts are explicit and real zero is retained', () => {
  assert.equal(objectCountLabel(layers[4]), '对象数未知')
  assert.equal(objectCountLabel(layers[0]), '0 个对象')
  assert.equal(objectCountLabel({ type: '3dtiles', object_count: 1 }), '1 个模型资源')
})
