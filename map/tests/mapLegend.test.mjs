import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import { stripTypeScriptTypes } from 'node:module'
import { test } from 'node:test'
import { createRenderer, nextTick } from 'vue'
import { compileScript, parse } from 'vue/compiler-sfc'

const descriptor = parse(await readFile(new URL('../src/components/map/MapLegend.vue', import.meta.url), 'utf8')).descriptor
const code = stripTypeScriptTypes(compileScript(descriptor, { id: 'legend-test', inlineTemplate: true }).content, { mode: 'transform' })
  .replace(/from ['"]vue['"]/g, `from '${import.meta.resolve('vue')}'`)
  .replace(/import .* from ['"]@lucide\/vue['"]/g, 'const ChevronDown = { render: () => null }')
const component = (await import('data:text/javascript;base64,' + Buffer.from(code).toString('base64'))).default

function detach(node) {
  if (node.parent) node.parent.children.splice(node.parent.children.indexOf(node), 1)
}

const renderer = createRenderer({
  createElement: tag => ({ tag, style: {}, children: [] }),
  createText: text => ({ text, children: [] }),
  createComment: () => ({ children: [] }),
  insert(node, parent, anchor) {
    detach(node)
    node.parent = parent
    parent.children.splice(anchor ? parent.children.indexOf(anchor) : parent.children.length, 0, node)
  },
  remove: detach, patchProp() {},
  setText: (node, text) => { node.text = text },
  setElementText: (node, text) => { node.text = text; node.children = [] },
  parentNode: node => node.parent,
  nextSibling: node => node.parent?.children[node.parent.children.indexOf(node) + 1],
})
const text = node => (node.text ?? '') + node.children.map(text).join(' ')
const base = { id: 'ordinary', type: 'geojson', name: '普通道路', attached: true, visible: true, status: 'ready' }
const scale = [{ label: '0–10', color: '#93c5fd' }, { label: '10–30', color: '#3b82f6' }]
const thematic = { ...base, id: 'thematic', name: '积水深度', static: false, unit: 'cm', legend: [...scale, { label: '缺测', color: '#94a3b8' }] }

test('the map legend appears only for ready, visible color scales and hides when the last scale leaves', async t => {
  const ordinary = [base, { ...base, id: 'site', name: '校园白模', legend: [scale[0]] },
    { ...base, id: 'model', name: '三维模型', type: '3dtiles', legend: scale },
    { ...base, id: 'plain', name: '单色专题', legend: [{ ...scale[0] }, { ...scale[1], color: scale[0].color }] }]
  const root = { children: [] }
  const app = renderer.createApp(component, { layers: ordinary })
  app.mount(root)
  t.after(() => app.unmount())
  assert.equal(root.children.some(node => node.tag === 'aside'), false)

  app._instance.props.layers = [...ordinary, thematic]
  await nextTick()
  assert.match(text(root), /积水深度\s+cm/)
  assert.match(text(root), /0–10/)
  assert.match(text(root), /10–30/)
  assert.match(text(root), /缺测不绘制/)
  assert.doesNotMatch(text(root), /普通道路|校园白模|三维模型|单色专题|未提供/)

  for (const state of [{ visible: false }, { status: 'loading' }, { attached: false }]) {
    app._instance.props.layers = [...ordinary, { ...thematic, ...state }]
    await nextTick()
    assert.equal(root.children.some(node => node.tag === 'aside'), false)
  }
})
