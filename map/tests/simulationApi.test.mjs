import { test } from 'node:test'
import assert from 'node:assert/strict'
import { getScenes, getScene, saveScene, deleteScene, getNetworks, getNetwork, submitRun, getRun, getRunInput, getRunResult, cancelRun } from '../src/api.ts'

test('simulation APIs encode identifiers, preserve pagination and quote scene versions', async (t) => {
  const calls = []
  t.mock.method(globalThis, 'fetch', async (url, options) => {
    calls.push({ url, options })
    return new Response('{}', { status: 200 })
  })
  const signal = new AbortController().signal
  const body = { name: '场景' }
  await getScenes({ page: 2, page_size: 50 }, signal)
  await getScene('scene/id', signal)
  await saveScene(body, undefined, undefined, signal)
  await saveScene(body, 'scene/id', 7, signal)
  await deleteScene('scene/id', 7, signal)
  await getNetworks({ page: 3, page_size: 40 }, signal)
  await getNetwork('network/id', '1.0 beta', signal)
  await submitRun({ seed: 42 }, 'fixed-key', signal)
  await getRun('run/id', signal)
  await getRunInput('run/id', signal)
  await getRunResult('run/id', signal)
  await cancelRun('run/id', signal)
  assert.equal(calls[0].url, '/api/scenes?page=2&page_size=50')
  assert.equal(calls[1].url, '/api/scenes/scene%2Fid')
  assert.equal(calls[2].options.method, 'POST')
  assert.equal(calls[3].url, '/api/scenes/scene%2Fid')
  assert.equal(calls[3].options.method, 'PUT')
  assert.equal(calls[3].options.headers['If-Match'], '"7"')
  assert.equal(calls[4].options.method, 'DELETE')
  assert.equal(calls[4].options.headers['If-Match'], '"7"')
  assert.equal(calls[5].url, '/api/networks?page=3&page_size=40')
  assert.equal(calls[6].url, '/api/networks/network%2Fid?version=1.0%20beta')
  assert.equal(calls[7].options.headers['Idempotency-Key'], 'fixed-key')
  assert.deepEqual(JSON.parse(calls[7].options.body), { seed: 42 })
  assert.deepEqual(calls.slice(8).map(call => call.url), ['/api/runs/run%2Fid', '/api/runs/run%2Fid/input', '/api/runs/run%2Fid/result', '/api/runs/run%2Fid/cancel'])
  assert.equal(calls[11].options.method, 'POST')
  assert.ok(calls.every(call => call.options.signal === signal))
})
