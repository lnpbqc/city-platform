import { test } from 'node:test'
import assert from 'node:assert/strict'
import { layerDownload, fetchLayerDownload } from '../src/layerDownload.ts'
import { samplesForCampus, mapLayer } from '../src/types.ts'

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
