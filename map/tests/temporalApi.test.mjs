import { test } from 'node:test'
import assert from 'node:assert/strict'
import { getLayerTimes, getTimeSeries, getObject } from '../src/api.ts'

test('time APIs send fixed versions, zoned time and resolution without changing legacy detail URLs', async t => {
  const calls = [], signal = new AbortController().signal
  t.mock.method(globalThis, 'fetch', async (url, options) => { calls.push({ url, options }); return new Response('{}') })
  await getLayerTimes('layer/id', { asset_id: 'asset', version: '1.0.0', campus: 'huangpu' }, signal)
  assert.equal(calls[0].url, '/api/layers/layer%2Fid/times?asset_id=asset&version=1.0.0&campus=huangpu')
  await getTimeSeries({ layer_id: 'layer/id', asset_id: 'asset', version: '1.0.0', time: '2026-10-25T08:00:00+08:00', resolution: 'day', bbox: '113,23,114,24' }, signal)
  const query = new URL(calls[1].url, 'http://localhost').searchParams
  assert.equal(query.get('time'), '2026-10-25T08:00:00+08:00')
  assert.equal(query.get('bbox'), '113,23,114,24')
  await getObject('id', signal)
  assert.equal(calls[2].url, '/api/objects/id')
  await getObject('id', signal, { time: '2026-10-25T00:00:00Z', resolution: 'day' })
  assert.equal(new URL(calls[3].url, 'http://localhost').searchParams.get('resolution'), 'day')
  assert.ok(calls.every(call => call.options.signal === signal))
})
