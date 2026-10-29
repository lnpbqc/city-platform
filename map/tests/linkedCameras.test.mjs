import { test } from 'node:test'
import assert from 'node:assert/strict'
import { linkedCameras, matchingCameras } from '../src/linkedCameras.ts'

const initial = { longitude: 113, latitude: 23, height: 900, heading: 0.2, pitch: -0.9, roll: 0, scene_mode: '3d' }
test('camera linking synchronizes either side once and prevents synchronous or delayed feedback', () => {
  let leftCamera = { ...initial }, rightCamera = { ...initial }, changes
  const calls = []
  const left = { getCamera: () => leftCamera, setCamera: value => { leftCamera = value; calls.push('left'); changes('left', value) } }
  const right = { getCamera: () => rightCamera, setCamera: value => { rightCamera = value; calls.push('right'); changes('right', value) } }
  changes = linkedCameras(() => left, () => right)
  changes('left', initial)
  assert.deepEqual(calls, [])
  leftCamera = { ...initial, longitude: 114, height: 1000 }
  changes('left', leftCamera)
  assert.deepEqual(rightCamera, leftCamera)
  assert.deepEqual(calls, ['right'])
  changes('right', { ...rightCamera, heading: rightCamera.heading + Math.PI * 2 })
  assert.deepEqual(calls, ['right'], 'angle wrapping must not start a feedback loop')
  rightCamera = { ...rightCamera, latitude: 24, scene_mode: '2d' }
  changes('right', rightCamera)
  assert.deepEqual(leftCamera, rightCamera)
  assert.deepEqual(calls, ['right', 'left'])
})
test('detached comparison is ignored and meaningful camera differences are retained', () => {
  const sync = linkedCameras(() => undefined, () => undefined)
  assert.doesNotThrow(() => sync('left', initial))
  assert.equal(matchingCameras(initial, { ...initial, height: 900.001 }), true)
  assert.equal(matchingCameras(initial, { ...initial, height: 901 }), false)
  assert.equal(matchingCameras({ ...initial, longitude: -180 }, { ...initial, longitude: 180 }), true)
  assert.equal(matchingCameras(initial, { ...initial, scene_mode: '2d' }), false)
})
