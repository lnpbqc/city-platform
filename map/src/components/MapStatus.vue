<script setup lang="ts">
import { computed } from 'vue'
import { Crosshair } from '@lucide/vue'
import type { MapLayer } from '../types'
import type { NavigationReading } from '../mapNavigation'
const props = defineProps<{ layers: MapLayer[]; navigation: NavigationReading | null }>()
const loadedCount = computed(
  () =>
    props.layers.filter((layer) => layer.attached && layer.status === 'ready')
      .length,
)
</script>

<template>
  <div class="map-status">
    <span aria-label="鼠标坐标"><Crosshair :size="12" />{{ navigation?.pointer
      ? `${navigation.pointer.longitude.toFixed(6)}°, ${navigation.pointer.latitude.toFixed(6)}° · 椭球高 ${navigation.pointer.height.toFixed(1)} m`
      : 'WGS84 · 鼠标移到地面查看坐标' }}</span>
    <span v-if="navigation?.scale" class="map-scale" aria-label="地图比例尺" :style="{ width: `${navigation.scale.pixels}px` }">{{ navigation.scale.label }}</span>
    <span>{{ loadedCount }} 个图层已加载</span>
  </div>
</template>

<style scoped>
.map-status {
  position: absolute;
  left: 20px;
  bottom: 16px;
  background: #ffffffeb;
  border-radius: 4px;
  padding: 6px 10px;
  display: flex;
  align-items: center;
  gap: 15px;
  font-size: 9px;
  color: #7f8b9c;
  pointer-events: none;
}
.map-status > span {
  display: flex;
  align-items: center;
  gap: 5px;
}
.map-status .map-scale { display: block; flex-shrink: 0; text-align: center; border: solid #61748d; border-width: 0 1px 2px; padding-bottom: 3px; color: #61748d; }
@media (max-width: 900px) {
  .map-status span:last-child {
    display: none;
  }
}
@media (max-width: 600px) {
  .map-status {
    left: 12px;
    bottom: 20px;
    font-size: 8px;
    padding: 5px 7px;
    gap: 9px;
  }
  .map-status span:first-child {
    display: none;
  }
}
</style>
