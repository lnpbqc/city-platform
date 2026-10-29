import { test } from 'node:test'
import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import { parse } from 'vue/compiler-sfc'
import ts from 'typescript'
import * as vue from 'vue'

const source = await readFile(new URL('../src/components/BookmarkPanel.vue', import.meta.url), 'utf8')
const { descriptor } = parse(source)
const javascript = ts.transpileModule(descriptor.scriptSetup.content, {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
}).outputText
const create = new Function('require', 'defineProps', 'defineEmits', 'exports', 'document', `${javascript}
  return { open, busy, bookmarks, draft, name, picking, error, deleting, ordered,
    nameInput, trigger, load, toggle, addRegion, pickPoint, cancelDraft, close,
    save, rename, remove, locate, retry, onKey }
`)
const region = { id: '440106', label: '广东省 · 广州市 · 天河区' }
const bookmark = (id, name = id) => ({
  id, name, kind: 'point', longitude: 113, latitude: 23, region_id: null,
  created_at: '2026-10-23T00:00:00Z',
})
const flush = () => new Promise(setImmediate)
function setup(overrides = {}, resolver = async () => region) {
  const hooks = [], emitted = [], actions = []
  const controller = {
    beginPointPicking: (callback) => { controller.callback = callback; actions.push('pick') },
    cancelPointPicking: () => actions.push('cancel'),
  }
  const props = vue.reactive({ selected: region, active: true, getController: () => controller })
  const api = {
    getBookmarks: async () => [],
    createBookmark: async (input) => ({ ...bookmark('new'), ...input }),
    renameBookmark: async (id, name) => bookmark(id, name),
    deleteBookmark: async () => {},
    ...overrides,
  }
  const scope = vue.effectScope()
  const panel = scope.run(() => create((name) => {
    if (name === 'vue') return { ...vue, onMounted: () => {}, onBeforeUnmount: (hook) => hooks.push(hook) }
    if (name === '../api') return api
    if (name === '../regions') return { resolveRegionTarget: resolver }
    if (name === '@lucide/vue') return {}
    throw new Error(`Unexpected component dependency: ${name}`)
  }, () => props, () => (...args) => emitted.push(args), {}, { removeEventListener() {} }))
  return { panel, props, controller, actions, emitted, cleanup() {
    hooks.forEach((hook) => hook())
    scope.stop()
  } }
}

test('bookmark list failures can retry and records display newest first', async () => {
  let requests = 0
  const { panel, cleanup } = setup({ getBookmarks: async () => {
    if (++requests === 1) throw new Error('服务暂不可用')
    return [bookmark('old'), { ...bookmark('new'), created_at: '2026-10-24T00:00:00Z' }]
  } })
  panel.toggle()
  await flush()
  assert.match(panel.error.value, /暂不可用/)
  panel.retry()
  await flush()
  assert.deepEqual(panel.ordered.value.map((item) => item.id), ['new', 'old'])
  assert.equal(panel.error.value, '')
  cleanup()
})

test('region creation, rename and confirmed deletion update server records', async () => {
  const calls = []
  const { panel, cleanup } = setup({
    createBookmark: async (input) => { calls.push(input); return { ...bookmark('region'), ...input } },
    renameBookmark: async (id, name) => { calls.push([id, name]); return bookmark(id, name) },
    deleteBookmark: async (id) => { calls.push(id) },
  })
  panel.addRegion()
  assert.equal(panel.name.value, region.label)
  await panel.save()
  assert.deepEqual(calls[0], { name: region.label, kind: 'region', region_id: '440106' })
  panel.rename(panel.bookmarks.value[0])
  panel.name.value = '  天河  '
  await panel.save()
  assert.deepEqual(calls[1], ['region', '天河'])
  assert.equal(panel.bookmarks.value[0].name, '天河')
  await panel.remove(panel.bookmarks.value[0])
  assert.equal(calls[2], 'region')
  assert.equal(panel.bookmarks.value.length, 0)
  cleanup()
})

test('map pick opens a focused name form, saves once and retains the preview marker', async () => {
  let resolve, saves = 0, focused = 0
  const { panel, controller, actions, emitted, cleanup } = setup({
    createBookmark: () => { saves++; return new Promise((done) => { resolve = done }) },
  })
  panel.open.value = true
  panel.nameInput.value = { focus() { focused++ } }
  panel.pickPoint()
  controller.callback({ longitude: 113.315959, latitude: 23.121995 })
  await vue.nextTick()
  assert.equal(focused, 1)
  assert.equal(panel.draft.value.kind, 'point')
  assert.deepEqual(emitted, [])
  const saving = panel.save()
  await panel.save()
  assert.equal(saves, 1)
  resolve(bookmark('new'))
  await saving
  assert.equal(panel.draft.value, undefined)
  panel.close()
  assert.deepEqual(actions, ['pick'])
  assert.equal(emitted.some(([name]) => name === 'point'), false)
  cleanup()
})

test('Escape, inactive workspaces and unmount cancel unfinished point selections', async () => {
  const { panel, props, controller, actions, cleanup } = setup()
  let focused = 0
  panel.trigger.value = { focus() { focused++ } }
  panel.open.value = true
  panel.pickPoint()
  panel.onKey({ key: 'Escape', preventDefault() {} })
  assert.equal(panel.open.value, false)
  assert.equal(focused, 1)
  assert.deepEqual(actions, ['pick', 'cancel'])
  panel.open.value = true
  panel.pickPoint()
  controller.callback({ longitude: 113, latitude: 23 })
  props.active = false
  await vue.nextTick()
  assert.equal(panel.draft.value, undefined)
  assert.equal(panel.open.value, false)
  props.active = true
  panel.pickPoint()
  cleanup()
  assert.equal(actions.filter((action) => action === 'cancel').length, 3)
})

test('save failures preserve point drafts and retry with the same coordinates', async () => {
  let saves = 0
  const { panel, controller, cleanup } = setup({ createBookmark: async (input) => {
    if (++saves === 1) throw new Error('保存失败')
    return { ...bookmark('new'), ...input }
  } })
  panel.pickPoint()
  controller.callback({ longitude: 114, latitude: 24 })
  await panel.save()
  assert.match(panel.error.value, /保存失败/)
  assert.equal(panel.draft.value.longitude, 114)
  panel.retry()
  await flush()
  assert.equal(panel.bookmarks.value[0].longitude, 114)
  assert.equal(panel.draft.value, undefined)
  cleanup()
})

test('changing the selected region cancels an unfinished point selection', async () => {
  const { panel, props, actions, cleanup } = setup()
  panel.pickPoint()
  props.selected = { ...region, id: '440100' }
  await vue.nextTick()
  assert.equal(panel.picking.value, false)
  assert.equal(panel.draft.value, undefined)
  assert.deepEqual(actions, ['pick', 'cancel'])
  cleanup()
})

test('region lookup failure preserves the bookmark and location retries without changing layers', async () => {
  let lookups = 0
  const { panel, emitted, cleanup } = setup({}, async (id) => {
    assert.equal(id, '440106')
    if (++lookups === 1) throw new Error('地区目录加载失败')
    return region
  })
  const saved = { ...bookmark('region'), kind: 'region', region_id: '440106' }
  panel.bookmarks.value = [saved]
  panel.open.value = true
  await panel.locate(saved)
  assert.match(panel.error.value, /地区目录/)
  assert.equal(panel.bookmarks.value.length, 1)
  panel.retry()
  await flush()
  assert.deepEqual(emitted, [['select', region]])
  assert.equal(panel.open.value, false)
  await panel.locate(bookmark('point'))
  assert.deepEqual(emitted.at(-1), ['point', { longitude: 113, latitude: 23 }])
  cleanup()
})
