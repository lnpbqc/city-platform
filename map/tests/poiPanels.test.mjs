import { test } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { parse, compileScript } from 'vue/compiler-sfc'
import { renderToString } from 'vue/server-renderer'
import * as vue from 'vue'
import ts from 'typescript'
import * as poi from '../src/poi.ts'

function component(name) {
  const { descriptor } = parse(readFileSync(new URL(`../src/components/${name}.vue`, import.meta.url), 'utf8'))
  const source = compileScript(descriptor, { id: name, inlineTemplate: true }).content
  const script = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 } }).outputText
  const exports = {}
  new Function('require', 'exports', script)(name => name === 'vue' ? vue : name === '../poi' ? poi : undefined, exports)
  return exports.default
}
test('POI card emphasizes place information and collapses raw and technical fields', async () => {
  const html = await renderToString(vue.createSSRApp(component('PoiDetails'), {
    selection: { title: '咖啡店', layerName: '商店', properties: { name: '咖啡店', category: '餐饮', address: '测试路', phone: '12345', opening_hours: '09:00-18:00' }, object: { object_id: 'point-1', coordinates: [121, 25], asset: { asset_id: 'asset', version: '1' } } }, distance: 125,
  }))
  assert.match(html, /POI 详情/)
  assert.match(html, /125 m/)
  assert.match(html, /咖啡店/)
  assert.match(html, /测试路/)
  assert.match(html, /12345/)
  assert.match(html, /<details[^>]*>/)
  assert.doesNotMatch(html, /<details[^>]*\sopen/)
  assert.doesNotMatch(html, /置信度|高度/)
})
test('nearby panel distinguishes empty, loading, failure and unavailable layers', async () => {
  const panel = component('NearbyPoiPanel')
  const base = { items: [], layers: [{ id: 'external', name: '外部地点' }], loading: false, error: '', unavailable: [] }
  const render = props => renderToString(vue.createSSRApp(panel, { ...base, ...props }))
  assert.match(await render({}), /1 公里内暂无 POI/)
  assert.match(await render({ loading: true }), /正在查询/)
  assert.match(await render({ error: '服务离线' }), /服务离线/)
  assert.match(await render({ unavailable: ['external'] }), /外部地点.*本地索引/)
})
