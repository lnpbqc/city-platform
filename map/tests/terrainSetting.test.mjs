import { test } from 'node:test'
import assert from 'node:assert/strict'
import { ionTerrainConfigured, readTerrainEnabled, saveTerrainEnabled, terrainStorageKey } from '../src/terrainSetting.ts'

function memory() {
  const values = new Map()
  return { values, getItem: key => values.get(key) ?? null, setItem: (key, value) => values.set(key, String(value)) }
}

test('terrain defaults to on and remembers the last explicit choice', () => {
  const storage = memory()
  assert.equal(readTerrainEnabled(storage), true)
  assert.equal(readTerrainEnabled(undefined), true)
  assert.equal(saveTerrainEnabled(storage, false), true)
  assert.equal(storage.values.get(terrainStorageKey), '0')
  assert.equal(readTerrainEnabled(storage), false)
  saveTerrainEnabled(storage, true)
  assert.equal(storage.values.get(terrainStorageKey), '1')
  assert.equal(readTerrainEnabled(storage), true)
  storage.values.set(terrainStorageKey, 'unexpected')
  assert.equal(readTerrainEnabled(storage), true)
})

test('disabled browser storage falls back to terrain on without throwing', () => {
  const blocked = { getItem() { throw new Error('denied') }, setItem() { throw new Error('denied') } }
  assert.equal(readTerrainEnabled(blocked), true)
  assert.equal(saveTerrainEnabled(blocked, false), false)
  assert.equal(saveTerrainEnabled(undefined, false), true)
})

test('ion terrain is available only for Cesium basemaps with a token', () => {
  assert.equal(ionTerrainConfigured({}), false)
  assert.equal(ionTerrainConfigured({ VITE_CESIUM_ION_TOKEN: '' }), false)
  assert.equal(ionTerrainConfigured({ VITE_CESIUM_ION_TOKEN: 'token' }), true)
  assert.equal(ionTerrainConfigured({ VITE_BASEMAP_PROVIDER: 'cesium', VITE_CESIUM_ION_TOKEN: 'token' }), true)
  assert.equal(ionTerrainConfigured({ VITE_BASEMAP_PROVIDER: 'cesium' }), false)
  assert.equal(ionTerrainConfigured({ VITE_BASEMAP_PROVIDER: 'tianditu', VITE_CESIUM_ION_TOKEN: 'token' }), false)
})
