import { test } from 'node:test'
import assert from 'node:assert/strict'
import { simulationGeometry } from '../src/simulationGeometry.ts'

const network = { nodes: [{ id: 'S', coordinates: [113, 23] }, { id: 'A', coordinates: [114, 23] }, { id: 'T', coordinates: [114, 24] }],
  edges: [{ id: 'S-A', source: 'S', target: 'A' }, { id: 'A-T', source: 'A', target: 'T' }] }

test('overlay retains exact server path order, formal edge IDs and semantic colors', () => {
  const geometry = simulationGeometry(network, ['A-T'], {
    baseline: { reachable: true, path: ['S', 'A', 'T'] }, blocked: { reachable: true, path: ['T', 'A', 'S'] },
  })
  assert.deepEqual(geometry.paths.map(path => [path.role, path.color]), [['baseline', '#2563eb'], ['blocked', '#f59e0b']])
  assert.deepEqual(geometry.paths[0].coordinates, [[113, 23], [114, 23], [114, 24]])
  assert.deepEqual(geometry.paths[1].edgeIds, ['A-T', 'S-A'])
  assert.equal(geometry.edges.find(edge => edge.id === 'A-T').blocked, true)
  assert.deepEqual(geometry.edges.find(edge => edge.id === 'A-T').midpoint, [114, 23.5])
})

test('unreachable has no drawn route while identical endpoints retain their single point', () => {
  const geometry = simulationGeometry(network, [], { baseline: { reachable: false, path: [] }, blocked: { reachable: true, path: ['S'] } })
  assert.equal(geometry.paths.length, 1)
  assert.deepEqual(geometry.paths[0].coordinates, [[113, 23]])
  assert.deepEqual(geometry.paths[0].edgeIds, [])
  assert.throws(() => simulationGeometry(network, [], { baseline: { reachable: true, path: ['missing'] } }), /不存在/)
})
