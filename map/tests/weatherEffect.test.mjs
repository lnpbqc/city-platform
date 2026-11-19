import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { test } from 'node:test'
import { parse } from 'vue/compiler-sfc'
import ts from 'typescript'
import * as vue from 'vue'

const { descriptor } = parse(readFileSync(new URL('../src/components/map/WeatherEffect.vue', import.meta.url), 'utf8'))
const script = ts.transpileModule(descriptor.scriptSetup.content, { compilerOptions: { module: ts.ModuleKind.CommonJS } }).outputText
const create = new Function('require', 'defineProps', 'exports', 'window', 'document', 'requestAnimationFrame', 'cancelAnimationFrame', `${script}\nreturn { canvas }`)

test('thunderstorms draw denser rain, respect reduced motion and release frames on change or disposal', async t => {
  const pending = new Map()
  let sequence = 0, lines = 0
  const motion = { matches: false }
  const props = vue.reactive({ effect: 'rain' })
  const scope = vue.effectScope()
  t.after(() => scope.stop())
  const state = scope.run(() => create(() => ({ ...vue, onBeforeUnmount: vue.onScopeDispose }), () => props, {},
    { matchMedia: () => motion }, { hidden: false }, callback => { pending.set(++sequence, callback); return sequence }, id => pending.delete(id)))
  const context = { clearRect() {}, beginPath() {}, moveTo() {}, lineTo() { lines++ }, stroke() {} }
  state.canvas.value = { clientWidth: 1000, clientHeight: 800, getContext: () => context }
  const draw = time => { const [id, callback] = pending.entries().next().value; pending.delete(id); callback(time) }
  await vue.nextTick()
  draw(32)
  const rain = lines
  props.effect = 'thunderstorm'
  await vue.nextTick()
  assert.equal(pending.size, 1)
  lines = 0
  draw(64)
  assert.ok(lines > rain)
  motion.matches = true
  lines = 0
  draw(96)
  assert.equal(lines, 0)
  props.effect = 'fog'
  await vue.nextTick()
  assert.equal(pending.size, 0)
  props.effect = 'rain'
  await vue.nextTick()
  assert.equal(pending.size, 1)
  scope.stop()
  assert.equal(pending.size, 0)
})
