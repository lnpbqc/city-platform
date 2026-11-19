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
  const { component, cleanup } = await setup('layers/LayerPanel', 'visibleLayers, groups', props)
  t.after(cleanup)
  assert.deepEqual(component.visibleLayers.value.map(layer => layer.id), ['roads'])
  assert.equal(component.groups.value.some(group => group.category === '底图'), false)
  props.layers = [...layers, { ...layers[1], id: 'user-map', category: '底图', name: '登记地图服务' }]
  assert.deepEqual(component.groups.value.find(group => group.category === '底图').layers.map(layer => layer.id), ['user-map'])
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
