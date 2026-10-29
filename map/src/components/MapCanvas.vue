<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref } from 'vue'
import { createMapController, type MapController } from '../mapController'
import type { Selection } from '../types'
import type { BoundaryState } from '../regionBoundary'
import type { NavigationReading } from '../mapNavigation'
const emit = defineEmits<{
  ready: [controller: MapController]
  selection: [value: Selection | null]
  notice: [message: string]
  fatal: [message: string]
  boundary: [state: BoundaryState]
  navigation: [state: NavigationReading, settled: boolean]
}>()
const container = ref<HTMLElement | null>(null)
let controller: MapController | undefined
onMounted(() => {
  try {
    controller = createMapController(
      container.value!,
      (value) => emit('selection', value),
      (message) => emit('notice', message),
      (state) => emit('boundary', state),
      (state, settled) => emit('navigation', state, settled),
    )
    emit('ready', controller)
  } catch (error) {
    emit(
      'fatal',
      error instanceof Error ? error.message : '无法初始化 WebGL 地图',
    )
  }
})
onBeforeUnmount(() => controller?.destroy())
</script>

<template>
  <div ref="container" class="map-canvas" aria-label="Cesium 三维地图"></div>
</template>

<style scoped>
.map-canvas {
  position: absolute;
  inset: 64px 0 0;
}
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
