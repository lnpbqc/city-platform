import { beforeEach, mock, test } from 'node:test'
import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import { stripTypeScriptTypes } from 'node:module'
import { parse, compileScript, compileTemplate } from 'vue/compiler-sfc'
import { createRenderer, nextTick } from 'vue'

const asset = { id: 'asset-one', name: '点位资产', original_name: 'points.geojson', type: 'geojson', source_kind: 'upload',
  protected: false, entry_url: '/data-files/asset-one/data.geojson', status: 'active', error: '', byte_size: 20, file_count: 1,
  uploaded_at: null, discovered_at: '2026-10-25T00:00:00Z', current_version: '1.0.0', source: '', references: [], reference_count: 0 }
const overview = { asset_count: 61, object_count: 8, run_count: 3, total_byte_size: 100, assets_by_type: { geojson: 61 }, assets_added_last_7_days: 2 }
let calls, list, statistics
beforeEach(() => {
  calls = { pages: [], statistics: 0, detail: [], writes: 0 }
  list = async query => ({ items: [asset], total: 61, ...query })
  statistics = async () => overview
  globalThis.Document = class {}
  globalThis.ShadowRoot = class {}
  globalThis.document = Object.assign(new Document(), { activeElement: null })
})
mock.module('../src/api/api.ts', { exports: {
  ApiError: class extends Error {},
  getScenes: async () => ({ items: [], total: 4 }),
  getAssetPage: query => { calls.pages.push({ ...query }); return list(query) },
  getStats: () => { calls.statistics++; return statistics() },
  getAsset: async id => { calls.detail.push(id); return { ...asset, id, files: [], file_checksums: [] } },
  deleteAsset: async () => { calls.writes++ }, reconcileAssets: async () => { calls.writes++; return { discovered: 0 } },
} })

const filename = new URL('../src/views/DataManagerView.vue', import.meta.url)
const descriptor = parse(await readFile(filename, 'utf8')).descriptor
const script = compileScript(descriptor, { id: 'data-manager-test' })
const template = compileTemplate({ source: descriptor.template.content, filename: filename.pathname, id: 'data-manager-test', compilerOptions: { bindingMetadata: script.bindings } })
assert.deepEqual(template.errors, [])
let compiled = stripTypeScriptTypes(script.content, { mode: 'transform' }).replace('export default', 'const component =')
compiled += '\n' + template.code.replace('export function render', 'function render') + '\ncomponent.render = render; export default component'
compiled = compiled.replace(/import\s+([\s\S]*?)\s+from\s+(['"])([^'"]+)\2\s*;?/g, (_statement, binding, _quote, specifier) => {
  if (specifier === 'vue') return `import ${binding} from '${import.meta.resolve('vue')}';`
  if (specifier === '@lucide/vue') return `const ${binding.replace(/\bas\b/g, ':')} = new Proxy({}, { get: () => ({ render: () => null }) });`
  if (specifier.endsWith('.vue')) return `const ${binding} = { render: () => null };`
  return `import ${binding} from '${new URL(specifier + '.ts', new URL('../src/views/DataManagerView.vue', import.meta.url)).href}';`
})
const component = (await import('data:text/javascript;base64,' + Buffer.from(compiled).toString('base64'))).default

function detach(node) { if (node.parent) { const index = node.parent.children.indexOf(node); if (index >= 0) node.parent.children.splice(index, 1) } }
const renderer = createRenderer({
  createElement: tag => ({ tagName: tag.toUpperCase(), text: '', children: [], addEventListener() {}, removeEventListener() {}, getRootNode: () => document,
    get options() { return this.children.filter(node => node.tagName === 'OPTION') } }),
  createText: text => ({ text, children: [] }), createComment: () => ({ text: '', children: [] }),
  insert(node, parent, anchor) { detach(node); node.parent = parent; const index = anchor ? parent.children.indexOf(anchor) : -1; parent.children.splice(index < 0 ? parent.children.length : index, 0, node) },
  remove: detach, setText: (node, text) => { node.text = text },
  setElementText(node, text) { node.text = text; node.children = [] },
  patchProp: (node, key, _previous, value) => { node[key] = value },
  parentNode: node => node.parent ?? null, nextSibling: node => node.parent?.children[node.parent.children.indexOf(node) + 1] ?? null,
})
const flush = async () => { await new Promise(setImmediate); await nextTick() }
const text = node => (node.text ?? '') + (node.children ?? []).map(text).join('')
async function setup(t, props = {}) {
  const root = { children: [] }
  const app = renderer.createApp(component, { active: true, recovery: 0, revision: 0, layers: [], backend: 'online', catalogError: '', deleting: '', ...props })
  app.mount(root); t.after(() => app.unmount()); await flush()
  return { root, state: app._instance.setupState, props: app._instance.props, text: () => text(root) }
}

test('scene references open the scene tab with the exact ID and show the scene count', async t => {
  const ctx = await setup(t)
  assert.match(ctx.text(), /场景\s*4/)
  await ctx.state.openDetail(asset.id)
  ctx.state.showScene('scene-from-asset')
  await flush()
  assert.equal(ctx.state.tab, 'scenes')
  assert.equal(ctx.state.sceneQuery, 'scene-from-asset')
  assert.equal(ctx.state.detailId, '')
  assert.equal(calls.writes, 0)
})

test('entering and recovery refresh current filters, page and open detail without any writes', async t => {
  t.mock.timers.enable({ apis: ['setTimeout'] })
  const ctx = await setup(t, { active: false })
  assert.equal(calls.pages.length, 0)
  ctx.props.active = true; await flush()
  assert.equal(calls.pages.length, 1)
  ctx.state.changeTab('assets')
  ctx.state.query = '道路'; ctx.state.kind = 'geojson'; ctx.state.status = 'active'
  await flush(); t.mock.timers.tick(250); await flush()
  await ctx.state.setPage(3)
  await ctx.state.openDetail(asset.id)
  const pinned = { ...calls.pages.at(-1) }, before = calls.pages.length
  ctx.props.active = false; await flush()
  ctx.props.recovery++; ctx.props.revision++; await flush()
  assert.equal(calls.pages.length, before)
  ctx.props.active = true; await flush()
  assert.deepEqual(calls.pages.at(-1), pinned)
  assert.equal(ctx.state.page, 3)
  assert.equal(ctx.state.query, '道路')
  assert.equal(ctx.state.kind, 'geojson')
  assert.deepEqual(calls.detail, [asset.id, asset.id])
  ctx.props.recovery++; await flush()
  assert.deepEqual(calls.pages.at(-1), pinned)
  assert.equal(calls.detail.length, 3)
  assert.equal(calls.writes, 0)
})

test('overview shows real object and run totals and failed statistics leave asset rows visible', async t => {
  const ctx = await setup(t)
  assert.match(ctx.text(), /对象数量\s*8\s*个/)
  assert.match(ctx.text(), /运行次数\s*3\s*次/)
  statistics = async () => { throw new Error('无权限：统计读取受限 · trace_id: stats') }
  ctx.state.changeTab('assets'); await flush()
  assert.match(ctx.text(), /无权限查看综合统计/)
  assert.match(ctx.text(), /点位资产/)
  assert.doesNotMatch(ctx.text(), /资产目录加载失败|还没有资产/)
  const pages = calls.pages.length
  statistics = async () => ({ ...overview, run_count: 9 })
  await ctx.state.refreshStats(); await flush()
  assert.equal(calls.pages.length, pages)
  assert.match(ctx.text(), /运行次数\s*9\s*次/)
})

test('asset and registration empty states distinguish forbidden, failed, empty and filtered results', async t => {
  const ctx = await setup(t)
  assert.equal(ctx.state.tab, 'records')
  assert.match(ctx.text(), /图层登记\s*0.*场景\s*4.*资产目录\s*61/)
  ctx.props.catalogError = '无权限：目录读取受限'; await flush()
  assert.match(ctx.text(), /无权限查看图层登记/)
  assert.doesNotMatch(ctx.text(), /还没有图层登记/)
  ctx.props.catalogError = '目录加载失败'; await flush()
  assert.match(ctx.text(), /图层登记加载失败/)
  ctx.props.catalogError = ''; await flush()
  assert.match(ctx.text(), /还没有图层登记/)
  list = async () => { throw new Error('无权限：资产读取受限') }
  ctx.state.changeTab('assets'); await flush()
  assert.match(ctx.text(), /无权限查看资产目录/)
  assert.doesNotMatch(ctx.text(), /没有匹配的资产|还没有资产/)
  list = async () => { throw new Error('临时失败 · trace_id: assets') }
  await ctx.state.refresh(); await flush()
  assert.match(ctx.text(), /资产目录加载失败/)
  statistics = async () => ({ ...overview, asset_count: 0 })
  list = async query => ({ ...query, items: [], total: 0 })
  await ctx.state.refresh(); await flush()
  assert.match(ctx.text(), /还没有资产/)
  statistics = async () => overview
  await ctx.state.refresh(); await flush()
  assert.match(ctx.text(), /没有匹配的资产/)
  statistics = async () => { throw new Error('统计不可用') }
  ctx.state.query = '不存在的资产'
  await ctx.state.refresh(); await flush()
  assert.match(ctx.text(), /没有匹配的资产/)
  assert.doesNotMatch(ctx.text(), /还没有资产/)
  assert.equal(calls.writes, 0)
})


const elements = (node, matches) => [node, ...(node.children ?? []).flatMap(child => elements(child, matches))].filter(matches)

test('overview keeps four metrics with storage breakdown in collapsed details and labeled filters', async t => {
  statistics = async () => ({ ...overview, storage: { render_bytes: 2048, database_bytes: 3072, temporary_bytes: 1024 } })
  const ctx = await setup(t)
  const cards = elements(ctx.root, node => node.class?.split(' ').includes('stat-card'))
  assert.equal(cards.length, 4)
  assert.match(text(cards[0]), /资产数量61份近 7 天新增 2 份/)
  assert.match(text(cards[3]), /源资产容量100B/)
  const details = elements(ctx.root, node => node.class === 'stats-details')[0]
  assert.equal(details.open, undefined)
  const storage = elements(details, node => node.class === 'storage-card')[0]
  assert.match(text(storage), /源资产容量100 B/)
  assert.match(text(storage), /显示产物2.0 KB/)
  assert.match(text(storage), /数据库（含索引）3.0 KB/)
  assert.match(text(storage), /临时空间1.0 KB/)
  ctx.state.changeTab('assets'); await flush()
  const controls = elements(ctx.root, node => node.tagName === 'SELECT' || node.tagName === 'INPUT')
  for (const control of controls) {
    assert.equal(control.parent.tagName, 'LABEL')
    assert.ok(text(control.parent).replace(text(control), '').trim(), control['aria-label'])
  }
  const scroll = elements(ctx.root, node => node.class === 'table-scroll')[0]
  assert.equal(scroll.tabindex, '0')
  assert.match(scroll['aria-label'], /资产目录.*横向滚动/)
  assert.equal(calls.writes, 0)
})

test('overview shows zero values, grouped large counts and missing storage without inventing totals', async t => {
  statistics = async () => ({ ...overview, asset_count: 0, object_count: 1234567, run_count: 0, total_byte_size: 1024 ** 4, assets_by_type: {}, assets_added_last_7_days: 0, storage: null })
  const ctx = await setup(t)
  const cards = elements(ctx.root, node => node.class?.split(' ').includes('stat-card'))
  assert.match(text(cards[0]), /资产数量0份近 7 天新增 0 份/)
  assert.match(text(cards[1]), /1,234,567/)
  assert.match(text(cards[2]), /运行次数0次/)
  assert.match(text(cards[3]), /源资产容量1.0TB/)
  assert.match(ctx.text(), /显示产物暂不可用/)
  assert.equal(ctx.state.bytes(1024 ** 3), '1.0 GB')
  assert.equal(ctx.state.bytes(1024), '1.0 KB')
  assert.equal(ctx.state.bytes(0), '0 B')
  assert.equal(calls.writes, 0)
})

test('overview preserves metric placeholders while loading and offers retry after statistics fail', async t => {
  let resolveStats
  statistics = () => new Promise(resolve => { resolveStats = resolve })
  const ctx = await setup(t)
  assert.equal(elements(ctx.root, node => node.class?.split(' ').includes('stat-card')).length, 4)
  assert.match(ctx.text(), /正在读取综合统计/)
  resolveStats(overview); await flush()
  statistics = async () => { throw new Error('统计服务不可用') }
  await ctx.state.refreshStats(); await flush()
  assert.match(ctx.text(), /综合统计加载失败/)
  const retry = elements(ctx.root, node => node.tagName === 'BUTTON' && text(node) === '重试统计')[0]
  statistics = async () => overview
  await retry.onClick(); await flush()
  assert.equal(ctx.state.stats.asset_count, 61)
  assert.doesNotMatch(ctx.text(), /综合统计加载失败/)
})

test('visible upload edit and delete actions preserve their original events and records', async t => {
  const events = []
  const layer = { id: 'layer-one', name: '测试图层', category: 'POI', type: 'geojson', url: '/data/points.geojson', builtin: false }
  const ctx = await setup(t, { layers: [layer], onAdd: () => events.push(['add']), onEdit: value => events.push(['edit', value]), onDeleteRecord: value => events.push(['delete', value]) })
  const buttons = elements(ctx.root, node => node.tagName === 'BUTTON')
  for (const label of ['上传 / 登记数据', '编辑', '删除登记']) {
    const button = buttons.find(node => text(node).trim() === label)
    assert.ok(button, label)
    button.onClick()
  }
  assert.deepEqual(events, [['add'], ['edit', layer], ['delete', layer]])
  assert.equal(calls.writes, 0)
})
