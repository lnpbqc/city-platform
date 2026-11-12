import { test } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { parse } from 'vue/compiler-sfc'
import ts from 'typescript'
import * as vue from 'vue'
import * as poi from '../src/map/poi.ts'
import * as tree from '../src/layers/layerTree.ts'

const { descriptor } = parse(readFileSync(new URL('../src/components/layers/LayerDialog.vue', import.meta.url), 'utf8'))
const source = ts.transpileModule(descriptor.scriptSetup.content, { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 } }).outputText
const create = new Function('require', 'defineProps', 'defineEmits', 'exports', source + '\nreturn { categoryChoice, newCategory, category, availableCategories, kind, file, error, selectFile, submit }')
function setup() {
  const calls = [], events = []
  const dialog = create(name => {
    if (name === 'vue') return { ...vue, onMounted() {}, onBeforeUnmount() {} }
    if (name === '../../map/poi') return poi
    if (name === '../../layers/layerTree') return tree
    if (name === '@lucide/vue') return {}
    if (name === '../../api/api') return { uploadLayer: async body => { calls.push(body); return { id: 'saved' } } }
    throw Error(name)
  }, () => ({ categories: ['社区设施', '社区设施'] }), () => (...event) => events.push(event), {})
  return { dialog, calls, events }
}
test('category options reuse saved categories; only a valid submitted new name is persisted', async () => {
  const { dialog, calls, events } = setup()
  assert.equal(dialog.availableCategories.value.filter(value => value === '社区设施').length, 1)
  dialog.categoryChoice.value = '__new_category__'
  dialog.newCategory.value = '   '
  await dialog.submit()
  assert.match(dialog.error.value, /分类名称/)
  assert.equal(calls.length, 0)
  dialog.newCategory.value = ' 社区设施 '
  dialog.file.value = new File(['{}'], 'points.geojson')
  await dialog.submit()
  assert.equal(calls[0].get('category'), '社区设施')
  assert.equal(events[0][0], 'saved')
})
test('GeoJSON accepts exactly 1 GiB and rejects one byte more; ZIP is capped at 10 GiB', async () => {
  const { dialog, calls } = setup()
  const chosen = size => { const file = new File(['{}'], 'points.geojson'); Object.defineProperty(file, 'size', { value: size }); return file }
  dialog.selectFile({ target: { files: [chosen(1073741825)] } })
  await dialog.submit()
  assert.match(dialog.error.value, /上限/)
  assert.equal(calls.length, 0)
  dialog.selectFile({ target: { files: [chosen(1073741824)] } })
  await dialog.submit()
  assert.equal(calls.length, 1)
  dialog.kind.value = '3dtiles'
  dialog.selectFile({ target: { files: [chosen(10 * 1024 ** 3 + 1)] } })
  assert.match(dialog.error.value, /10240/)
})
