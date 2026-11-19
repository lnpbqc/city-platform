import { test } from 'node:test'
import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import { parse } from 'vue/compiler-sfc'
import ts from 'typescript'
import * as vue from 'vue'
import * as tree from '../src/layers/layerTree.ts'

async function setup(file, exports, props) {
  const { descriptor } = parse(await readFile(new URL(`../src/components/${file}.vue`, import.meta.url), 'utf8'))
  const code = ts.transpileModule(descriptor.scriptSetup.content, { compilerOptions: { module: ts.ModuleKind.CommonJS } }).outputText
  const scope = vue.effectScope()
  const component = scope.run(() => new Function('require', 'defineProps', 'defineEmits', 'exports', code + `\n return { ${exports} }`)(name => {
    if (name === 'vue') return { ...vue, onMounted() {} }
    if (name === '../../layers/layerTree') return tree
    return {}
  }, () => props, () => () => {}, {}))
  return { component, cleanup: () => scope.stop() }
}
const layers = [
  { id: 'basemap', name: '底图', category: '底图', builtin: true, attached: true, status: 'ready' },
  { id: 'roads', name: '道路', category: '道路', builtin: false, attached: true, status: 'ready' },
]

test('panel hides the internal basemap and its empty group, but keeps user map services', async t => {
  const props = vue.reactive({ layers, filter: 'all' })
  const { component, cleanup } = await setup('layers/LayerPanel', 'visibleLayers, groups, search, folded, toggleGroup', props)
  t.after(cleanup)
  assert.deepEqual(component.visibleLayers.value.map(layer => layer.id), ['roads'])
  assert.equal(component.groups.value.some(group => group.category === '底图'), false)
  assert.deepEqual(component.groups.value.map(group => group.category), ['道路'])
  props.layers = [...layers, { ...layers[1], id: 'user-map', category: '底图', name: '登记地图服务' }]
  assert.deepEqual(component.groups.value.find(group => group.category === '底图').layers.map(layer => layer.id), ['user-map'])
  component.toggleGroup('道路')
  component.search.value = '登记'
  assert.deepEqual(component.groups.value.map(group => group.category), ['底图'])
  component.search.value = ''
  assert.equal(component.folded.value.has('道路'), true)
  component.search.value = '不存在'
  assert.deepEqual(component.groups.value, [])
  component.search.value = ''
  props.layers = [...layers, { ...layers[1], id: 'buildings', name: '建筑', category: '建筑', builtin: true },
    { ...layers[1], id: 'detached', category: '专题', attached: false }]
  assert.deepEqual(component.groups.value.map(group => group.category), ['建筑', '道路'])
  props.filter = 'mine'
  assert.deepEqual(component.groups.value.map(group => group.category), ['道路'])
  assert.equal(component.folded.value.has('道路'), true)
})

test('layer chooser excludes the internal basemap from samples without hiding custom services', async t => {
  const { component, cleanup } = await setup('layers/LayerChooser', 'filtered, tab', { layers })
  t.after(cleanup)
  assert.deepEqual(component.filtered.value.map(layer => layer.id), ['roads'])
  component.tab.value = 'samples'
  assert.deepEqual(component.filtered.value, [])
})

test('map status counts business layers without counting the internal basemap', async t => {
  const { component, cleanup } = await setup('map/MapStatus', 'loadedCount', { layers })
  t.after(cleanup)
  assert.equal(component.loadedCount.value, 1)
})

test('status coordinates prefer the pointer, fall back to the visible center and preserve zeros', async t => {
  const props = vue.reactive({ layers, navigation: null })
  const { component, cleanup } = await setup('map/MapStatus', 'coordinateText, coordinateSource', props)
  t.after(cleanup)
  assert.equal(component.coordinateText.value, '暂无地面坐标')
  assert.equal(component.coordinateSource.value, '中心')
  props.navigation = { pointer: null, center: { longitude: 113.4, latitude: 23.1, height: -2 } }
  assert.equal(component.coordinateText.value, '113.400000°, 23.100000° · 椭球高 -2.0 m')
  props.navigation.pointer = { longitude: 0, latitude: 0, height: 0 }
  assert.equal(component.coordinateSource.value, '鼠标')
  assert.equal(component.coordinateText.value, '0.000000°, 0.000000° · 椭球高 0.0 m')
  props.navigation.pointer = null
  assert.equal(component.coordinateSource.value, '中心')
  assert.match(component.coordinateText.value, /^113\.400000°/)
  props.navigation.center = null
  props.navigation.camera = { longitude: 114, latitude: 24, height: 1000 }
  assert.equal(component.coordinateText.value, '暂无地面坐标', 'camera position must not replace ground coordinates')
})
