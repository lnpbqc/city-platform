import { test } from 'node:test'
import assert from 'node:assert/strict'
import { createRenderer, defineComponent, nextTick, shallowRef } from 'vue'
import { useReplay } from '../src/composables/useReplay.ts'

const renderer = createRenderer({ createElement: () => ({}), createText: () => ({}), createComment: () => ({}), insert() {}, remove() {}, setText() {}, setElementText() {}, patchProp() {}, parentNode: () => null, nextSibling: () => null })
function setup(t) {
  let clock = 1000, identity = 0, replay
  const frames = new Map()
  const previous = { request: globalThis.requestAnimationFrame, cancel: globalThis.cancelAnimationFrame }
  globalThis.requestAnimationFrame = callback => { const id = ++identity; frames.set(id, callback); return id }
  globalThis.cancelAnimationFrame = id => frames.delete(id)
  t.mock.method(performance, 'now', () => clock)
  t.after(() => { globalThis.requestAnimationFrame = previous.request; globalThis.cancelAnimationFrame = previous.cancel })
  const timeline = shallowRef({ duration: 80, ticks: [0, 20, 80], baseline: { duration: 80, coordinates: [[113, 23], [114, 23], [115, 23]], times: [0, 20, 80] }, blocked: null })
  const app = renderer.createApp(defineComponent({ setup() { replay = useReplay(() => timeline.value); return () => null } }))
  app.mount({})
  t.after(() => app.unmount())
  const advance = milliseconds => { clock += milliseconds; const callbacks = [...frames.values()]; frames.clear(); callbacks.forEach(callback => callback(clock)) }
  return { replay, frames, advance, app, timeline }
}

test('play uses one frame, scales elapsed time, pauses, seeks, steps and resets', t => {
  const { replay, frames, advance } = setup(t)
  replay.play(); replay.play()
  assert.equal(frames.size, 1)
  advance(1000)
  assert.equal(replay.seconds.value, 1)
  replay.rate.value = 4
  advance(500)
  assert.equal(replay.seconds.value, 3)
  replay.pause(); advance(1000)
  assert.equal(replay.seconds.value, 3)
  assert.equal(frames.size, 0)
  replay.seek(30)
  replay.step(-1)
  assert.equal(replay.seconds.value, 20)
  replay.step(1)
  assert.equal(replay.seconds.value, 80)
  assert.deepEqual(replay.positions.value.baseline, [115, 23])
  replay.play(); advance(250)
  assert.equal(replay.seconds.value, 1, 'playing again from the end starts a new replay')
  replay.reset()
  assert.equal(replay.seconds.value, 0)
  assert.equal(frames.size, 0)
})

test('arrival stops the clock; a new result and unmount release scheduled work', async t => {
  const { replay, frames, advance, timeline, app } = setup(t)
  replay.seek(79); replay.play(); advance(2000)
  assert.equal(replay.seconds.value, 80)
  assert.equal(replay.playing.value, false)
  assert.equal(frames.size, 0)
  replay.reset(); replay.play()
  timeline.value = { duration: 0, ticks: [0], baseline: { duration: 0, coordinates: [[113, 23]], times: [0] }, blocked: null }
  await nextTick()
  assert.equal(replay.seconds.value, 0)
  assert.equal(replay.playing.value, false)
  assert.deepEqual(replay.positions.value, { baseline: [113, 23], blocked: null })
  replay.play()
  assert.equal(frames.size, 0)
  timeline.value = { ...timeline.value, duration: 10 }
  await nextTick()
  replay.play()
  app.unmount()
  assert.equal(frames.size, 0)
})
