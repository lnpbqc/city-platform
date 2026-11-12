import { ref, watch } from 'vue'
import { ionTerrainConfigured, readTerrainEnabled, saveTerrainEnabled } from '../map/terrainSetting.ts'

function storage() {
  try { return typeof window === 'undefined' ? undefined : window.localStorage } catch { return undefined }
}

// One display preference shared by every map canvas (map, comparison and simulation views).
const terrainEnabled = ref(readTerrainEnabled(storage()))
const terrainAvailable = ionTerrainConfigured({
  VITE_BASEMAP_PROVIDER: import.meta.env?.VITE_BASEMAP_PROVIDER,
  VITE_CESIUM_ION_TOKEN: import.meta.env?.VITE_CESIUM_ION_TOKEN,
})
watch(terrainEnabled, (enabled) => { saveTerrainEnabled(storage(), enabled) })

export function useTerrainSetting() {
  return { terrainEnabled, terrainAvailable }
}
