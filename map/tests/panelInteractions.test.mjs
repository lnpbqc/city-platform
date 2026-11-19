import { test } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { compileScript, parse } from 'vue/compiler-sfc'
import ts from 'typescript'
import * as vue from 'vue'
import * as temporal from '../src/temporal/temporal.ts'
import * as poi from '../src/map/poi.ts'
import * as weather from '../src/map/weather.ts'
import * as regions from '../src/map/regions.ts'

function component(name) {
  const { descriptor } = parse(readFileSync(new URL(`../src/components/${name === 'TimeAxis' ? 'common' : 'map'}/${name}.vue`, import.meta.url), 'utf8'))
  const source = compileScript(descriptor, { id: name, inlineTemplate: true }).content
  const js = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 } }).outputText
  const exports = {}
  new Function('require', 'exports', js)(path => {
    if (path === 'vue') return vue
    if (path === '../../temporal/temporal') return temporal
    if (path === '../../map/poi') return poi
    if (path === '../../map/weather') return weather
    if (path === '../../map/regions') return regions
    if (path.endsWith('UiTooltip.vue')) return { inheritAttrs: false, setup: (_props, { slots }) => () => slots.default?.() }
    if (path === './FeatureInspector.vue') return component('FeatureInspector')
    if (path === '@lucide/vue') return new Proxy({}, { get: () => () => null })
    throw new Error(path)
  }, exports)
  return exports.default
}
const walk = n => [n, ...(n.children ?? []).flatMap(walk)]
const text = n => `${n.text ?? ''}${(n.children ?? []).map(text).join('')}`
const components = { ObjectPanel: component('ObjectPanel'), TimeAxis: component('TimeAxis'), WeatherControl: component('WeatherControl'), DisplayRegionPanel: component('DisplayRegionPanel'), RegionPicker: component('RegionPicker') }
const label = value => n => n.props['aria-label'] === value
const cls = value => n => String(n.props.class).split(' ').includes(value)
const tick = async () => { await vue.nextTick(); await vue.nextTick() }
function mount(name, initial, handlers = {}) {
  let focused
  const documentListeners = new Map()
  const ownerDocument = {
    addEventListener: (name, callback) => documentListeners.set(name, callback),
    removeEventListener: name => documentListeners.delete(name),
  }
  const node = tag => ({
    tag, props: {}, children: [], style: {}, dataset: {}, scrollTop: 0, listeners: {}, ownerDocument,
    get isConnected() { return Boolean(this.parent) },
    get options() { return this.children.filter(child => child.tag === 'option') },
    focus() { focused = this },
    contains(other) { return walk(vue.toRaw(this)).includes(vue.toRaw(other)) },
    addEventListener(event, handler) { this.listeners[event] = handler },
    getRootNode() { return { activeElement: focused } },
    querySelectorAll() { return walk(this).filter(n => n.props['data-object-id']) },
  })
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
  return { props, root, events, documentListeners, node, pointerDown: target => documentListeners.get('pointerdown')?.({ target }),
    focused: () => vue.toRaw(focused), find: fn => walk(root).find(fn), close: () => app.unmount() }
}

test('region picker defaults to display regions and separates administrative location with keyboard navigation', async t => {
  const catalogRequest = t.mock.method(globalThis, 'fetch', async () => ({ ok: true, json: async () => ({
    retrievedAt: '2026-10-22', regions: [{ id: '440000', parent: '100000', name: '广东省', level: 'province', longitude: 113, latitude: 23 }],
  }) }))
  const ctx = mount('RegionPicker', { selected: regions.demoRegion, sidebar: false, boundaryState: { status: 'idle' }, boundaryEnabled: false }, { onOpen() {}, onSelect() {} })
  t.after(ctx.close)
  const trigger = ctx.find(label('选择中国城市和地区'))
  trigger.props.onClick(); await tick()
  const tablist = ctx.find(n => n.props.role === 'tablist')
  const displayTab = ctx.find(n => n.props.role === 'tab' && text(n) === '展示区域')
  const adminTab = ctx.find(n => n.props.role === 'tab' && text(n) === '行政区定位')
  const panel = tab => ctx.find(n => n.props.id === tab.props['aria-controls'])
  assert.ok(tablist && displayTab && adminTab)
  assert.equal(displayTab.props['aria-selected'], true)
  assert.equal(ctx.focused(), displayTab)
  assert.equal(panel(adminTab).style.display, 'none')
  assert.equal(catalogRequest.mock.callCount(), 0)

  const key = async key => {
    let prevented = false
    tablist.props.onKeydown({ key, preventDefault() { prevented = true } }); await tick()
    assert.equal(prevented, true)
  }
  await key('ArrowRight')
  await tick()
  assert.equal(adminTab.props['aria-selected'], true)
  assert.equal(ctx.focused(), adminTab)
  assert.equal(panel(displayTab).style.display, 'none')
  assert.equal(catalogRequest.mock.callCount(), 1)
  const search = ctx.find(label('搜索中国地区'))
  assert.equal(ctx.find(label('选择省级地区')).options[1].text, '广东省')
  assert.equal(walk(panel(adminTab)).filter(cls('map-panel-scroll')).length, 1)
  assert.equal(panel(adminTab).props.tabindex, '0')
  search.value = '440000'; search.listeners.input({ target: search }); await tick()
  assert.match(text(panel(adminTab)), /找到 1 个地区/)
  assert.equal(ctx.find(label('选择省级地区')), undefined)

  panel(adminTab).scrollTop = 80
  await key('Home')
  assert.equal(ctx.focused(), displayTab)
  await key('End')
  assert.equal(ctx.focused(), adminTab)
  assert.equal(panel(adminTab).scrollTop, 80)
  const national = ctx.find(n => n.tag === 'button' && text(n) === '全国概览')
  national.props.onClick(); await tick()
  assert.deepEqual(ctx.events, [['onOpen'], ['onSelect', regions.chinaRegion]])
  assert.equal(ctx.find(n => n.props.role === 'tablist'), undefined)
  assert.equal(ctx.focused(), trigger)
  trigger.props.onClick(); await tick()
  assert.equal(ctx.find(n => n.props.role === 'tab' && text(n) === '展示区域').props['aria-selected'], true)
})

test('region picker reports both opening and closing so narrow panels can restore', async t => {
  const ctx = mount('RegionPicker', { selected: regions.demoRegion, sidebar: false, boundaryState: { status: 'idle' }, boundaryEnabled: false }, { 'onUpdate:open'() {} })
  t.after(ctx.close)
  ctx.find(label('选择中国城市和地区')).props.onClick()
  await tick()
  ctx.find(label('关闭地区选择')).props.onClick()
  await tick()
  assert.deepEqual(ctx.events, [['onUpdate:open', true], ['onUpdate:open', false]])
})

test('display regions open and manage independently, with one disclosure and Escape focus return', async t => {
  const first = { id: 'first', name: '一个在窄屏上会截断的展示区域名称' }
  const second = { id: 'second', name: '第二个区域' }
  const ctx = mount('DisplayRegionPanel', {
    regions: [first, second], loading: false, loadError: '', capture: () => null, save: async () => {}, remove: async () => {},
  }, { onOpen() {} })
  t.after(ctx.close)
  const one = ctx.find(label(`管理${first.name}`))
  const two = ctx.find(label(`管理${second.name}`))
  const locate = ctx.find(n => n.props.title === first.name)
  assert.equal(one.tag, 'button')
  assert.equal(one.props['aria-expanded'], false)
  one.props.onClick({ currentTarget: one })
  await tick()
  assert.equal(one.props['aria-expanded'], true)
  assert.equal(ctx.find(n => n.props.id === one.props['aria-controls']).parent, one.parent.parent)
  assert.deepEqual(ctx.events, [])
  two.props.onClick({ currentTarget: two })
  await tick()
  assert.equal(one.props['aria-expanded'], false)
  assert.equal(two.props['aria-expanded'], true)
  const panel = ctx.find(label('展示区域'))
  assert.equal(walk(panel).filter(cls('map-panel-scroll')).length, 1)
  assert.equal(ctx.find(cls('display-heading')).parent, panel)
  assert.equal(ctx.find(cls('display-region-body')).props.tabindex, '0')
  let stopped = false
  panel.props.onKeydown({ key: 'Escape', stopPropagation() { stopped = true } })
  await tick()
  assert.equal(stopped, true)
  assert.equal(two.props['aria-expanded'], false)
  assert.equal(ctx.focused(), two)
  locate.props.onClick()
  assert.deepEqual(ctx.events.map(([action, region]) => [action, region.id]), [['onOpen', first.id]])
})

test('display region controls save, rename, update and confirm deletion', async t => {
  const region = { id: 'one', name: '旧名称' }
  const view = { latitude: 23, longitude: 114, radius_m: 1000, camera: {} }
  const saved = [], removed = []
  const ctx = mount('DisplayRegionPanel', {
    regions: [region], loading: false, loadError: '', capture: () => view,
    save: async (body, id) => saved.push([body, id]), remove: async id => removed.push(id),
  })
  t.after(ctx.close)
  const click = title => ctx.find(n => n.tag === 'button' && text(n).trim() === title).props.onClick()
  const submit = async title => {
    await tick()
    const field = ctx.find(n => n.tag === 'input')
    assert.equal(ctx.focused(), field)
    field.value = title
    field.listeners.input({ target: field })
    await tick()
    ctx.find(n => n.tag === 'form').props.onSubmit({ preventDefault() {} })
    await tick()
  }
  const manage = async () => {
    const trigger = ctx.find(label('管理旧名称'))
    if (!trigger.props['aria-expanded']) trigger.props.onClick({ currentTarget: trigger })
    await tick()
  }
  click('保存当前视角')
  await submit('新区域')
  await manage()
  click('改名')
  await submit('新名称')
  await manage()
  click('更新为当前视角')
  await tick()
  await manage()
  click('删除')
  await tick()
  assert.deepEqual(removed, [])
  assert.equal(ctx.focused().text, '取消')
  ctx.find(label('展示区域')).props.onKeydown({ key: 'Escape', stopPropagation() {} })
  await tick()
  assert.equal(ctx.focused(), ctx.find(label('管理旧名称')))
  assert.equal(ctx.find(n => n.tag === 'button' && text(n) === '确认删除'), undefined)
  await manage()
  click('删除')
  await tick()
  click('确认删除')
  await tick()
  assert.deepEqual(saved, [[{ ...view, name: '新区域' }, undefined], [{ name: '新名称' }, 'one'], [view, 'one']])
  assert.deepEqual(removed, ['one'])
})

test('weather selector can override automatic weather and history shows the saved source', async t => {
  const ctx = mount('WeatherControl', { compact: true, mode: 'auto', status: 'ready', region: '黄埔校区', weather: {
    source: 'open-meteo', effect: 'rain', reading: { code: 61, valid_at: '2026-01-01T00:15:00Z' },
  } }, { 'onUpdate:mode': mode => { ctx.props.mode = mode } })
  t.after(ctx.close)
  const button = ctx.find(label('天气设置'))
  assert.equal(button.props['aria-expanded'], false)
  button.props.onClick()
  await tick()
  assert.equal(button.props['aria-expanded'], true)
  assert.match(text(ctx.root), /黄埔校区 · 小雨.*08:15.*Open-Meteo/)
  const select = ctx.find(label('天气模式'))
  assert.deepEqual(select.children.filter(node => node.tag === 'option').map(node => node.props.value), ['auto', 'clear', 'cloudy', 'overcast', 'fog', 'rain', 'snow', 'thunderstorm'])
  select.props.onChange({ target: { value: 'snow' } })
  await tick()
  assert.equal(ctx.props.mode, 'snow')
  ctx.props.fixed = true
  await tick()
  assert.equal(ctx.find(label('天气模式')), undefined)
  assert.match(text(ctx.root), /运行天气 · 小雨/)
})

test('compact weather shows overcast accurately and dismisses settings without stealing outside focus', async t => {
  const ctx = mount('WeatherControl', { compact: true, mode: 'auto', status: 'ready', region: '一个完整的很长的展示区域名称', weather: {
    source: 'open-meteo', effect: 'none', reading: { code: 3, is_day: true, valid_at: '2026-11-19T07:00:00Z' },
  } })
  t.after(() => { ctx.close(); assert.equal(ctx.documentListeners.size, 0) })
  const button = ctx.find(label('天气设置'))
  const content = ctx.find(label('天气设置内容'))
  assert.match(text(button), /一个完整的很长的展示区域名称.*阴.*自动/)
  assert.equal(content.style.display, 'none')
  button.props.onClick(); await tick()
  assert.notEqual(content.style.display, 'none')
  assert.match(text(content), /一个完整的很长的展示区域名称.*阴.*15:00.*Open-Meteo/)
  ctx.pointerDown(ctx.find(label('天气模式'))); await tick()
  assert.equal(button.props['aria-expanded'], true)
  const outside = ctx.node('button')
  outside.focus()
  ctx.pointerDown(outside); await tick()
  assert.equal(button.props['aria-expanded'], false)
  assert.equal(ctx.focused(), outside)
  button.props.onClick(); await tick()
  button.props.onClick(); await tick()
  assert.equal(button.props['aria-expanded'], false)
  assert.equal(ctx.documentListeners.size, 0)
  button.props.onClick(); await tick()
  ctx.find(label('关闭天气设置')).props.onClick(); await tick()
  assert.equal(ctx.focused(), button)
  button.props.onClick(); await tick()
  ctx.find(label('地图天气')).props.onKeydown({ key: 'Escape', stopPropagation() {}, preventDefault() {} })
  await tick()
  assert.equal(button.props['aria-expanded'], false)
  assert.equal(ctx.focused(), button)
})

test('manual and saved weather summaries use their snapshot instead of the current automatic mode', async t => {
  const ctx = mount('WeatherControl', { compact: true, mode: 'auto', fixed: true, status: 'ready', weather: { source: 'manual', effect: 'thunderstorm' } })
  t.after(ctx.close)
  assert.match(text(ctx.find(label('天气设置'))), /运行天气.*雷雨.*手动/)
  assert.equal(ctx.find(label('天气模式')), undefined)
})

test('weather status distinguishes an uncovered view, throttling and an earlier reading', async t => {
  const ctx = mount('WeatherControl', { compact: true, mode: 'auto', status: 'outside', weather: weather.noWeather })
  t.after(ctx.close)
  const button = ctx.find(label('天气设置'))
  assert.match(text(button), /未进入展示区域/)
  ctx.props.status = 'loading'
  await tick()
  assert.match(text(button), /正在查询天气/)
  ctx.props.status = 'limited'
  ctx.props.region = '香港维港'
  ctx.props.reference = { code: 61, valid_at: '2026-01-01T00:15:00Z' }
  await tick()
  assert.match(text(button), /天气服务限流/)
  button.props.onClick(); await tick()
  assert.match(text(ctx.root), /香港维港 · 天气服务限流.*上次更新.*小雨.*08:15/)
  ctx.props.status = 'unavailable'
  await tick()
  assert.match(text(button), /天气暂不可用/)
  assert.match(text(ctx.find(label('天气设置内容'))), /上次更新.*小雨/)
})

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

test('3D model details show basic fields before collapsed picked properties, even after loading', async t => {
  const raw = { title: '三维对象', layerName: '校园模型', resourceType: '3dtiles', objectId: 'asset-object',
    properties: { 名称: '教学楼 A', 用途: '教学', 层数: 4 }, detailLoading: true }
  const ctx = mount('ObjectPanel', { layers: [], items: [], total: 0, page: 1, pageSize: 20, layerId: '', q: '', type: '', selectedId: '', selection: raw, loading: false, error: '', area: false, drawing: null, progress: null })
  t.after(ctx.close)
  const detail = () => text(ctx.find(cls('object-details')))
  assert.match(detail(), /教学楼 A.*校园模型.*原始属性.*用途教学.*层数4/)
  ctx.props.selection = { ...raw, detailLoading: false, object: { name: '整个校园', object_id: 'asset-object',
    type: 'model', height_m: 18, semantic_source: 'geometry_model', coordinates: [113, 23],
    asset: { asset_id: 'campus', version: '1' }, properties: { 名称: '整个校园', 备注: '资产属性' } } }
  await tick()
  assert.match(detail(), /教学楼 A.*类型model.*高度18 m.*所属图层校园模型.*来源几何模型.*等级.*置信度.*WGS84坐标.*资产版本campus@1.*原始几何.*object_idasset-object.*原始属性.*用途教学.*层数4/)
  const disclosure = ctx.find(n => n.tag === 'details' && text(n).includes('原始属性'))
  assert.ok(disclosure)
  assert.equal(disclosure.props.open, undefined)
  assert.equal(detail().match(/教学楼 A/g)?.length, 1)
  assert.doesNotMatch(detail(), /整个校园|资产属性/)
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
