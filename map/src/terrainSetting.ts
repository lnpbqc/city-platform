export const terrainStorageKey = 'city.map.terrain.v1'

type TerrainStorage = Pick<Storage, 'getItem' | 'setItem'>

/** Terrain stays on unless the user explicitly switched it off. */
export function readTerrainEnabled(storage: TerrainStorage | undefined) {
  try { return storage?.getItem(terrainStorageKey) !== '0' } catch { return true }
}

export function saveTerrainEnabled(storage: TerrainStorage | undefined, enabled: boolean) {
  try { storage?.setItem(terrainStorageKey, enabled ? '1' : '0'); return true } catch { return false }
}

/** Same rule the basemap uses to request Cesium World Terrain. */
export function ionTerrainConfigured(env: { VITE_BASEMAP_PROVIDER?: string; VITE_CESIUM_ION_TOKEN?: string }) {
  return env.VITE_BASEMAP_PROVIDER !== 'tianditu' && !!env.VITE_CESIUM_ION_TOKEN
}
