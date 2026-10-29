import { test } from 'node:test'
import assert from 'node:assert/strict'
import { createRenderer, defineComponent, nextTick, shallowRef } from 'vue'
import { dayTime, localDay, localTime, normalizedTime, temporalColor, timeLabel } from '../src/temporal.ts'
import { useTimeAxis } from '../src/composables/useTimeAxis.ts'

test('Shanghai calendar conversion preserves day boundaries, historical DST and actual zero', () => {
  assert.equal(localTime('2026-10-25T08:00'), '2026-10-25T00:00:00.000Z')
  assert.equal(dayTime(localDay('2026-10-25T16:30:00Z')), '2026-10-25T16:00:00.000Z')
  assert.equal(normalizedTime('2026-10-25T08:30:00+08:00', 'hour'), '2026-10-25T00:30:00.000Z')
  assert.equal(localTime('1988-08-01T08:00'), '1988-07-31T23:00:00.000Z')
  assert.equal(timeLabel('1988-07-31T23:00:00Z'), '1988-08-01 08:00:00')
  assert.equal(temporalColor(0, 'cm'), '#dbeafe')
  assert.equal(temporalColor(10, 'cm'), '#93c5fd')
  assert.equal(temporalColor(11, 'cm'), '#3b82f6')
  assert.equal(temporalColor(31, 'cm'), '#1d4ed8')
  assert.equal(temporalColor(100, '辆/小时'), '#93c5fd')
})

const renderer = createRenderer({ createElement: () => ({}), createText: () => ({}), createComment: () => ({}), insert() {}, remove() {}, setText() {}, setElementText() {}, patchProp() {}, parentNode: () => null, nextSibling: () => null })
test('time axis includes uncovered hours, scales playback, switches to daily and releases frames', async t => {
  let axis, now = 0, identity = 0
  const frames = new Map()
  const previous = { request: globalThis.requestAnimationFrame, cancel: globalThis.cancelAnimationFrame }
  globalThis.requestAnimationFrame = callback => { const id = ++identity; frames.set(id, callback); return id }
  globalThis.cancelAnimationFrame = id => frames.delete(id)
  t.after(() => { globalThis.requestAnimationFrame = previous.request; globalThis.cancelAnimationFrame = previous.cancel })
  t.mock.method(performance, 'now', () => now)
  const times = shallowRef(['2026-10-25T00:00:00Z', '2026-10-25T01:00:00Z', '2026-10-26T00:00:00Z', '2026-10-26T01:00:00Z'])
  const app = renderer.createApp(defineComponent({ setup() { axis = useTimeAxis(() => times.value); return () => null } }))
  app.mount({})
  t.after(() => app.unmount())
  const advance = milliseconds => { now += milliseconds; const callbacks = [...frames.values()]; frames.clear(); callbacks.forEach(callback => callback(now)) }
  assert.equal(axis.maximum.value, 25)
  assert.equal(axis.time.value, '2026-10-25T00:00:00.000Z')
  axis.seek(2)
  assert.equal(axis.time.value, '2026-10-25T02:00:00.000Z', 'uncovered hours remain selectable')
  axis.play(); axis.play()
  assert.equal(frames.size, 1)
  advance(1000)
  assert.equal(axis.position.value, 3)
  axis.rate.value = 5
  advance(1000)
  assert.equal(axis.position.value, 8)
  axis.pause(); advance(1000)
  assert.equal(axis.position.value, 8)
  axis.resolution.value = 'day'; await nextTick()
  assert.equal(axis.time.value, '2026-10-24T16:00:00.000Z')
  assert.equal(axis.maximum.value, 1)
  axis.step(1)
  assert.equal(axis.time.value, '2026-10-25T16:00:00.000Z')
  axis.play(); advance(1000)
  assert.equal(axis.playing.value, false)
  assert.equal(frames.size, 0)
  axis.resolution.value = 'hour'; await nextTick()
  axis.seek(0); axis.play()
  app.unmount()
  assert.equal(frames.size, 0)
})
