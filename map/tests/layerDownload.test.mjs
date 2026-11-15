import { test } from 'node:test'
import assert from 'node:assert/strict'
import { layerDownload, fetchLayerDownload, startTilesZipDownload } from '../src/layers/layerDownload.ts'
import { samplesForCampus, mapLayer } from '../src/layers/types.ts'

test('current model downloads pin the revision and use the asset name', () => {
  const layer = mapLayer({
    id: 'tiles', asset_id: 'model', asset_version: '1.0.0', name: '林芝/北区', type: '3dtiles',
    url: '/data-files/model/3dtiles/tileset.json', tiles_calibrated: true, tiles_revision: 2,
  })
  assert.deepEqual(layerDownload(layer), {
    url: '/api/assets/model/versions/1.0.0/download?revision=2',
    filename: '林芝_北区.zip', label: '下载校准后的 ZIP', external: false, native: true,
  })
})

test('native downloads check availability and leave the ZIP transfer to the browser', async t => {
  const url = '/api/assets/model/versions/1.0.1/download'
  const anchor = { click() { this.clicked = true }, remove() { this.removed = true } }
  const previous = globalThis.document
  globalThis.document = { createElement: () => anchor, body: { append() {} } }
  t.after(() => { if (previous === undefined) delete globalThis.document; else globalThis.document = previous })
  let response = new Response(null, { status: 409, headers: { 'X-Download-Error': encodeURIComponent('发布文件缺失') } })
  const requests = t.mock.method(globalThis, 'fetch', async () => response)
  await assert.rejects(startTilesZipDownload({ url, filename: 'model-1.0.1.zip' }), /发布文件缺失/)
  assert.equal(anchor.clicked, undefined)
  response = new Response()
  await startTilesZipDownload({ url, filename: 'model-1.0.1.zip' })
  assert.equal(anchor.href, url)
  assert.equal(anchor.download, 'model-1.0.1.zip')
  assert.equal(anchor.clicked && anchor.removed, true)
  assert.ok(requests.mock.calls.every(({ arguments: args }) => args[0] === url && args[1].method === 'HEAD'))
})

test('each campus downloads its own GeoJSON and complete 3D sample ZIP', () => {
  for (const campus of ['university-town', 'huangpu']) {
    for (const sample of samplesForCampus(campus)) {
      const target = layerDownload(mapLayer(sample, true))
      assert.equal(target.external, false)
      assert.equal(
        target.url,
        sample.type === 'geojson'
          ? sample.url
          : `/samples/${campus}/buildings-demo.zip`,
      )
      assert.ok(
        target.filename.endsWith(
          sample.type === 'geojson' ? '.geojson' : '.zip',
        ),
      )
    }
  }
})

test('local assets use protected download; external tiles open the source without claiming a full model download', () => {
  const local = mapLayer({
    id: 'registered',
    asset_id: 'asset-id',
    name: 'a/b:c',
    type: '3dtiles',
    url: '/data-files/asset-id/city/tileset.json',
  })
  assert.deepEqual(layerDownload(local), {
    url: '/api/assets/asset-id/download',
    filename: 'a_b_c.zip',
    label: '下载完整 ZIP',
    external: false,
  })
  local.asset_id = null
  local.url = 'https://example.invalid/tileset.json'
  assert.equal(layerDownload(local).external, true)
  assert.equal(layerDownload(local).url, local.url)
  local.asset_id = 'registered-external-asset'
  assert.equal(layerDownload(local).external, true)
  assert.equal(layerDownload(local).url, local.url)
  local.type = 'geojson'
  local.url = 'https://example.invalid/points.geojson'
  assert.equal(layerDownload(local).external, false)
  assert.equal(layerDownload(local).url, local.url)
})

test('default HTTP ports remain external while the three backend aliases are managed', () => {
  const layer = mapLayer({ id: 'remote', asset_id: 'asset-id', name: '外部数据', category: '三维', type: '3dtiles', url: '' })
  for (const prefix of ['http://localhost:80', 'https://localhost:443']) {
    layer.url = `${prefix}/data-files/asset-id/tileset.json`
    assert.equal(layerDownload(layer).external, true)
    assert.equal(layerDownload(layer).url, layer.url)
  }
  for (const prefix of ['http://localhost:8000', 'http://127.0.0.1:5173', 'http://[::1]:4173']) {
    layer.url = `${prefix}/data-files/asset-id/tileset.json`
    assert.equal(layerDownload(layer).url, '/api/assets/asset-id/download')
  }
})

test('download returns actual bytes; HTTP and network failures propagate for the card error', async (t) => {
  t.mock.method(
    globalThis,
    'fetch',
    async () => new Response('{"type":"FeatureCollection"}'),
  )
  assert.equal(
    await (await fetchLayerDownload('/sample')).text(),
    '{"type":"FeatureCollection"}',
  )
  globalThis.fetch = async () =>
    new Response('{"detail":"文件资产入口缺失"}', { status: 409 })
  await assert.rejects(fetchLayerDownload('/missing'), /入口缺失/)
  globalThis.fetch = async () => new Response('offline', { status: 502 })
  await assert.rejects(fetchLayerDownload('/offline'), /502/)
  globalThis.fetch = async () => {
    throw new TypeError('Failed to fetch')
  }
  await assert.rejects(fetchLayerDownload('/cors'), /Failed to fetch/)
})
