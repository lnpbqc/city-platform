import { beforeEach, mock, test } from 'node:test'
import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import { stripTypeScriptTypes } from 'node:module'
import { parse, compileScript } from 'vue/compiler-sfc'
import { createRenderer, nextTick } from 'vue'

const camera = { longitude: 113, latitude: 23, height: 900, heading: 0, pitch: -1, roll: 0, scene_mode: '3d' }
let signals
beforeEach(() => { signals = []; globalThis.document = { addEventListener() {}, removeEventListener() {} } })
mock.module('../src/api.ts', { exports: {
  getLayerTimes: async (_id, _query, signal) => { signals.push(signal); return ['2026-10-25T00:00:00Z', '2026-10-25T01:00:00Z'] },
  getTimeSeries: async (query, signal) => { signals.push(signal); return { ...query, asset: { asset_id: query.asset_id, version: query.version }, unit: 'cm', items: [] } },
} })
const source = await readFile(new URL('../src/components/ComparisonView.vue', import.meta.url), 'utf8')
let compiled = stripTypeScriptTypes(compileScript(parse(source).descriptor, { id: 'comparison-view-test' }).content, { mode: 'transform' })
compiled = compiled.replace(/import\s+([\s\S]*?)\s+from\s+(['"])([^'"]+)\2\s*;?/g, (statement, binding, _quote, specifier) => {
  if (specifier === 'vue') return `import ${binding} from '${import.meta.resolve('vue')}';`
  if (specifier.endsWith('.vue')) return `const ${binding} = {};`
  return `import ${binding} from '${new URL('../src/' + specifier.slice(3) + '.ts', import.meta.url).href}';`
})
const component = (await import('data:text/javascript;base64,' + Buffer.from(compiled).toString('base64'))).default
component.render = () => null
const renderer = createRenderer({ createElement: () => ({}), createText: () => ({}), createComment: () => ({}), insert() {}, remove() {}, setText() {}, setElementText() {}, patchProp() {}, parentNode: () => null, nextSibling: () => null })
const flush = async () => { await new Promise(setImmediate); await nextTick() }
test('comparison clones fixed layer state, restores an independent time and releases requests on close', async t => {
  const sources = [{ id: 'points', name: 'point', category: '专题', type: 'geojson', source: '', color: '#347af0', attached: true, visible: false, opacity: 0.35,
    static: false, asset_id: 'asset', asset_version: '1.0.0', url: '/pinned', order: 3, status: 'ready', campus: 'university-town' }]
  const app = renderer.createApp(component, { active: true, layers: sources, camera, initialTime: { time: '2026-10-25T01:00:00Z', resolution: 'hour' } })
  app.mount({}); t.after(() => app.unmount())
  const state = app._instance.setupState, calls = []
  state.ready({ initialize() {}, load: async layer => { layer.attached = true; layer.status = 'ready'; calls.push({ id: layer.id, version: layer.asset_version }) },
    appearance() {}, syncOrder() {}, showTemporal() {}, remove: layer => calls.push({ remove: layer.id }) })
  await flush()
  assert.notEqual(state.layers[0], sources[0])
  assert.deepEqual(calls, [{ id: 'points', version: '1.0.0' }])
  assert.equal(state.layers[0].visible, false)
  assert.equal(state.layers[0].opacity, 0.35)
  assert.equal(state.layers[0].order, 3)
  assert.equal(state.time, '2026-10-25T01:00:00.000Z')
  state.temporal.seek(0); await flush()
  assert.equal(state.time, '2026-10-25T00:00:00.000Z')
  assert.equal(sources[0].asset_version, '1.0.0')
  app.unmount()
  assert.ok(signals.length > 0 && signals.at(-1).aborted)
})
