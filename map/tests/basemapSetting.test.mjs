import { test } from 'node:test'
import assert from 'node:assert/strict'
import { readBasemap, saveBasemap, vectorBasemapConfigured, readAnnotations, saveAnnotations } from '../src/map/basemapSetting.ts'

test('imagery is the default; only an available saved vector choice is restored', () => {
  let value = null
  const storage = { getItem: () => value, setItem: (_key, next) => { value = next } }
  assert.equal(readBasemap(storage, true), 'imagery')
  saveBasemap(storage, 'vector')
  assert.equal(readBasemap(storage, true), 'vector')
  assert.equal(readBasemap(storage, false), 'imagery')
  value = 'unknown'
  assert.equal(readBasemap(storage, true), 'imagery')
  const blocked = { getItem() { throw Error() }, setItem() { throw Error() } }
  assert.equal(readBasemap(blocked, true), 'imagery')
  assert.doesNotThrow(() => saveBasemap(blocked, 'vector'))
  assert.equal(readBasemap(undefined, true), 'imagery')
})

test('vector availability depends on a nonblank Tianditu key, independently of imagery provider', () => {
  assert.equal(vectorBasemapConfigured({}), false)
  assert.equal(vectorBasemapConfigured({ VITE_TIANDITU_KEY: '  ' }), false)
  assert.equal(vectorBasemapConfigured({ VITE_BASEMAP_PROVIDER: 'cesium', VITE_TIANDITU_KEY: ' key ' }), true)
})

test('annotation defaults and preferences are independent per basemap and tolerate unavailable storage', () => {
  const values = new Map()
  const storage = { getItem: key => values.get(key), setItem: (key, value) => values.set(key, value) }
  assert.equal(readAnnotations(storage, 'imagery'), false)
  assert.equal(readAnnotations(storage, 'vector'), true)
  saveAnnotations(storage, 'imagery', true)
  saveAnnotations(storage, 'vector', false)
  assert.equal(readAnnotations(storage, 'imagery'), true)
  assert.equal(readAnnotations(storage, 'vector'), false)
  assert.equal(readAnnotations(undefined, 'vector'), true)
  const blocked = { getItem() { throw Error() }, setItem() { throw Error() } }
  assert.equal(readAnnotations(blocked, 'imagery'), false)
  assert.doesNotThrow(() => saveAnnotations(blocked, 'imagery', true))
})
