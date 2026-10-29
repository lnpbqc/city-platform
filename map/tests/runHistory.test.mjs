import { beforeEach, mock, test } from 'node:test'
import assert from 'node:assert/strict'
import { createRenderer, defineComponent } from 'vue'
import { readFile } from 'node:fs/promises'
import { stripTypeScriptTypes } from 'node:module'
import { parse, compileScript } from 'vue/compiler-sfc'

const deferred = () => { let resolve, reject; const promise = new Promise((yes, no) => { resolve = yes; reject = no }); return { promise, resolve, reject } }
let calls, handler
beforeEach(() => {
  calls = []
  globalThis.document = { addEventListener() {}, removeEventListener() {} }
  handler = async query => ({ ...query, items: [{ run_id: `run-${query.page}` }], total: 41 })
})
mock.module('../src/api.ts', { exports: { getRuns: (query, signal) => { calls.push({ query, signal }); return handler(query, signal) } } })
const { useRunHistory } = await import('../src/composables/useRunHistory.ts')
const source = await readFile(new URL('../src/components/RunHistoryPanel.vue', import.meta.url), 'utf8')
let compiled = stripTypeScriptTypes(compileScript(parse(source).descriptor, { id: 'run-history-test' }).content, { mode: 'transform' })
compiled = compiled.replace(/import\s+([\s\S]*?)\s+from\s+(['"])([^'"]+)\2\s*;?/g, (_statement, binding, _quote, specifier) => {
  if (specifier === 'vue') return `import ${binding} from '${import.meta.resolve('vue')}';`
  if (specifier === '@lucide/vue') return `const ${binding.replace(/\bas\b/g, ':')} = new Proxy({}, { get: () => ({}) });`
  return `import ${binding} from '${new URL('../src/' + specifier.slice(3) + '.ts', import.meta.url).href}';`
})
const historyPanel = (await import('data:text/javascript;base64,' + Buffer.from(compiled).toString('base64'))).default
historyPanel.render = () => null
const renderer = createRenderer({ createElement: () => ({}), createText: () => ({}), createComment: () => ({}), insert() {}, remove() {}, setText() {}, setElementText() {}, patchProp() {}, parentNode: () => null, nextSibling: () => null })
function setup(t) {
  let history
  const app = renderer.createApp(defineComponent({ setup() { history = useRunHistory(); return () => null } }))
  app.mount({}); t.after(() => app.unmount())
  return { app, history }
}
test('history pages and filter changes use server pagination and reset to page one', async t => {
  const { history } = setup(t)
  await history.refresh(); await history.setPage(3)
  assert.equal(history.items.value[0].run_id, 'run-3')
  assert.equal(history.total.value, 41)
  await history.setQuery({ scene_id: 'scene/id', status: 'failed', from: '2026-10-27T00:00:00Z', to: '2026-10-28T00:00:00Z' })
  assert.equal(history.page.value, 1)
  assert.equal(history.pageSize.value, 20)
  assert.deepEqual(calls.at(-1).query, { ...history.query.value, page: 1, page_size: 20 })
})
test('late history pages and errors never overwrite newer filters; failed current queries clear stale rows', async t => {
  const { history } = setup(t), old = deferred()
  handler = () => old.promise
  const refreshing = history.refresh()
  handler = async query => ({ ...query, items: [{ run_id: 'new' }], total: 1 })
  await history.setQuery({ status: 'succeeded' })
  assert.equal(calls[0].signal.aborted, true)
  old.reject(new Error('old-error')); await refreshing
  assert.equal(history.items.value[0].run_id, 'new')
  assert.equal(history.error.value, '')
  handler = async () => { throw new Error('失败 · trace_id: history') }
  await history.setPage(2)
  assert.deepEqual(history.items.value, [])
  assert.equal(history.total.value, 0)
  assert.match(history.error.value, /trace_id: history/)
  assert.equal(history.loading.value, false)
})
test('unmount aborts an active history request and prevents all late mutations', async t => {
  const { app, history } = setup(t), late = deferred()
  handler = () => late.promise
  const refreshing = history.refresh()
  app.unmount()
  assert.equal(calls[0].signal.aborted, true)
  late.resolve({ items: [{ run_id: 'late' }], total: 1, page: 1, page_size: 20 })
  await refreshing
  assert.deepEqual(history.items.value, [])
})

test('an open history panel reconnects at the existing filter and page', async t => {
  const app = renderer.createApp(historyPanel, { scenes: [], locked: false, selected: '', revision: '', recovery: 0 })
  app.mount({}); t.after(() => app.unmount())
  await new Promise(setImmediate)
  const state = app._instance.setupState
  state.scene = 'scene-filter'; state.status = 'failed'
  state.apply(); await new Promise(setImmediate)
  await state.setPage(3)
  app._instance.props.recovery = 1
  await new Promise(setImmediate)
  assert.equal(state.page, 3)
  assert.equal(state.scene, 'scene-filter')
  assert.equal(state.status, 'failed')
  assert.deepEqual(calls.at(-1).query, { scene_id: 'scene-filter', status: 'failed', from: '', to: '', page: 3, page_size: 20 })
})
