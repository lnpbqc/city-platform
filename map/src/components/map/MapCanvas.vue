<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { createMapController, type MapController } from '../../map/mapController'
import type { Selection } from '../../layers/types'
import type { BoundaryState } from '../../map/regionBoundary'
import type { NavigationReading } from '../../map/mapNavigation'
import { useTerrainSetting } from '../../composables/useTerrainSetting'
import type { MapPoint } from '../../map/mapController'
import type { WeatherEffect as WeatherEffectKind } from '../../map/weather'
import WeatherEffect from './WeatherEffect.vue'
const props = defineProps<{ weatherEffect?: WeatherEffectKind; trackWeather?: boolean }>()
const emit = defineEmits<{
  ready: [controller: MapController]
  selection: [value: Selection | null]
  notice: [message: string]
  fatal: [message: string]
  boundary: [state: BoundaryState]
  navigation: [state: NavigationReading, settled: boolean]
  ground: [point: MapPoint]
  cameraMove: []
  weatherResize: []
}>()
const container = ref<HTMLElement | null>(null)
const { terrainEnabled } = useTerrainSetting()
let controller: MapController | undefined
let weatherResize: ResizeObserver | undefined
watch(terrainEnabled, (enabled) => { void controller?.setTerrain(enabled) })
onMounted(() => {
  try {
    controller = createMapController(
      container.value!,
      (value) => emit('selection', value),
      (message) => emit('notice', message),
      (state) => emit('boundary', state),
      (state, settled) => emit('navigation', state, settled),
      { terrain: terrainEnabled.value, onGroundClick: point => emit('ground', point),
        onCameraMove: props.trackWeather ? () => emit('cameraMove') : undefined },
    )
    if (props.trackWeather) {
      weatherResize = new ResizeObserver(() => emit('weatherResize'))
      weatherResize.observe(container.value!)
    }
    emit('ready', controller)
  } catch (error) {
    emit(
      'fatal',
      error instanceof Error ? error.message : '无法初始化 WebGL 地图',
    )
  }
})
onBeforeUnmount(() => { weatherResize?.disconnect(); controller?.destroy() })
</script>

<template>
  <div class="map-canvas">
    <div ref="container" class="map-engine" aria-label="Cesium 地图"></div>
    <WeatherEffect :effect="weatherEffect ?? 'none'" />
  </div>
</template>

<style scoped>
.map-canvas {
  position: absolute;
  inset: 64px 0 0;
  isolation: isolate;
}
.map-engine { position: absolute; inset: 0; }
:deep(.cesium-viewer-bottom) {
  left: auto !important;
  right: 6px;
  max-width: calc(100% - 500px);
}
:deep(.cesium-widget-credits) {
  font-size: 9px !important;
}
:deep(.cesium-viewer .cesium-widget-credits) {
  padding-bottom: 2px;
}
:deep(.cesium-performanceDisplay-defaultContainer) {
  top: 70px !important;
}
@media (max-width: 600px) {
  .map-canvas {
    top: 58px;
  }
  :deep(.cesium-viewer-bottom) {
    max-width: 65%;
    font-size: 8px;
  }
}
</style>
