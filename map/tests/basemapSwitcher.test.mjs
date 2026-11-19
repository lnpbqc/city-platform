import { test } from 'node:test'
import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import { stripTypeScriptTypes } from 'node:module'
import { createRenderer, nextTick } from 'vue'
import { compileScript, parse } from 'vue/compiler-sfc'
import * as settings from '../src/map/basemapSetting.ts'

const descriptor = parse(await readFile(new URL('../src/components/map/BasemapSwitcher.vue', import.meta.url), 'utf8')).descriptor
const code = stripTypeScriptTypes(compileScript(descriptor, { id: 'basemap-test', inlineTemplate: true }).content, { mode: 'transform' })
  .replace(/from ['"]vue['"]/g, `from '${import.meta.resolve('vue')}'`)
  .replace(/from ['"]..\/..\/map\/basemapSetting['"]/g, `from '${new URL('../src/map/basemapSetting.ts', import.meta.url).href}'`)
const component = (await import('data:text/javascript;base64,' + Buffer.from(code).toString('base64'))).default
globalThis.window = undefined
globalThis.document = undefined
const renderer = createRenderer({
  createElement: tag => ({ tag, props: {}, children: [], focus() { document.activeElement = this },
    querySelector(selector) { return find(this, node => node.props?.['data-basemap'] === selector.match(/"(.*?)"/)[1]) },
    contains(target) { return this === target || this.children.some(child => child.contains?.(target)) } }),
  createText: text => ({ text, children: [] }), createComment: () => ({ children: [] }),
  insert(node, parent) { node.parent = parent; parent.children.push(node) },
  remove(node) { node.parent.children.splice(node.parent.children.indexOf(node), 1) },
  patchProp(node, key, _previous, value) { node.props[key] = value },
  setText(node, value) { node.text = value }, setElementText(node, value) { node.text = value; node.children = [] },
  parentNode: node => node.parent, nextSibling: () => null,
})
const find = (root, predicate) => predicate(root) ? root : root.children.map(child => find(child, predicate)).find(Boolean)
const flush = async () => { await new Promise(resolve => setImmediate(resolve)); await nextTick() }
function setup(t, options = {}) {
  const values = new Map(options.values ?? (options.saved ? [[settings.basemapStorageKey, options.saved]] : []))
  const listeners = new Map(), calls = [], annotationCalls = []
  t.mock.property(globalThis, 'window', { localStorage: { getItem: key => values.get(key), setItem: (key, value) => values.set(key, value) } })
  t.mock.property(globalThis, 'document', {
    addEventListener: (name, listener) => listeners.set(name, listener),
    removeEventListener: name => listeners.delete(name),
  })
  const controller = { async setBasemap(kind, settings) { calls.push(kind); annotationCalls.push(settings?.annotations); return options.switch ? options.switch(kind) : true } }
  const root = { children: [] }
  const app = renderer.createApp(component, { controller, vectorAvailable: options.available ?? true })
  app.mount(root)
  t.after(() => app.unmount())
  const trigger = () => find(root, node => node.props?.class === 'stack-trigger')
  const card = kind => find(root, node => node.props?.['data-basemap'] === kind)
  const checkbox = kind => find(root, node => node.tag === 'input' && node.props?.['aria-label'] === `${kind === 'imagery' ? '影像' : '矢量'}显示注记`)
  return { app, root, values, listeners, calls, annotationCalls, trigger, card, checkbox }
}

test('collapsed basemap keeps the selected thumbnail in front and the other card stacked behind', async t => {
  const ctx = setup(t)
  assert.notEqual(ctx.card('imagery').parent.props.hidden, true)
  assert.match(ctx.card('imagery').parent.props.class, /selected/)
  assert.match(ctx.card('vector').parent.props.class, /behind/)
  ctx.trigger().props.onClick()
  await nextTick()
  assert.equal(ctx.trigger().props['aria-expanded'], true)
  await ctx.card('vector').props.onClick()
  await nextTick()
  assert.match(ctx.card('vector').parent.props.class, /selected/)
  assert.match(ctx.card('imagery').parent.props.class, /behind/)
})

test('cards expand by hover or click, select by button activation, close by Escape or outside press', async t => {
  const ctx = setup(t)
  const container = ctx.root.children[0]
  assert.equal(ctx.trigger().props['aria-expanded'], false)
  container.props.onMouseenter()
  await nextTick()
  assert.equal(ctx.trigger().props['aria-expanded'], true)
  await ctx.card('vector').props.onClick()
  await nextTick()
  assert.deepEqual(ctx.calls, ['vector'])
  assert.equal(ctx.card('vector').props['aria-pressed'], true)
  assert.equal(ctx.values.get(settings.basemapStorageKey), 'vector')
  container.props.onMouseleave()
  await nextTick()
  assert.equal(ctx.trigger().props['aria-expanded'], false)
  ctx.trigger().props.onClick()
  await nextTick()
  assert.equal(ctx.trigger().props['aria-expanded'], true)
  assert.equal(document.activeElement.props['data-basemap'], 'vector')
  container.props.onKeydown({ key: 'Escape', stopPropagation() {}, preventDefault() {} })
  await nextTick()
  assert.equal(ctx.trigger().props['aria-expanded'], false)
  ctx.trigger().props.onClick()
  await nextTick()
  ctx.listeners.get('pointerdown')({ target: {} })
  await nextTick()
  assert.equal(ctx.trigger().props['aria-expanded'], false)
})

test('unavailable vector cannot be selected and a saved vector preference falls back to imagery', async t => {
  const ctx = setup(t, { saved: 'vector', available: false })
  await flush()
  assert.equal(ctx.card('vector').props.disabled, true)
  await ctx.card('vector').props.onClick()
  assert.deepEqual(ctx.calls, [])
  assert.equal(ctx.card('imagery').props['aria-pressed'], true)
})

test('failed switching preserves selection and preference; a saved available vector restores', async t => {
  const ctx = setup(t, { saved: 'vector', switch: () => true })
  await flush()
  assert.deepEqual(ctx.calls, ['vector'])
  assert.equal(ctx.card('vector').props['aria-pressed'], true)
  ctx.app._instance.props.controller.setBasemap = async () => false
  await ctx.card('imagery').props.onClick()
  await nextTick()
  assert.equal(ctx.card('vector').props['aria-pressed'], true)
  assert.equal(ctx.values.get(settings.basemapStorageKey), 'vector')
})

test('a late switch result cannot replace the latest UI choice or storage', async t => {
  let release
  const ctx = setup(t, { switch: kind => kind === 'vector' ? new Promise(resolve => { release = resolve }) : true })
  const first = ctx.card('vector').props.onClick()
  await ctx.card('imagery').props.onClick()
  release(true)
  await first
  await nextTick()
  assert.equal(ctx.card('imagery').props['aria-pressed'], true)
  assert.equal(ctx.values.get(settings.basemapStorageKey), 'imagery')
})

test('the default imagery card can retry a failed initial imagery load', async t => {
  const ctx = setup(t, { available: false })
  await ctx.card('imagery').props.onClick()
  await nextTick()
  assert.deepEqual(ctx.calls, ['imagery'])
  assert.equal(ctx.values.get(settings.basemapStorageKey), 'imagery')
})

test('annotation checkboxes default by kind and editing an inactive card does not switch basemaps', async t => {
  const ctx = setup(t)
  assert.equal(ctx.checkbox('imagery').props.checked, false)
  assert.equal(ctx.checkbox('vector').props.checked, true)
  await ctx.checkbox('vector').props.onChange({ target: { checked: false } })
  assert.deepEqual(ctx.calls, [])
  await ctx.card('vector').props.onClick()
  assert.deepEqual(ctx.annotationCalls, [false])
  assert.equal(ctx.checkbox('imagery').props.checked, false)
  await ctx.checkbox('vector').props.onChange({ target: { checked: true } })
  assert.deepEqual(ctx.annotationCalls, [false, true])
  assert.equal(ctx.checkbox('vector').props.checked, true)
  assert.equal(find(ctx.card('vector'), node => node.tag === 'input'), undefined)
})

test('saved annotation choices restore with the saved basemap', async t => {
  const values = new Map([[settings.basemapStorageKey, 'vector']])
  settings.saveAnnotations({ setItem: (key, value) => values.set(key, value) }, 'vector', false)
  const restored = setup(t, { values })
  await flush()
  assert.deepEqual(restored.annotationCalls, [false])
  assert.equal(restored.checkbox('vector').props.checked, false)
})

test('missing key disables annotations', async t => {
  const unkeyed = setup(t, { available: false })
  assert.equal(unkeyed.checkbox('imagery').props.disabled, true)
})

test('a failed toggle restores the checkbox', async t => {
  const ctx = setup(t, { switch: () => false })
  const target = { checked: true }
  await ctx.checkbox('imagery').props.onChange({ target })
  await nextTick()
  assert.equal(target.checked, false)
  assert.equal(ctx.checkbox('imagery').props.checked, false)
})

test('annotation changes while imagery is loading survive the pending switch', async t => {
  const gates = []
  const ctx = setup(t, { saved: 'vector', switch: kind => kind === 'imagery' ? new Promise(resolve => gates.push(resolve)) : true })
  await flush()
  const switching = ctx.card('imagery').props.onClick()
  await nextTick()
  const toggling = ctx.checkbox('imagery').props.onChange({ target: { checked: true } })
  await nextTick()
  gates.forEach(resolve => resolve(true))
  await Promise.all([switching, toggling])
  await nextTick()
  assert.equal(ctx.checkbox('imagery').props.checked, true)
  assert.equal(ctx.annotationCalls.at(-1), true)
  assert.equal(settings.readAnnotations({ getItem: key => ctx.values.get(key) }, 'imagery'), true)
})
