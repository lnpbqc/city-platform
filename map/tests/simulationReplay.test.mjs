import { test } from 'node:test'
import assert from 'node:assert/strict'
import { replayTimeline, replayPosition, replayStep } from '../src/simulationReplay.ts'

const network = { nodes: [{ id: 'S', coordinates: [113, 23] }, { id: 'A', coordinates: [113.002, 23] }, { id: 'T', coordinates: [113.004, 23.002] }],
  edges: [{ id: 'S-A', source: 'S', target: 'A', length_m: 200, speed_mps: 10 },
    { id: 'A-T', source: 'A', target: 'T', length_m: 300, speed_mps: 5 }] }
const path = (ids, duration_s, reachable = true) => ({ path: ids, duration_s, reachable })
const closePosition = (actual, expected) => {
  assert.equal(actual.length, expected.length)
  actual.forEach((value, index) => assert.ok(Math.abs(value - expected[index]) < 1e-10))
}

test('replay uses per-edge travel time and synchronized routes, retaining the finished vehicle', () => {
  const timeline = replayTimeline(network, { baseline: path(['S', 'A', 'T'], 80), blocked: path(['T', 'A', 'S'], 80) })
  assert.equal(timeline.duration, 80)
  assert.deepEqual(timeline.ticks, [0, 20, 60, 80])
  assert.deepEqual(replayPosition(timeline.baseline, 10), [113.001, 23])
  assert.deepEqual(replayPosition(timeline.baseline, 20), [113.002, 23])
  closePosition(replayPosition(timeline.baseline, 50), [113.003, 23.001])
  closePosition(replayPosition(timeline.blocked, 30), [113.003, 23.001])
  assert.deepEqual(replayPosition(timeline.baseline, 100), [113.004, 23.002])
  assert.equal(replayStep(timeline.ticks, 20, 1), 60)
  assert.equal(replayStep(timeline.ticks, 35, -1), 20)
  assert.equal(replayStep(timeline.ticks, 0, -1), 0)
  assert.equal(replayStep(timeline.ticks, 80, 1), 80)
})

test('different route durations share one clock; unreachable and single-node paths remain explicit', () => {
  const timeline = replayTimeline(network, { baseline: path(['S', 'A'], 20), blocked: path(['S', 'A', 'T'], 80) })
  assert.deepEqual(replayPosition(timeline.baseline, 50), [113.002, 23])
  closePosition(replayPosition(timeline.blocked, 50), [113.003, 23.001])
  const unavailable = replayTimeline(network, { baseline: path([], null, false), blocked: path(['S'], 0) })
  assert.equal(unavailable.duration, 0)
  assert.deepEqual(unavailable.ticks, [0])
  assert.equal(replayPosition(unavailable.baseline, 0), null)
  assert.deepEqual(replayPosition(unavailable.blocked, 100), [113, 23])
})

test('interpolation preserves high coordinates and crosses the date line along its short span', () => {
  const value = { nodes: [{ id: 'S', coordinates: [179, 10, 4] }, { id: 'T', coordinates: [-179, 12, 8] }],
    edges: [{ id: 'S-T', source: 'S', target: 'T', length_m: 10, speed_mps: 1 }] }
  const timeline = replayTimeline(value, { baseline: path(['S', 'T'], 10), blocked: path([], null, false) })
  assert.deepEqual(replayPosition(timeline.baseline, 5), [-180, 11, 6])
  assert.throws(() => replayTimeline(network, { baseline: path(['S', 'missing'], 10) }), /节点不存在/)
  assert.throws(() => replayTimeline(network, { baseline: path(['S', 'T'], 10) }), /边不存在/)
})
