<script setup lang="ts">
import { computed } from 'vue'
import { Crosshair, Layers } from '@lucide/vue'
import type { MapLayer } from '../../layers/types'
import type { NavigationReading } from '../../map/mapNavigation'
const props = defineProps<{ layers: MapLayer[]; navigation: NavigationReading | null }>()
const loadedCount = computed(
  () =>
    props.layers.filter((layer) => layer.id !== 'basemap' && layer.attached && layer.status === 'ready')
      .length,
)
const coordinateSource = computed(() => props.navigation?.pointer ? '鼠标' : '中心')
const coordinateText = computed(() => {
  const point = props.navigation?.pointer ?? props.navigation?.center
  return point
    ? `${point.longitude.toFixed(6)}°, ${point.latitude.toFixed(6)}° · 椭球高 ${point.height.toFixed(1)} m`
    : '暂无地面坐标'
})
</script>

<template>
  <div class="map-status" aria-label="地图状态">
    <span class="status-crs">WGS84</span>
    <span class="status-source">{{ coordinateSource }}</span>
    <span class="status-coordinates" :aria-label="coordinateSource === '鼠标' ? '鼠标坐标' : '可视中心坐标'"><Crosshair :size="14" aria-hidden="true" /><span>{{ coordinateText }}</span></span>
    <span class="status-scale"><span v-if="navigation?.scale" class="map-scale" aria-label="地图比例尺" :style="{ width: `${navigation.scale.pixels}px` }">{{ navigation.scale.label }}</span></span>
    <span class="status-layers"><Layers :size="14" aria-hidden="true" />已加载 {{ loadedCount }} 层</span>
  </div>
</template>

<style scoped>
.map-status {
  position: absolute;
  left: 16px;
  bottom: 12px;
  z-index: 3;
  height: 36px;
  width: 720px;
  max-width: calc(100% - 160px);
  box-sizing: border-box;
  background: #fff;
  border: 1px solid #d5dfeb;
  box-shadow: 0 2px 8px #243b5314;
  border-radius: 7px;
  padding: 6px 12px;
  display: flex;
  align-items: center;
  gap: 12px;
  font-size: 12px;
  color: #334155;
  font-variant-numeric: tabular-nums;
  pointer-events: none;
}
.map-status > span {
  display: flex;
  align-items: center;
  gap: 5px;
}
.status-crs { flex-shrink: 0; font-weight: 600; color: #1d4ed8; }
.status-source { flex: 0 0 24px; }
.status-coordinates { flex: 1; min-width: 0; }
.status-coordinates > svg { flex-shrink: 0; }
.status-coordinates > span { min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.status-scale { flex: 0 0 100px; justify-content: center; }
.status-layers { flex: 0 0 112px; padding-left: 12px; border-left: 1px solid #dce4ee; white-space: nowrap; }
.map-status .map-scale { display: block; flex-shrink: 0; text-align: center; border: solid #61748d; border-width: 0 1px 2px; padding-bottom: 3px; color: #61748d; }
@media (max-width: 900px) {
  .map-status .status-layers {
    display: none;
  }
}
@media (max-width: 600px) {
  .map-status {
    left: 12px;
    bottom: 12px;
    max-width: calc(100% - 24px);
    font-size: 12px;
    padding: 6px 8px;
    gap: 9px;
  }
}
</style>
