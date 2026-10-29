import { test } from 'node:test'
import assert from 'node:assert/strict'
import { ApiError, getRuns, rerunRun, downloadRun } from '../src/api.ts'

test('history APIs encode fixed rerun and UTC filters, carry abort signals, and download actual blobs', async t => {
  const calls = [], signal = new AbortController().signal
  t.mock.method(globalThis, 'fetch', async (url, options) => {
    calls.push({ url, options })
    return new Response(url.includes('/download') ? '{"original":true}' : '{}', { status: 200 })
  })
  await getRuns({ page: 3, page_size: 100, scene_id: '场景/id', status: 'failed', from: '2026-10-27T00:00:00+08:00', to: '' }, signal)
  const url = new URL(calls[0].url, 'http://localhost')
  assert.equal(url.searchParams.get('scene_id'), '场景/id')
  assert.equal(url.searchParams.get('from'), '2026-10-27T00:00:00+08:00')
  assert.equal(url.searchParams.get('page'), '3')
  assert.equal(url.searchParams.has('to'), false)
  await rerunRun('old/id', 'fixed-key', signal)
  assert.equal(calls[1].url, '/api/runs/old%2Fid/rerun')
  assert.equal(calls[1].options.method, 'POST')
  assert.equal(calls[1].options.headers['Idempotency-Key'], 'fixed-key')
  assert.equal(calls[1].options.body, undefined)
  const result = await downloadRun('old/id', 'geojson', signal)
  assert.ok(result instanceof Blob)
  assert.equal(await result.text(), '{"original":true}')
  assert.equal(calls[2].url, '/api/runs/old%2Fid/download?format=geojson')
  assert.ok(calls.every(call => call.options.signal === signal))
  await getRuns()
  assert.equal(calls[3].url, '/api/runs?page=1&page_size=20')
})
test('downloads keep unified structured errors instead of turning failed responses into files', async t => {
  t.mock.method(globalThis, 'fetch', async () => new Response(JSON.stringify({ code: 'RUN_NOT_SUCCEEDED', message: '没有成功结果', detail: { status: 'failed' }, trace_id: 'history-trace' }), { status: 409 }))
  await assert.rejects(downloadRun('run', 'json'), cause => cause instanceof ApiError && cause.status === 409 && cause.code === 'RUN_NOT_SUCCEEDED' && cause.traceId === 'history-trace' && cause.detail.status === 'failed')
})
