import {
  Ion,
  createWorldImageryAsync,
  createWorldTerrainAsync,
  TileMapServiceImageryProvider,
  WebMapTileServiceImageryProvider,
  WebMercatorTilingScheme,
  buildModuleUrl,
  Credit,
  type TerrainProvider,
  type Viewer,
  type ImageryLayer,
  type ImageryProvider,
} from 'cesium'
import { ionTerrainConfigured } from './terrainSetting.ts'
import type { BasemapKind } from './basemapSetting.ts'

type BasemapEnvironment = {
  VITE_BASEMAP_PROVIDER?: string
  VITE_TIANDITU_KEY?: string
  VITE_CESIUM_ION_TOKEN?: string
  VITE_TIANDITU_MAX_LEVEL?: string
}

/** Owns only base imagery; overlays and terrain are independent of map style. */
export function createBasemapSwitcher(
  viewer: Viewer,
  env: BasemapEnvironment,
  alive: () => boolean,
  onNotice: (message: string) => void,
) {
  let revision = 0
  let activeKind: BasemapKind | undefined
  let active: { layer: ImageryLayer; unsubscribe?: () => void }[] = []
  const cached = new Map<string, typeof active[number]>()
  let disposed = false
  const tianditu = env.VITE_BASEMAP_PROVIDER === 'tianditu'
  const key = env.VITE_TIANDITU_KEY?.trim()
  const token = tianditu ? undefined : env.VITE_CESIUM_ION_TOKEN
  const level = Number(env.VITE_TIANDITU_MAX_LEVEL)
  const maximumLevel = Number.isInteger(level) && level >= 1 && level <= 18 ? level : 18

  function wmts(layer: string) {
    return new WebMapTileServiceImageryProvider({
      url: `https://t{s}.tianditu.gov.cn/${layer}_w/wmts?tk=${encodeURIComponent(key!)}`,
      layer,
      style: 'default',
      format: 'tiles',
      tileMatrixSetID: 'w',
      tileMatrixLabels: Array.from({ length: 19 }, (_, level) => String(level)),
      tilingScheme: new WebMercatorTilingScheme(),
      minimumLevel: 1,
      maximumLevel,
      subdomains: ['0', '1', '2', '3', '4', '5', '6', '7'],
      credit: new Credit('<a href="https://www.tianditu.gov.cn/" target="_blank" rel="noopener">天地图</a>', true),
    })
  }

  async function setBasemap(kind: BasemapKind, options?: { annotations?: boolean }): Promise<boolean> {
    const request = ++revision
    if (!alive() || disposed) return false
    const annotations = options?.annotations ?? kind === 'vector'
    if ((kind === 'vector' || annotations) && !key) {
      onNotice(`尚未配置 VITE_TIANDITU_KEY，${kind === 'vector' ? '矢量底图' : '影像注记'}不可用。`)
      return false
    }
    const ids = [kind, ...(annotations ? [kind === 'vector' ? 'cva' : 'cia'] : [])]
    if (activeKind === kind && active.length === ids.length && ids.every(id => active.includes(cached.get(id)!))) return true
    const current = () => alive() && !disposed && request === revision
    const added = new Map<string, typeof active[number]>()
    try {
      if (token) Ion.defaultAccessToken = token
      for (const id of ids) {
        if (cached.has(id)) continue
        let provider: ImageryProvider
        if (id === 'vector') provider = wmts('vec')
        else if (id === 'cia' || id === 'cva') provider = wmts(id)
        else if (tianditu && key) provider = wmts('img')
        else provider = token
          ? await createWorldImageryAsync()
          : await TileMapServiceImageryProvider.fromUrl(buildModuleUrl('Assets/Textures/NaturalEarthII'))
        if (!current()) return false
        // Keep all owned imagery below business overlays, including hidden bases.
        const layer = viewer.imageryLayers.addImageryProvider(provider, cached.size + added.size)
        layer.show = false
        const entry: typeof active[number] = { layer }
        added.set(id, entry)
        entry.unsubscribe = provider.errorEvent.addEventListener(() => {
          if (alive() && !disposed && active.includes(entry)) onNotice(id !== 'imagery' || tianditu
            ? '天地图瓦片加载失败，请检查 Key 和网络；专题图层仍可操作。'
            : '影像瓦片加载失败，请检查网络或 ion 权限；专题图层仍可操作。')
        })
      }
      for (const [id, entry] of added) cached.set(id, entry)
      for (const entry of active) entry.layer.show = false
      active = ids.map(id => cached.get(id)!)
      for (const entry of active) entry.layer.show = true
      activeKind = kind
      if (kind === 'imagery' && !token && !(tianditu && key)) onNotice(tianditu
        ? '尚未配置 VITE_TIANDITU_KEY，当前使用内置低分辨率地球影像与椭球地表。'
        : '尚未配置 ion Token，当前使用内置低分辨率地球影像与椭球地表。')
      viewer.scene.requestRender()
      return true
    } catch {
      for (const entry of added.values()) {
        entry.unsubscribe?.()
        if (alive()) viewer.imageryLayers.remove(entry.layer, true)
      }
      if (current()) onNotice(kind === 'vector' || tianditu
        ? '天地图底图不可用，请检查 Key、网络或本地底图资源；当前保留原底图。'
        : 'ion 影像不可用，请检查 Token、网络和资源权限；当前保留原底图。')
      return false
    }
  }
  return { setBasemap, destroy() {
    disposed = true
    revision++
    for (const entry of cached.values()) {
      entry.unsubscribe?.()
      viewer.imageryLayers.remove(entry.layer, true)
    }
    cached.clear()
    active = []
  } }
}

/** Resolves world terrain independently from subsequent base imagery switches. */
export async function initializeBasemap(
  viewer: Viewer,
  env: BasemapEnvironment,
  alive: () => boolean,
  onNotice: (message: string) => void,
  switching = createBasemapSwitcher(viewer, env, alive, onNotice),
): Promise<TerrainProvider | undefined> {
  await switching.setBasemap('imagery')
  if (!ionTerrainConfigured(env) || !alive()) return undefined
  try {
    const terrain = await createWorldTerrainAsync()
    if (!alive()) return undefined
    terrain.errorEvent.addEventListener(() => {
      if (alive()) onNotice('地形瓦片加载失败，请检查网络和 ion 权限。')
    })
    return terrain
  } catch {
    if (alive())
      onNotice('ion 地形不可用，当前使用椭球地表；请检查网络和资源权限。')
    return undefined
  }
}
