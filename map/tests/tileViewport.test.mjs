import { test } from 'node:test'
import assert from 'node:assert/strict'
import { TileViewport } from '../src/map/tileViewport.ts'

function setup(t) {
  const previous = globalThis.Worker
  let worker
  globalThis.Worker = class {
    messages = []
    terminated = false
    constructor() { worker = this }
    postMessage(value) { this.messages.push(structuredClone(value)) }
    terminate() { this.terminated = true }
  }
  const client = new TileViewport()
  t.after(() => {
    client.destroy()
    if (previous === undefined) delete globalThis.Worker
    else globalThis.Worker = previous
  })
  return { client, worker }
}

const render = { status: 'succeeded', url: '/archive', profile: 'roads' }
const view = { bbox: [0,0,1,1], meters_per_pixel: 1, asset_id: 'asset', version: '1' }

test('reactive descriptors and bounds cross the worker boundary as plain values', async t => {
  const { client, worker } = setup(t)
  const reactiveRender = new Proxy(render, {})
  const reactiveView = new Proxy({ ...view, bbox: new Proxy(view.bbox, {}) }, {})
  const pending = client.load(reactiveRender, reactiveView, new AbortController().signal)
  const message = worker.messages[0]
  assert.deepEqual(message.view.bbox, view.bbox)
  assert.equal(message.render.contains_roads, true)
  const result = { type: 'FeatureCollection', features: [], truncated: false }
  worker.onmessage({ data: { id: message.id, data: result } })
  assert.deepEqual(await pending, result)
})

test('cancelling a tile view rejects it and ignores its late result', async t => {
  const { client, worker } = setup(t)
  const abort = new AbortController()
  const pending = client.load(render, view, abort.signal)
  const id = worker.messages[0].id
  abort.abort()
  await assert.rejects(pending, { name: 'AbortError' })
  assert.deepEqual(worker.messages.at(-1), { cancel: id })
  assert.doesNotThrow(() => worker.onmessage({ data: { id, data: {} } }))
})

test('a crashed decoder rejects current and later requests instead of hanging', async t => {
  const { client, worker } = setup(t)
  const pending = client.load(render, view, new AbortController().signal)
  worker.onerror()
  await assert.rejects(pending, /瓦片解码进程异常/)
  await assert.rejects(client.load(render, view, new AbortController().signal), /瓦片解码进程异常/)
  assert.equal(worker.messages.length, 1)
})

test('removing a tile layer terminates the decoder and rejects pending work', async t => {
  const { client, worker } = setup(t)
  const pending = client.load(render, view, new AbortController().signal)
  client.destroy()
  await assert.rejects(pending, { name: 'AbortError' })
  assert.equal(worker.terminated, true)
  await assert.rejects(client.load(render, view, new AbortController().signal), { name: 'AbortError' })
})
