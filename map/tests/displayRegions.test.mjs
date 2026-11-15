import assert from 'node:assert/strict'
import { mock, test } from 'node:test'
import { effectScope, ref } from 'vue'

let list
mock.module('../src/api/api.ts', { exports: {
  getDisplayRegions: () => list(),
  saveDisplayRegion: async () => {},
  deleteDisplayRegion: async () => {},
} })
const { useDisplayRegions } = await import('../src/composables/useDisplayRegions.ts')
const tick = () => new Promise(setImmediate)

test('restoring the connection refreshes the shared project regions without reopening the menu', async t => {
  const scope = effectScope()
  t.after(() => scope.stop())
  const active = ref(true), recovery = ref(0)
  let reads = 0
  list = async () => { reads++; throw Error('offline') }
  const catalog = scope.run(() => useDisplayRegions(() => active.value, () => recovery.value))
  await tick()
  assert.equal(catalog.regions.value, null)
  assert.equal(catalog.loadError.value, '展示区域加载失败')
  assert.equal(reads, 1)
  const saved = { id: 'area', name: '展示区域' }
  list = async () => { reads++; return [saved] }
  recovery.value++
  await tick()
  assert.equal(reads, 2)
  assert.deepEqual(catalog.regions.value, [saved])
  assert.equal(catalog.loadError.value, '')
})
