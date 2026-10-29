import { mock, test } from 'node:test'
import assert from 'node:assert/strict'
import { createRenderer, defineComponent } from 'vue'

const deferred = () => {
  let resolve, reject
  const promise = new Promise((yes, no) => {
    resolve = yes
    reject = no
  })
  return { promise, resolve, reject }
}
class ApiError extends Error {
  constructor(message, status, detail) {
    super(message)
    this.status = status
    this.detail = detail
  }
}
let listRequest, detailRequest, deleteRequest, scanRequest, statsRequest
mock.module('../src/api.ts', {
  exports: {
    ApiError,
    getAssets: () => listRequest(),
    getAssetPage: async (query) => {
      const result = await listRequest(query)
      return Array.isArray(result) ? { items: result, total: result.length, page: query.page, page_size: query.page_size } : result
    },
    getStats: () => statsRequest(),
    getAsset: (id) => detailRequest(id),
    deleteAsset: (id) => deleteRequest(id),
    reconcileAssets: () => scanRequest(),
  },
})
const { useAssets } = await import('../src/composables/useAssets.ts')
const renderer = createRenderer({
  createElement: () => ({}),
  createText: () => ({}),
  createComment: () => ({}),
  insert() {},
  remove() {},
  setText() {},
  setElementText() {},
  patchProp() {},
  parentNode: () => null,
  nextSibling: () => null,
})
function setup() {
  let assets
  listRequest = async () => []
  detailRequest = async (id) => ({ id, files: [] })
  deleteRequest = async () => undefined
  scanRequest = async () => ({ discovered: 0, assets: [] })
  statsRequest = async () => ({ asset_count: 0, object_count: 0, run_count: 0, total_byte_size: 0, assets_by_type: {}, assets_added_last_7_days: 0 })
  const app = renderer.createApp(
    defineComponent({
      setup() {
        assets = useAssets()
        return () => null
      },
    }),
  )
  app.mount({})
  return { app, assets }
}
const asset = {
  id: 'first-asset',
  original_name: 'example.geojson',
  type: 'geojson',
  entry_url: '/data-files/first/data.geojson',
  byte_size: 20,
  file_count: 1,
  uploaded_at: '2026-10-22T01:00:00Z',
  discovered_at: '2026-10-22T01:00:00Z',
  status: 'active',
  error: '',
  references: [],
  reference_count: 0,
}

test('reference conflict retains confirmation and blocks repeat deletion until reopened', async () => {
  const { app, assets } = setup()
  let calls = 0
  const references = [{ id: 'registered-layer', name: '仍然引用的图层' }]
  deleteRequest = async () => {
    calls++
    throw new ApiError('文件仍有登记引用', 409, {
      message: '文件仍有登记引用',
      references,
    })
  }
  listRequest = async () => [{ ...asset, references, reference_count: 1 }]
  assets.askDelete(asset)
  await assets.confirmDelete()
  assert.equal(assets.pendingDelete.value.id, asset.id)
  assert.deepEqual(assets.conflicts.value, references)
  assert.match(assets.deleteError.value, /登记引用/)
  assert.equal(assets.assets.value[0].reference_count, 1)
  await assets.confirmDelete()
  assert.equal(calls, 1)
  assets.cancelDelete()
  assert.equal(assets.pendingDelete.value, null)
  assert.deepEqual(assets.conflicts.value, [])
  app.unmount()
})

test('failed deletion refreshes error state and can retry to finish cleanup', async () => {
  const { app, assets } = setup()
  let calls = 0
  deleteRequest = async () => {
    calls++
    if (calls === 1)
      throw new ApiError('磁盘清理失败，请重试', 500, '磁盘清理失败，请重试')
  }
  listRequest = async () =>
    calls === 1
      ? [{ ...asset, status: 'delete_error', error: '磁盘清理失败' }]
      : []
  assets.askDelete(asset)
  await assets.confirmDelete()
  assert.equal(assets.assets.value[0].status, 'delete_error')
  assert.match(assets.deleteError.value, /清理失败/)
  assert.equal(assets.deleting.value, false)
  await assets.confirmDelete()
  assert.equal(calls, 2)
  assert.equal(assets.pendingDelete.value, null)
  assert.deepEqual(assets.assets.value, [])
  assert.match(assets.message.value, /彻底删除/)
  app.unmount()
})

test('mixed reference conflict retains scene and historical versions for display and blocks another delete', async () => {
  const { app, assets } = setup()
  const references = [{ id: 'layer', name: 'layer' },
    { type: 'scene', id: 'scene', name: 'scene', version: 2, asset_version: '1.0.0' },
    { type: 'run', id: 'run', name: 'snapshot', version: 1, asset_version: '1.0.0' }]
  let calls = 0
  deleteRequest = async () => {
    calls++
    throw new ApiError('被1个图层、1个场景、1条历史运行引用', 409, { references, reference_count: 3 })
  }
  assets.askDelete(asset)
  await assets.confirmDelete()
  assert.deepEqual(assets.conflicts.value, references)
  await assets.confirmDelete()
  assert.equal(calls, 1)
  app.unmount()
})

test('busy deletion ignores duplicate confirmation, cancellation and changing target', async () => {
  const { app, assets } = setup()
  const gate = deferred()
  let calls = 0
  deleteRequest = () => {
    calls++
    return gate.promise
  }
  assets.askDelete(asset)
  const deleting = assets.confirmDelete()
  assert.equal(assets.deleting.value, true)
  assets.cancelDelete()
  assets.askDelete({ ...asset, id: 'other-asset' })
  await assets.confirmDelete()
  assert.equal(assets.pendingDelete.value.id, asset.id)
  assert.equal(calls, 1)
  gate.resolve()
  await deleting
  assert.equal(assets.pendingDelete.value, null)
  assert.equal(assets.deleting.value, false)
  app.unmount()
})

test('switching and closing asset detail invalidates stale responses', async () => {
  const { app, assets } = setup()
  const first = deferred(),
    second = deferred(),
    third = deferred()
  detailRequest = (id) => ({ first, second, third })[id].promise
  const firstRun = assets.openDetail('first')
  const secondRun = assets.openDetail('second')
  second.resolve({ id: 'second', files: [] })
  await secondRun
  first.resolve({ id: 'first', files: [] })
  await firstRun
  assert.equal(assets.detail.value.id, 'second')
  const thirdRun = assets.openDetail('third')
  assets.closeDetail()
  third.reject(new Error('已关闭的请求失败'))
  await thirdRun
  assert.equal(assets.detailId.value, '')
  assert.equal(assets.detail.value, null)
  assert.equal(assets.detailError.value, '')
  app.unmount()
})

test('out-of-order list requests and unmounted details do not overwrite current state', async () => {
  const { app, assets } = setup()
  const first = deferred(),
    second = deferred(),
    detail = deferred()
  let calls = 0
  listRequest = () => (++calls === 1 ? first : second).promise
  const firstRun = assets.refresh(),
    secondRun = assets.refresh()
  second.resolve([{ ...asset, id: 'latest' }])
  await secondRun
  first.resolve([asset])
  await firstRun
  assert.equal(assets.assets.value[0].id, 'latest')
  detailRequest = () => detail.promise
  const detailRun = assets.openDetail(asset.id)
  app.unmount()
  detail.resolve({ ...asset, files: [] })
  await detailRun
  assert.equal(assets.detail.value, null)
})

test('manual scan reports discoveries and reloads asset inventory', async () => {
  const { app, assets } = setup()
  scanRequest = async () => ({ discovered: 2, assets: [asset] })
  listRequest = async () => [asset]
  await assets.scan()
  assert.match(assets.message.value, /补录 2/)
  assert.equal(assets.assets.value.length, 1)
  assert.equal(assets.scanning.value, false)
  app.unmount()
})

test('server pagination and filters reset page and update totals and overview', async () => {
  const { app, assets } = setup()
  const queries = []
  listRequest = async (query) => {
    queries.push(query)
    return { items: [asset], total: 41, page: query.page, page_size: query.page_size }
  }
  statsRequest = async () => ({ asset_count: 41, total_byte_size: 300 })
  await assets.setPage(3)
  assert.equal(assets.page.value, 3)
  assert.equal(assets.total.value, 41)
  await assets.setQuery({ q: '校区', type: 'geojson', sort: '-byte_size' })
  assert.equal(assets.page.value, 1)
  assert.deepEqual(assets.query.value, { q: '校区', type: 'geojson', sort: '-byte_size' })
  assert.deepEqual(queries.at(-1), { q: '校区', type: 'geojson', sort: '-byte_size', page: 1, page_size: 20 })
  assert.equal(assets.stats.value.asset_count, 41)
  app.unmount()
})

test('deleting the last item on the last page returns to a valid page', async () => {
  const { app, assets } = setup()
  let deleted = false
  const pages = []
  listRequest = async ({ page, page_size }) => {
    pages.push(page)
    return { items: page === 2 ? (deleted ? [] : [asset]) : [{ ...asset, id: 'previous' }], total: deleted ? 20 : 21, page, page_size }
  }
  deleteRequest = async () => { deleted = true }
  await assets.setPage(2)
  assets.askDelete(asset)
  await assets.confirmDelete()
  assert.equal(assets.page.value, 1)
  assert.equal(assets.assets.value[0].id, 'previous')
  assert.equal(assets.total.value, 20)
  assert.deepEqual(pages, [2, 2, 1])
  app.unmount()
})

test('stale page and statistics responses cannot replace a newer filter result', async () => {
  const { app, assets } = setup()
  const first = deferred(), second = deferred(), firstStats = deferred(), secondStats = deferred()
  let lists = 0, statistics = 0
  listRequest = () => (++lists === 1 ? first : second).promise
  statsRequest = () => (++statistics === 1 ? firstStats : secondStats).promise
  const oldRun = assets.refresh()
  const newRun = assets.setQuery({ q: 'new' })
  second.resolve({ items: [{ ...asset, id: 'new' }], total: 1, page: 1, page_size: 20 })
  secondStats.resolve({ asset_count: 1 })
  await newRun
  first.resolve({ items: [asset], total: 20, page: 1, page_size: 20 })
  firstStats.resolve({ asset_count: 20 })
  await oldRun
  assert.equal(assets.assets.value[0].id, 'new')
  assert.equal(assets.total.value, 1)
  assert.equal(assets.stats.value.asset_count, 1)
  app.unmount()
})

for (const operation of ['page', 'filter']) {
  test(`failed ${operation} request clears rows and count from the previous result`, async () => {
    const { app, assets } = setup()
    listRequest = async ({ page, page_size }) => ({ items: [asset], total: 30, page, page_size })
    await assets.refresh()
    assert.equal(assets.assets.value.length, 1)
    listRequest = async () => { throw new Error('服务暂不可用') }
    if (operation === 'page') await assets.setPage(2)
    else await assets.setQuery({ type: '3dtiles' })
    assert.deepEqual(assets.assets.value, [])
    assert.equal(assets.total.value, 0)
    assert.match(assets.error.value, /服务暂不可用/)
    app.unmount()
  })
}

test('statistics failures stay separate from a successful asset page and retry only the overview', async () => {
  const { app, assets } = setup()
  let lists = 0
  listRequest = async () => { lists++; return [asset] }
  statsRequest = async () => { throw new ApiError('无权限：统计读取受限 · trace_id: stats', 403) }
  await assets.refresh()
  assert.deepEqual(assets.assets.value, [asset])
  assert.equal(assets.total.value, 1)
  assert.equal(assets.error.value, '')
  assert.match(assets.statsError.value, /无权限/)
  assert.equal(assets.stats.value, null)
  assert.equal(assets.statsLoading.value, false)
  statsRequest = async () => ({ asset_count: 1, object_count: 8, run_count: 3 })
  await assets.refreshStats()
  assert.equal(lists, 1)
  assert.equal(assets.stats.value.run_count, 3)
  assert.equal(assets.statsError.value, '')
  app.unmount()
})

test('asset page renders as soon as ready while independent statistics are pending or a previous overview is stale', async () => {
  const { app, assets } = setup()
  await assets.refresh()
  const statistics = deferred()
  listRequest = async () => [asset]
  statsRequest = () => statistics.promise
  const refreshing = assets.refresh()
  await new Promise(setImmediate)
  assert.equal(assets.assets.value[0].id, asset.id)
  assert.equal(assets.loading.value, false)
  assert.equal(assets.statsLoading.value, true)
  assert.equal(assets.stats.value, null)
  statistics.reject(new Error('统计读取失败 · trace_id: overview'))
  await refreshing
  assert.equal(assets.assets.value[0].id, asset.id)
  assert.equal(assets.stats.value, null)
  assert.match(assets.statsError.value, /overview/)
  app.unmount()
})

test('asset failures do not suppress successful overview data and stale overview failures cannot replace a retry', async () => {
  const { app, assets } = setup()
  listRequest = async () => { throw new ApiError('无权限：资产读取受限', 403) }
  statsRequest = async () => ({ asset_count: 4, object_count: 2, run_count: 1 })
  await assets.refresh()
  assert.match(assets.error.value, /无权限/)
  assert.equal(assets.stats.value.asset_count, 4)
  assert.equal(assets.statsError.value, '')
  const old = deferred()
  statsRequest = () => old.promise
  const older = assets.refreshStats()
  statsRequest = async () => ({ asset_count: 5 })
  await assets.refreshStats()
  old.reject(new Error('已失效统计错误'))
  await older
  assert.equal(assets.stats.value.asset_count, 5)
  assert.equal(assets.statsError.value, '')
  const late = deferred()
  statsRequest = () => late.promise
  const unmounting = assets.refreshStats()
  app.unmount()
  late.resolve({ asset_count: 9 })
  await unmounting
  assert.equal(assets.stats.value, null)
})
