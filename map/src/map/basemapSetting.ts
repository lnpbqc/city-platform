export type BasemapKind = 'imagery' | 'vector'

export const basemapStorageKey = 'city.map.basemap.v1'
type BasemapStorage = Pick<Storage, 'getItem' | 'setItem'>

export function vectorBasemapConfigured(env: { VITE_TIANDITU_KEY?: string; VITE_BASEMAP_PROVIDER?: string }) {
  return !!env.VITE_TIANDITU_KEY?.trim()
}

export function readBasemap(storage: BasemapStorage | undefined, vectorAvailable: boolean): BasemapKind {
  try { return vectorAvailable && storage?.getItem(basemapStorageKey) === 'vector' ? 'vector' : 'imagery' }
  catch { return 'imagery' }
}

export function saveBasemap(storage: BasemapStorage | undefined, kind: BasemapKind) {
  try { storage?.setItem(basemapStorageKey, kind) } catch { /* Browser storage may be disabled. */ }
}
