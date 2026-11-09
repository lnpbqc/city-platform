import { test } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { parse } from 'vue/compiler-sfc'
import ts from 'typescript'
import * as vue from 'vue'
import * as poi from '../src/poi.ts'

const { descriptor } = parse(readFileSync(new URL('../src/components/PoiEditor.vue', import.meta.url), 'utf8'))
const script = ts.transpileModule(descriptor.scriptSetup.content, {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
}).outputText
const create = new Function('require', 'defineProps', 'defineEmits', 'defineExpose', 'exports',
  script + '\nreturn { save, name, category, address, conflict, error, busy }')
class ApiError extends Error {
  constructor(message, code) { super(message); this.code = code }
}
const feature = (name, coordinates) => ({
  type: 'Feature', id: name, geometry: { type: 'Point', coordinates },
  properties: { name, category: '餐饮', source: '外部导入', untouched: { keep: true } },
})

function setup({ moved = false, fail = false } = {}) {
  const original = feature('原有点', [121, 25, 12])
  original.bbox = [121, 25, 121, 25]
  const document = { type: 'FeatureCollection', bbox: [121, 25, 122, 26],
    copyright: '保留来源', features: [original, feature('第二个点', [122, 26])] }
  const calls = [], events = []
  const props = vue.reactive({
    layers: [], layer: { id: 'layer', asset_id: 'asset', asset_version: '1.0.0', url: '/original.geojson' },
    object: { object_id: 'point-id', name: '原有点', properties: original.properties, geometry: original.geometry, coordinates: original.geometry.coordinates, feature_index: 0 },
    coordinates: moved ? [121.5, 25.5] : undefined,
  })
  const editor = create(name => {
    if (name === 'vue') return vue
    if (name === '../poi') return poi
    if (name === '../mapResource') throw Error('editing must not fetch entire layer')
    if (name === '../api') return { ApiError, savePoiFeature: async (...args) => {
      calls.push(args)
      if (fail) throw new ApiError('请重新加载', 'POI_SNAPSHOT_CONFLICT')
      return { id: 'layer' }
    } }
    throw Error(name)
  }, () => props, () => (...event) => events.push(event), () => {}, {})
  return { editor, document, calls, events }
}

test('editing an imported POI preserves unrelated attributes, feature IDs and original altitude', async () => {
  const { editor, calls, document, events } = setup()
  editor.name.value = '修改名称'
  await editor.save()
  const [id, body] = calls[0]
  assert.deepEqual([id, body.asset_id, body.version, body.object_id, body.operation], ['layer', 'asset', '1.0.0', 'point-id', 'update'])
  assert.deepEqual(body.feature.properties.untouched, { keep: true })
  assert.equal(body.feature.properties.source, '外部导入')
  assert.deepEqual(body.feature.geometry.coordinates, [121, 25, 12])
  assert.equal(document.features[0].properties.name, '原有点')
  assert.equal(events[0][0], 'saved')
})

test('moving a POI removes stale geographic envelopes while retaining source attributes', async () => {
  const { editor, calls } = setup({ moved: true })
  await editor.save()
  const saved = calls[0][1].feature
  assert.deepEqual(saved.geometry.coordinates, [121.5, 25.5])
  assert.equal(saved.bbox, undefined)
})

test('a stale snapshot keeps the draft and blocks repeated saves until refreshed', async () => {
  const { editor, calls, events } = setup({ fail: true })
  editor.name.value = '未提交草稿'
  await editor.save()
  assert.equal(editor.name.value, '未提交草稿')
  assert.equal(editor.conflict.value, true)
  assert.equal(editor.busy.value, false)
  assert.equal(events.length, 0)
  await editor.save()
  assert.equal(calls.length, 1)
})
