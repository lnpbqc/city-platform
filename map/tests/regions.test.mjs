import { test } from 'node:test'
import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import { createRegionIndex, chinaRegion, campusRegions, resolveRegionTarget } from '../src/regions.ts'

const catalog = JSON.parse(
  await readFile(
    new URL('../public/data/regions.json', import.meta.url),
    'utf8',
  ),
)
const index = createRegionIndex(catalog.regions)

test('directory includes 34 provincial entries and valid, connected reference points', () => {
  assert.equal(index.children('100000').length, 34)
  assert.equal(
    new Set(catalog.regions.map((region) => region.id)).size,
    catalog.regions.length,
  )
  for (const region of catalog.regions) {
    assert.ok(
      Number.isFinite(region.longitude) && Math.abs(region.longitude) <= 180,
    )
    assert.ok(
      Number.isFinite(region.latitude) && Math.abs(region.latitude) <= 90,
    )
    if (region.parent) assert.ok(index.byId.has(region.parent), region.id)
  }
})
test('Guangdong / Guangzhou / Tianhe selection resolves the correct path and target', () => {
  assert.ok(index.children('440000').some((region) => region.id === '440100'))
  assert.ok(index.children('440100').some((region) => region.id === '440106'))
  assert.equal(index.target('440106').label, '广东省 · 广州市 · 天河区')
  assert.ok(Math.abs(index.target('440106').longitude - 113.33) < 0.05)
})
test('municipalities, Hong Kong and province-administered districts keep their actual parent', () => {
  assert.ok(
    index
      .children('110000')
      .some((region) => region.id === '110101' && region.level === 'district'),
  )
  assert.equal(
    index.children('810000').filter((region) => region.level === 'district')
      .length,
    18,
  )
  assert.ok(
    index.children('460000').some((region) => region.level === 'district'),
  )
  assert.equal(index.children('710000').length, 0)
})
test('search supports full paths, codes and ambiguous district names', () => {
  assert.equal(index.search('广东 广州 天河')[0].id, '440106')
  assert.equal(index.search('440106')[0].id, '440106')
  const names = index
    .search('朝阳区')
    .map((region) => index.target(region.id).label)
  assert.ok(names.some((name) => name.includes('北京')))
  assert.ok(names.some((name) => name.includes('长春')))
  assert.deepEqual(index.search('   '), [])
  assert.deepEqual(index.search('不存在的测试地区'), [])
  assert.equal(index.target('100000'), chinaRegion)
})

test('saved country and campus regions resolve without loading the directory', async (t) => {
  const fetching = t.mock.method(globalThis, 'fetch', () => {
    throw new Error('shortcuts should not fetch')
  })
  assert.equal(await resolveRegionTarget('100000'), chinaRegion)
  for (const campus of campusRegions)
    assert.equal(await resolveRegionTarget(campus.id), campus)
  assert.equal(fetching.mock.callCount(), 0)
})

test('saved administrative regions resolve with the existing directory path and camera target', async (t) => {
  t.mock.method(globalThis, 'fetch', async (url) => {
    assert.equal(url, '/data/regions.json')
    return { ok: true, json: async () => catalog }
  })
  assert.deepEqual(await resolveRegionTarget('440106'), index.target('440106'))
  await assert.rejects(resolveRegionTarget('missing'), /不存在该代码/)
})

test('directory network and format failures allow a subsequent location retry', async (t) => {
  const fetching = t.mock.method(globalThis, 'fetch', async () => ({ ok: false, status: 503 }))
  await assert.rejects(resolveRegionTarget('440106'), /503/)
  fetching.mock.mockImplementation(async () => ({ ok: true, json: async () => null }))
  await assert.rejects(resolveRegionTarget('440106'), /格式无效/)
  fetching.mock.mockImplementation(async () => ({ ok: true, json: async () => ({ regions: {} }) }))
  await assert.rejects(resolveRegionTarget('440106'), /格式无效/)
  fetching.mock.mockImplementation(async () => ({ ok: true, json: async () => catalog }))
  assert.deepEqual(await resolveRegionTarget('440106'), index.target('440106'))
})
