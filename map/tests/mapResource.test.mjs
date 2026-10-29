import { test, mock } from 'node:test'
import assert from 'node:assert/strict'
import { fetchMapGeoJSON, mapLoadError } from '../src/mapResource.ts'

test('GeoJSON streaming reports actual byte progress and parses UTF8', async (t) => {
  const bytes = new TextEncoder().encode('{"type":"FeatureCollection","名称":"校园","features":[]}')
  const stream = new ReadableStream({ start(controller) { controller.enqueue(bytes.slice(0, 12)); controller.enqueue(bytes.slice(12)); controller.close() } })
  t.mock.method(globalThis, 'fetch', async () => new Response(stream, { headers: { 'Content-Length': String(bytes.length) } }))
  const progress = []
  const result = await fetchMapGeoJSON('/test.geojson', new AbortController().signal, (...args) => progress.push(args))
  assert.equal(result['名称'], '校园')
  assert.deepEqual(progress.at(-1), [bytes.length, bytes.length])
  assert.equal(progress[0][0], 12)
})

test('resource errors preserve server code and trace', async (t) => {
  t.mock.method(globalThis, 'fetch', async () => new Response(JSON.stringify({ code: 'NOT_FOUND', message: '文件不存在', trace_id: 'resource-trace' }), { status: 404 }))
  await assert.rejects(fetchMapGeoJSON('/bad', new AbortController().signal), error => error.code === 'NOT_FOUND' && error.traceId === 'resource-trace')
})

test('invalid JSON is a visible parse error with a client diagnostic', async (t) => {
  t.mock.method(globalThis, 'fetch', async () => new Response('invalid JSON'))
  await assert.rejects(fetchMapGeoJSON('/bad', new AbortController().signal), error => error.code === 'RESOURCE_INVALID' && error.traceId.startsWith('client-'))
})

test('Cesium request error headers remain traceable; network failures get client IDs', () => {
  const error = mapLoadError({ statusCode: 404, responseHeaders: { 'x-trace-id': 'tile-trace' }, response: '{"message":"瓦片不存在","code":"NOT_FOUND"}' })
  assert.equal(error.traceId, 'tile-trace')
  assert.equal(error.code, 'NOT_FOUND')
  assert.match(error.message, /瓦片不存在/)
  assert.equal(mapLoadError(new Error('CORS')).code, 'RESOURCE_LOAD_FAILED')
  assert.match(mapLoadError(new Error('CORS')).traceId, /^client-/)
})

test('aborted fetch is retained as cancellation', async (t) => {
  t.mock.method(globalThis, 'fetch', async () => { throw new DOMException('取消', 'AbortError') })
  await assert.rejects(fetchMapGeoJSON('/test', new AbortController().signal), error => error.name === 'AbortError')
})
