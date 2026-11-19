import { test } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { compileScript, parse } from 'vue/compiler-sfc'
import ts from 'typescript'
import * as vue from 'vue'

const { descriptor } = parse(readFileSync(new URL('../src/components/common/UiTooltip.vue', import.meta.url), 'utf8'))
const source = compileScript(descriptor, { id: 'tooltip', inlineTemplate: true }).content
const js = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 } }).outputText
const tick = async () => { await vue.nextTick(); await vue.nextTick() }
const walk = n => [n, ...n.children.flatMap(walk)]

function mount(initial = {}) {
  const listeners = new Map()
  const viewport = { innerWidth: 320, innerHeight: 240,
    addEventListener: (key, fn) => listeners.set(key, fn),
    removeEventListener: key => listeners.delete(key),
  }
  const exports = {}
  new Function('require', 'exports', 'window', js)(() => vue, exports, viewport)
  const node = tag => vue.markRaw({ tag, props: {}, children: [],
    get firstElementChild() { return this.children.find(n => !n.tag.startsWith('#')) },
    getAttribute(key) { return this.props[key] ?? null },
    setAttribute(key, value) { this.props[key] = value },
    removeAttribute(key) { delete this.props[key] },
    hasAttribute(key) { return this.props[key] != null && this.props[key] !== false },
    contains(other) { return walk(this).includes(other) },
    getBoundingClientRect() { return this.tag === 'div' ? { width: 140, height: 40 } : { left: 290, right: 318, top: 4, bottom: 32, width: 28, height: 28 } },
  })
  const root = node('root'), body = node('body')
  const renderer = vue.createRenderer({
    createElement: node, createText: text => ({ ...node('#text'), text }), createComment: () => node('#comment'),
    setText: (n, text) => { n.text = text }, setElementText: (n, text) => { n.text = text; n.children = [] },
    patchProp: (n, k, _old, v) => { n.props[k] = v },
    insert(n, p, a) { if (n.parent) n.parent.children.splice(n.parent.children.indexOf(n), 1); n.parent = p; const i = p.children.indexOf(a); p.children.splice(i < 0 ? p.children.length : i, 0, n) },
    remove(n) { if (n.parent) n.parent.children.splice(n.parent.children.indexOf(n), 1); n.parent = null },
    parentNode: n => n.parent, nextSibling: n => n.parent?.children[n.parent.children.indexOf(n) + 1] ?? null,
    querySelector: selector => selector === 'body' ? body : null,
  })
  let clicks = 0
  const props = vue.reactive({ text: '放大地图', disabled: false, ...initial })
  const app = renderer.createApp({ render: () => vue.h(exports.default, { text: props.text }, {
    default: () => vue.h('button', { disabled: props.disabled, 'aria-label': '放大', 'aria-describedby': 'existing', onClick: () => clicks++ }, '+'),
  }) })
  app.mount(root)
  return { props, listeners, viewport, body,
    wrapper: () => walk(root).find(n => n.tag === 'span'),
    trigger: () => walk(root).find(n => n.tag === 'button'),
    tooltip: () => walk(body).find(n => n.props.role === 'tooltip'),
    clicks: () => clicks, close: () => app.unmount(),
  }
}

test('hover waits 300ms, focus opens immediately, Escape dismisses until a fresh interaction', async t => {
  t.mock.timers.enable({ apis: ['setTimeout'] })
  const ctx = mount(); t.after(ctx.close)
  const wrapper = ctx.wrapper()
  wrapper.props.onPointerenter()
  t.mock.timers.tick(299); await tick()
  assert.equal(ctx.tooltip(), undefined)
  t.mock.timers.tick(1); await tick()
  assert.equal(ctx.tooltip().text, '放大地图')
  assert.equal(ctx.trigger().props['aria-describedby'], `existing ${ctx.tooltip().props.id}`)
  ctx.listeners.get('keydown')({ key: 'Escape' }); await tick()
  assert.equal(ctx.tooltip(), undefined)
  assert.equal(ctx.trigger().props['aria-describedby'], 'existing')
  t.mock.timers.tick(1000); await tick()
  assert.equal(ctx.tooltip(), undefined)
  wrapper.props.onFocusin(); await tick()
  assert.ok(ctx.tooltip())
  wrapper.props.onPointerleave(); await tick()
  assert.ok(ctx.tooltip(), 'focused controls retain their explanation')
  wrapper.props.onFocusout({ relatedTarget: null }); await tick()
  assert.equal(ctx.tooltip(), undefined)
  ctx.trigger().props.onClick()
  assert.equal(ctx.clicks(), 1)
})

test('disabled controls have a keyboard target, preserve native state, and restore descriptions', async t => {
  const ctx = mount({ disabled: true, text: '已达到最大缩放级别' }); t.after(ctx.close)
  await tick()
  assert.equal(ctx.wrapper().props.tabindex, 0)
  assert.equal(ctx.wrapper().props['aria-label'], '放大')
  assert.equal(ctx.trigger().props.disabled, true)
  ctx.wrapper().props.onFocusin(); await tick()
  assert.equal(ctx.tooltip().text, '已达到最大缩放级别')
  assert.equal(ctx.wrapper().props['aria-describedby'], ctx.tooltip().props.id)
  ctx.props.disabled = false; await tick()
  assert.equal(ctx.wrapper().props.tabindex, undefined)
  assert.equal(ctx.trigger().props.disabled, false)
  assert.equal(ctx.trigger().props['aria-describedby'], `existing ${ctx.tooltip().props.id}`)
})

test('teleported explanation flips below top-edge triggers and clamps inside viewport', async t => {
  const ctx = mount(); t.after(ctx.close)
  ctx.wrapper().props.onFocusin(); await tick()
  assert.equal(ctx.tooltip().parent, ctx.body)
  assert.equal(ctx.tooltip().props.style.left, '172px')
  assert.equal(ctx.tooltip().props.style.top, '40px')
  ctx.viewport.innerWidth = 180
  ctx.listeners.get('resize')(); await tick()
  assert.equal(ctx.tooltip().props.style.left, '32px')
})

test('unmount clears delayed opening and global listeners', async t => {
  t.mock.timers.enable({ apis: ['setTimeout'] })
  const ctx = mount()
  ctx.wrapper().props.onPointerenter()
  ctx.close()
  assert.equal(ctx.listeners.size, 0)
  t.mock.timers.tick(300); await tick()
  assert.equal(ctx.tooltip(), undefined)
})
