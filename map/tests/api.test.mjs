import { test } from 'node:test'
import assert from 'node:assert/strict'
import { ApiError, getLayers, getLayerCatalog, saveCatalogMapState, getAssetVersion, getObjects, getObject, selectObjects } from '../src/api.ts'

test('new error envelopes preserve domain code, detail and trace in visible messages', async (t) => {
  t.mock.method(globalThis, 'fetch', async () => new Response(JSON.stringify({
    code: 'ASSET_IN_USE', message: '资产仍有引用', detail: { references: [{ id: 'one' }] }, trace_id: 'server-trace',
  }), { status: 409 }))
  await assert.rejects(getLayers(), (error) => {
    assert.ok(error instanceof ApiError)
    assert.equal(error.status, 409)
    assert.equal(error.code, 'ASSET_IN_USE')
    assert.equal(error.traceId, 'server-trace')
    assert.deepEqual(error.detail, { references: [{ id: 'one' }] })
    assert.match(error.message, /资产仍有引用/)
    assert.match(error.message, /ASSET_IN_USE/)
    assert.match(error.message, /trace_id: server-trace/)
    return true
  })
})

for (const [detail, message] of [
  ['旧格式错误', '旧格式错误'],
  [[{ msg: '名称必填' }, { msg: '地址必填' }], '名称必填；地址必填'],
  [{ message: '仍被引用', references: [] }, '仍被引用'],
]) {
  test(`legacy error detail stays supported: ${message}`, async (t) => {
    t.mock.method(globalThis, 'fetch', async () => new Response(JSON.stringify({ detail }), { status: 422 }))
    await assert.rejects(getLayers(), (error) => error.message === message && error.status === 422)
  })
}

test('non-JSON errors retain the HTTP status and trace response header', async (t) => {
  t.mock.method(globalThis, 'fetch', async () => new Response('upstream unavailable', {
    status: 502, headers: { 'X-Trace-ID': 'proxy-trace' },
  }))
  await assert.rejects(getLayers(), (error) => error.status === 502 && error.traceId === 'proxy-trace')
})

test('network failures have a distinct code and client diagnostic id', async (t) => {
  t.mock.method(globalThis, 'fetch', async () => { throw new TypeError('Failed to fetch') })
  await assert.rejects(getLayers(), (error) => error.status === 0 && error.code === 'NETWORK_ERROR' && error.traceId.startsWith('client-'))
})

test('successful responses are unchanged', async (t) => {
  t.mock.method(globalThis, 'fetch', async () => new Response(JSON.stringify([{ id: 'one' }]), { status: 200 }))
  assert.deepEqual(await getLayers(), [{ id: 'one' }])
})

test('catalog and pinned asset APIs encode identifiers and forward abort signals', async (t) => {
  const calls = []
  t.mock.method(globalThis, 'fetch', async (url, options) => {
    calls.push({ url, options })
    return new Response(JSON.stringify([]), { status: 200 })
  })
  const signal = new AbortController().signal
  await getLayerCatalog('huangpu', signal)
  await getAssetVersion('asset/one', '1.0 beta', signal)
  await saveCatalogMapState('demo/points', { map_attached: false, map_visible: true, map_opacity: 0.4 }, 'huangpu')
  assert.equal(calls[0].url, '/api/layers/catalog?campus=huangpu')
  assert.equal(calls[0].options.signal, signal)
  assert.equal(calls[1].url, '/api/assets/asset%2Fone/versions/1.0%20beta')
  assert.equal(calls[1].options.signal, signal)
  assert.equal(calls[2].url, '/api/layers/catalog/demo%2Fpoints/map-state?campus=huangpu')
  assert.equal(calls[2].options.keepalive, true)
  assert.deepEqual(JSON.parse(calls[2].options.body), { map_attached: false, map_visible: true, map_opacity: 0.4 })
})

test('object APIs retain query, geometry, paging and abort context', async (t) => {
  const calls = []
  t.mock.method(globalThis, 'fetch', async (url, options) => {
    calls.push({ url, options })
    return new Response('{}', { status: 200 })
  })
  const signal = new AbortController().signal
  const query = { asset_id: 'asset/one', version: '1.0.0', layer_id: 'demo-points', type: '', q: '教学 楼', page: 2, page_size: 20 }
  const geometry = { type: 'Polygon', coordinates: [[[0, 0], [1, 0], [0, 1], [0, 0]]] }
  await getObjects(query, signal)
  await getObject('object/id', signal)
  await selectObjects(query, geometry, signal)
  const params = new URL(calls[0].url, 'http://local').searchParams
  assert.equal(params.get('asset_id'), 'asset/one')
  assert.equal(params.get('q'), '教学 楼')
  assert.equal(params.get('type'), null)
  assert.equal(calls[0].options.signal, signal)
  assert.equal(calls[1].url, '/api/objects/object%2Fid')
  assert.equal(calls[1].options.signal, signal)
  assert.equal(calls[2].url, '/api/objects/select')
  assert.equal(calls[2].options.method, 'POST')
  assert.deepEqual(JSON.parse(calls[2].options.body), { ...query, geometry })
  assert.equal(calls[2].options.signal, signal)
})
