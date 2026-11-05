import { test } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { compileScript, parse } from 'vue/compiler-sfc'
import ts from 'typescript'
import * as vue from 'vue'
import * as temporal from '../src/temporal.ts'
import * as poi from '../src/poi.ts'

function component(name) {
  const { descriptor } = parse(readFileSync(new URL(`../src/components/${name}.vue`, import.meta.url), 'utf8'))
  const source = compileScript(descriptor, { id: name, inlineTemplate: true }).content
  const js = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 } }).outputText
  const exports = {}
  new Function('require', 'exports', js)(path => {
    if (path === 'vue') return vue
    if (path === '../temporal') return temporal
    if (path === '../poi') return poi
    if (path === './FeatureInspector.vue') return component('FeatureInspector')
    if (path === '@lucide/vue') return new Proxy({}, { get: () => () => null })
    throw new Error(path)
  }, exports)
  return exports.default
}
const walk = n => [n, ...(n.children ?? []).flatMap(walk)]
const text = n => `${n.text ?? ''}${(n.children ?? []).map(text).join('')}`
const components = { ObjectPanel: component('ObjectPanel'), TimeAxis: component('TimeAxis') }
const label = value => n => n.props['aria-label'] === value
const cls = value => n => String(n.props.class).split(' ').includes(value)
const tick = async () => { await vue.nextTick(); await vue.nextTick() }
function mount(name, initial, handlers = {}) {
  let focused
  const node = tag => ({ tag, props: {}, children: [], style: {}, dataset: {}, scrollTop: 0, focus() { focused = this }, querySelectorAll() { return walk(this).filter(n => n.props['data-object-id']) } })
  const renderer = vue.createRenderer({
    createElement: node, createText: text => ({ ...node('#text'), text }), createComment: () => node('#comment'),
    setText: (n, t) => { n.text = t }, setElementText: (n, t) => { n.text = t; n.children = [] },
    patchProp(n, k, _old, v) { n.props[k] = v; if (k === 'style') Object.assign(n.style, v); if (k === 'data-object-id') n.dataset.objectId = v },
    insert(n, p, a) { if (n.parent) n.parent.children.splice(n.parent.children.indexOf(n), 1); n.parent = p; const i = p.children.indexOf(a); p.children.splice(i < 0 ? p.children.length : i, 0, n) },
    remove(n) { if (n.parent) n.parent.children.splice(n.parent.children.indexOf(n), 1) },
    parentNode: n => n.parent, nextSibling: n => n.parent?.children[n.parent.children.indexOf(n) + 1] ?? null,
  })
  const props = vue.reactive(initial), root = node('root'), events = []
  const app = renderer.createApp({ render: () => vue.h(components[name], { ...props, ...Object.fromEntries(Object.entries(handlers).map(([key, fn]) => [key, (...args) => { events.push([key, ...args]); fn(...args) }])) }) })
  app.mount(root)
  return { props, root, events, focused: () => focused, find: fn => walk(root).find(fn), close: () => app.unmount() }
}

test('results enter loading details; return preserves filters, range, page, scroll and keyboard focus', async t => {
  const item = { object_id: 'one', name: '教学楼', type: 'building' }
  const ctx = mount('ObjectPanel', { layers: [{ id: 'a', name: '建筑' }], layerId: 'a', items: [item], total: 50, page: 2, pageSize: 20, loading: false, error: '', q: '教学', type: 'building', selectedId: '', selection: null, area: true, drawing: null, progress: null }, {
    onSelect: item => { ctx.props.selectedId = item.object_id; ctx.props.selection = { title: item.name, layerId: 'a', objectId: item.object_id, layerName: '建筑', properties: {}, detailLoading: true } },
    onClearSelection: () => { ctx.props.selectedId = ''; ctx.props.selection = null },
  })
  t.after(ctx.close)
  const results = ctx.find(cls('object-results')), row = ctx.find(n => n.props['data-object-id'] === 'one')
  results.scrollTop = 180
  row.props.onClick(); await tick()
  assert.equal(results.style.display, 'none')
  assert.match(text(ctx.root), /正在读取原始对象详情/)
  assert.equal(ctx.find(n => n.tag === 'h2').text, '对象详情')
  assert.equal(ctx.find(label('关闭属性面板')), undefined)
  const back = ctx.find(cls('object-back'))
  assert.equal(vue.toRaw(ctx.focused()), back)
  back.props.onClick(); await tick()
  assert.notEqual(results.style.display, 'none')
  assert.equal(results.scrollTop, 180)
  assert.deepEqual([ctx.props.q, ctx.props.type, ctx.props.page, ctx.props.area], ['教学', 'building', 2, true])
  assert.equal(vue.toRaw(ctx.focused()), row)
  assert.equal(ctx.find(cls('object-details')), undefined)
})

test('map-picked raw models show details and resource invalidation returns to results', async t => {
  const ctx = mount('ObjectPanel', { layers: [], items: [], total: 0, page: 1, pageSize: 20, layerId: '', q: '', type: '', selectedId: '', selection: null, loading: false, error: '', area: false, drawing: null, progress: null })
  t.after(ctx.close)
  ctx.props.selection = { title: '地图对象', layerName: '模型', properties: {}, resourceType: '3dtiles' }; await tick()
  assert.match(text(ctx.find(cls('object-details'))), /未携带语义属性/)
  ctx.props.selection = null; await tick()
  assert.equal(ctx.find(cls('object-details')), undefined)
  assert.notEqual(ctx.find(cls('object-results')).style.display, 'none')
})

const timeProps = () => ({ time: '2026-10-25T00:00:00Z', resolution: 'hour', rate: 2, playing: true, maximum: 1, position: 0, times: ['2026-10-25T00:00:00Z', '2026-10-25T01:00:00Z'], loading: false, metadataLoading: false, allMissing: false, counts: [{ id: 'a', name: '积水', total: 3, missing: 0 }], errors: {} })
test('time settings collapse without resetting playback; core controls and settings emit their values', async t => {
  const ctx = mount('TimeAxis', timeProps(), { onPause() {}, onStep() {}, onSeek() {}, 'onUpdate:resolution'() {}, 'onUpdate:rate'() {}, onSelect() {} })
  t.after(ctx.close)
  const details = ctx.find(cls('time-details'))
  assert.equal(details.style.display, 'none')
  ctx.find(label('展开时间设置')).props.onClick(); await tick()
  assert.notEqual(details.style.display, 'none')
  assert.equal(ctx.find(label('收起时间设置')).props['aria-expanded'], true)
  ctx.find(label('下一个专题时次')).props.onClick()
  ctx.find(label('专题时间进度')).props.onInput({ target: { value: '1' } })
  ctx.find(label('专题时次分辨率')).props.onChange({ target: { value: 'day' } })
  ctx.find(label('时间轴速率')).props.onChange({ target: { value: '5' } })
  ctx.find(label('选择专题北京时间')).props.onChange({ target: { value: '2026-10-25T09:00' } })
  ctx.find(label('收起时间设置')).props.onClick(); await tick()
  assert.equal(details.style.display, 'none')
  assert.equal(ctx.props.playing, true)
  assert.equal(ctx.props.time, '2026-10-25T00:00:00Z')
  assert.deepEqual(ctx.events, [['onStep', 1], ['onSeek', 1], ['onUpdate:resolution', 'day'], ['onUpdate:rate', 5], ['onSelect', '2026-10-25T01:00:00.000Z']])
})

test('missing, loading and errors remain in compact bars; two views expand independently', async t => {
  const left = mount('TimeAxis', timeProps()), right = mount('TimeAxis', timeProps())
  t.after(left.close); t.after(right.close)
  left.props.allMissing = true; await tick()
  assert.match(text(left.find(cls('time-status'))), /缺测/)
  left.props.loading = true; await tick()
  assert.match(text(left.find(cls('time-status'))), /正在读取/)
  left.props.errors = { a: '网络错误' }; await tick()
  assert.equal(left.find(cls('time-status')).props.role, 'alert')
  left.find(cls('status-action')).props.onClick(); await tick()
  assert.notEqual(left.find(cls('time-details')).style.display, 'none')
  assert.equal(right.find(cls('time-details')).style.display, 'none')
  assert.match(text(left.find(cls('time-details'))), /积水：网络错误/)
})
