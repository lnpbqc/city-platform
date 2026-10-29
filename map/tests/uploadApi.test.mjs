import { test } from 'node:test'
import assert from 'node:assert/strict'
import * as api from '../src/api.ts'

function xhrFixture(t) {
  const requests = []
  class UploadRequest {
    upload = {}
    status = 0
    responseText = ''
    headers = {}
    open(method, url) { this.method = method; this.url = url }
    send(body) { this.body = body; this.sent = true }
    setRequestHeader(name, value) { this.headers[name] = value }
    getResponseHeader(name) { return name.toLowerCase() === 'x-trace-id' ? 'header-trace' : null }
    abort() { this.aborted = true; this.onabort?.() }
    finish(status, body) {
      this.status = status
      this.responseText = typeof body === 'string' ? body : JSON.stringify(body)
      this.onload?.()
    }
    constructor() { requests.push(this) }
  }
  const previous = globalThis.XMLHttpRequest
  globalThis.XMLHttpRequest = UploadRequest
  t.after(() => {
    if (previous === undefined) delete globalThis.XMLHttpRequest
    else globalThis.XMLHttpRequest = previous
  })
  return requests
}

test('XHR upload reports transport and validation separately without setting Content-Type', async (t) => {
  const requests = xhrFixture(t)
  const events = []
  const body = new FormData()
  const uploading = api.uploadLayer(body, {
    onProgress: (loaded, total) => events.push([loaded, total]),
    onUploaded: () => events.push('validating'),
  })
  assert.equal(requests.length, 1)
  const xhr = requests[0]
  assert.equal(xhr.method, 'POST')
  assert.equal(xhr.url, '/api/layers/upload')
  assert.equal(xhr.body, body)
  assert.deepEqual(xhr.headers, {})
  xhr.upload.onprogress({ lengthComputable: true, loaded: 10, total: 20 })
  xhr.upload.onload()
  assert.deepEqual(events, [[10, 20], 'validating'])
  xhr.finish(201, { id: 'uploaded' })
  assert.deepEqual(await uploading, { id: 'uploaded' })
})

test('upload cancellation aborts XHR and releases the signal listener', async (t) => {
  const requests = xhrFixture(t)
  const controller = new AbortController()
  const removed = t.mock.method(controller.signal, 'removeEventListener')
  const uploading = api.uploadLayer(new FormData(), { signal: controller.signal })
  controller.abort()
  await assert.rejects(uploading, (error) => error.name === 'AbortError' && !(error instanceof api.ApiError))
  assert.equal(requests[0].aborted, true)
  assert.equal(removed.mock.calls.length, 1)
})

test('already cancelled upload sends no request', async (t) => {
  const requests = xhrFixture(t)
  const controller = new AbortController()
  controller.abort()
  await assert.rejects(api.uploadLayer(new FormData(), { signal: controller.signal }), { name: 'AbortError' })
  assert.equal(requests.length, 0)
})

test('completed upload releases cancellation and ignores a later abort', async (t) => {
  const requests = xhrFixture(t)
  const controller = new AbortController()
  const removed = t.mock.method(controller.signal, 'removeEventListener')
  const uploading = api.uploadLayer(new FormData(), { signal: controller.signal })
  requests[0].finish(201, { id: 'complete' })
  await uploading
  controller.abort()
  assert.equal(removed.mock.calls.length, 1)
  assert.equal(requests[0].aborted, undefined)
})

for (const [body, message, code] of [
  [{ code: 'CONTENT_INVALID', message: '路径含反斜杠', detail: { path: 'a\\b' }, trace_id: 'server-trace' }, '路径含反斜杠', 'CONTENT_INVALID'],
  [{ detail: '缺少 tileset.json' }, '缺少 tileset.json', 'HTTP_ERROR'],
  [{ detail: [{ msg: '名称必填' }] }, '名称必填', 'HTTP_ERROR'],
]) {
  test(`upload preserves API error parsing: ${message}`, async (t) => {
    const requests = xhrFixture(t)
    const uploading = api.uploadLayer(new FormData())
    requests[0].finish(422, body)
    await assert.rejects(uploading, (error) => error instanceof api.ApiError && error.status === 422 && error.code === code && error.message.includes(message))
  })
}

test('XHR network failure has the shared client diagnostic code', async (t) => {
  const requests = xhrFixture(t)
  const uploading = api.uploadLayer(new FormData())
  requests[0].onerror()
  await assert.rejects(uploading, (error) => error.code === 'NETWORK_ERROR' && error.traceId.startsWith('client-'))
})

test('paged asset APIs encode filters and preserve old getAssets', async (t) => {
  const requests = []
  t.mock.method(globalThis, 'fetch', async (url, options) => {
    requests.push({ url, options })
    return new Response(JSON.stringify({ ok: true }))
  })
  await api.getAssetPage({ page: 2, page_size: 10, type: '3dtiles', q: '校区 100%', from: '2026-10-25T12:00:00+08:00', sort: '-byte_size' })
  const url = new URL(requests[0].url, 'http://local')
  assert.equal(url.pathname, '/api/assets')
  assert.equal(url.searchParams.get('page'), '2')
  assert.equal(url.searchParams.get('q'), '校区 100%')
  assert.equal(url.searchParams.get('from'), '2026-10-25T12:00:00+08:00')
  await api.getAssetPage()
  assert.equal(new URL(requests[1].url, 'http://local').searchParams.get('page'), '1')
  await api.getAssets()
  assert.equal(requests[2].url, '/api/assets')
  await api.getStats()
  assert.equal(requests[3].url, '/api/stats/overview')
  await api.getAssetVersions('asset / id')
  assert.equal(requests[4].url, '/api/assets/asset%20%2F%20id/versions')
  const registration = { name: '外部数据', type: '3dtiles', location: 'https://example.invalid/tileset.json', source: '提供方', coordinate_description: 'WGS84' }
  await api.registerAsset(registration)
  assert.equal(requests[5].url, '/api/assets/register')
  assert.equal(requests[5].options.method, 'POST')
  assert.deepEqual(JSON.parse(requests[5].options.body), registration)
  await api.getAssetPage({ page: undefined, page_size: undefined })
  const defaultPage = new URL(requests[6].url, 'http://local')
  assert.equal(defaultPage.searchParams.get('page'), '1')
  assert.equal(defaultPage.searchParams.get('page_size'), '20')
})
