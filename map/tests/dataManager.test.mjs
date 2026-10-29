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
mock.module('../src/api.ts', { exports: {
  ApiError: class extends Error {},
  getAssetPage: query => { calls.pages.push({ ...query }); return list(query) },
  getStats: () => { calls.statistics++; return statistics() },
  getAsset: async id => { calls.detail.push(id); return { ...asset, id, files: [], file_checksums: [] } },
  deleteAsset: async () => { calls.writes++ }, reconcileAssets: async () => { calls.writes++; return { discovered: 0 } },
} })

const filename = new URL('../src/components/DataManagerView.vue', import.meta.url)
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
  return `import ${binding} from '${new URL('../src/' + specifier.slice(3) + '.ts', import.meta.url).href}';`
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
  return { state: app._instance.setupState, props: app._instance.props, text: () => text(root) }
}

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
  assert.match(ctx.text(), /对象\s*8\s*个/)
  assert.match(ctx.text(), /运行\s*3\s*次/)
  statistics = async () => { throw new Error('无权限：统计读取受限 · trace_id: stats') }
  ctx.state.changeTab('assets'); await flush()
  assert.match(ctx.text(), /无权限查看综合统计/)
  assert.match(ctx.text(), /点位资产/)
  assert.doesNotMatch(ctx.text(), /资产目录加载失败|还没有资产/)
  const pages = calls.pages.length
  statistics = async () => ({ ...overview, run_count: 9 })
  await ctx.state.refreshStats(); await flush()
  assert.equal(calls.pages.length, pages)
  assert.match(ctx.text(), /运行\s*9\s*次/)
})

test('asset and registration empty states distinguish forbidden, failed, empty and filtered results', async t => {
  const ctx = await setup(t)
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
