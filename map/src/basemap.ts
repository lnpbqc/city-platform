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
} from 'cesium'
import { ionTerrainConfigured } from './terrainSetting.ts'

type BasemapEnvironment = {
  VITE_BASEMAP_PROVIDER?: string
  VITE_TIANDITU_KEY?: string
  VITE_CESIUM_ION_TOKEN?: string
}

/** Adds imagery and resolves the ion world terrain, which the caller decides whether to show. */
export async function initializeBasemap(
  viewer: Viewer,
  env: BasemapEnvironment,
  alive: () => boolean,
  onNotice: (message: string) => void,
): Promise<TerrainProvider | undefined> {
  const tianditu = env.VITE_BASEMAP_PROVIDER === 'tianditu'
  const key = env.VITE_TIANDITU_KEY?.trim()
  const token = tianditu ? undefined : env.VITE_CESIUM_ION_TOKEN
  if (!alive()) return undefined
  if (token) Ion.defaultAccessToken = token
  if (tianditu && !key)
    onNotice('尚未配置 VITE_TIANDITU_KEY，当前使用内置低分辨率地球影像与椭球地表。')
  try {
    if (tianditu && key) {
      const credit = new Credit('<a href="https://www.tianditu.gov.cn/" target="_blank" rel="noopener">天地图</a>', true)
      for (const layer of ['img']) {
        const imagery = new WebMapTileServiceImageryProvider({
          url: `https://t{s}.tianditu.gov.cn/${layer}_w/wmts?tk=${encodeURIComponent(key)}`,
          layer,
          style: 'default',
          format: 'tiles',
          tileMatrixSetID: 'w',
          tileMatrixLabels: Array.from({ length: 19 }, (_, level) => String(level)),
          tilingScheme: new WebMercatorTilingScheme(),
          minimumLevel: 1,
          maximumLevel: 18,
          subdomains: ['0', '1', '2', '3', '4', '5', '6', '7'],
          credit,
        })
        imagery.errorEvent.addEventListener(() => {
          if (alive()) onNotice('天地图瓦片加载失败，请检查 Key 和网络；专题图层仍可操作。')
        })
        if (!alive()) return undefined
        viewer.imageryLayers.addImageryProvider(imagery)
      }
    } else {
      const imagery = token
        ? await createWorldImageryAsync()
        : await TileMapServiceImageryProvider.fromUrl(
            buildModuleUrl('Assets/Textures/NaturalEarthII'),
          )
      if (!alive()) return undefined
      imagery.errorEvent.addEventListener(() => {
        if (alive()) onNotice('影像瓦片加载失败，请检查网络或 ion 权限；专题图层仍可操作。')
      })
      viewer.imageryLayers.addImageryProvider(imagery)
      if (!token && !tianditu)
        onNotice('尚未配置 ion Token，当前使用内置低分辨率地球影像与椭球地表。')
    }
    viewer.scene.requestRender()
  } catch {
    if (alive())
      onNotice(tianditu
        ? '天地图底图不可用，请检查 Key、网络或本地底图资源；当前保留椭球地表。'
        : 'ion 影像不可用，请检查 Token、网络和资源权限；当前保留椭球地表。')
  }
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
