<script setup lang="ts">
import UiTooltip from '../common/UiTooltip.vue'
import { Plus, Minus, House, Mountain, Navigation2, MapPin } from '@lucide/vue'
import { useTerrainSetting } from '../../composables/useTerrainSetting'
defineProps<{ is2D: boolean; heading: number; addPoi?: boolean }>()
const { terrainEnabled, terrainAvailable } = useTerrainSetting()
function toggleTerrain() { terrainEnabled.value = !terrainEnabled.value }
const emit = defineEmits<{
  zoom: [direction: number]
  home: []
  mode: []
  tilt: []
  north: []
  poi: []
}>()
</script>

<template>
  <div class="map-tools panel" role="toolbar" aria-label="地图浏览工具">
    <UiTooltip v-if="addPoi" text="添加 POI"><button class="icon-button" aria-label="添加 POI" @click="emit('poi')"><MapPin :size="18" /></button></UiTooltip>
    <UiTooltip :text="`指北 · 当前方向 ${(Math.round(heading * 180 / Math.PI) + 360) % 360}°`"><button class="icon-button" aria-label="指北" @click="emit('north')"><Navigation2 :size="18" :style="{ transform: `rotate(${-heading}rad)` }" /></button></UiTooltip>
    <UiTooltip text="放大地图"><button class="icon-button" aria-label="放大地图" @click="emit('zoom', 1)"><Plus :size="19" /></button></UiTooltip>
    <UiTooltip text="缩小地图"><button class="icon-button" aria-label="缩小地图" @click="emit('zoom', -1)"><Minus :size="19" /></button></UiTooltip>
    <span class="tool-divider"></span>
    <UiTooltip text="复位至所选地区"><button class="icon-button" aria-label="复位至所选地区" @click="emit('home')"><House :size="18" /></button></UiTooltip>
    <UiTooltip :text="is2D ? '切换三维' : '切换二维'"><button class="icon-button mode-button" :aria-label="is2D ? '切换三维' : '切换二维'" @click="emit('mode')">{{ is2D ? '3D' : '2D' }}</button></UiTooltip>
    <UiTooltip :text="is2D ? '二维模式下不可调整俯仰' : '调整地图俯仰'"><button class="icon-button" aria-label="调整地图俯仰" :disabled="is2D" @click="emit('tilt')"><Mountain :size="18" /></button></UiTooltip>
    <UiTooltip :text="terrainAvailable ? (terrainEnabled ? '关闭起伏地形' : '显示起伏地形') : '未配置 Cesium ion Token，地形不可用'"><button class="icon-button mode-button terrain-button" :aria-pressed="terrainAvailable && terrainEnabled" :aria-label="terrainAvailable ? (terrainEnabled ? '关闭地形' : '开启地形') : '地形不可用'" :disabled="!terrainAvailable" @click="toggleTerrain">地形</button></UiTooltip>
  </div>
</template>

<style scoped>
.map-tools {
  position: absolute;
  right: 20px;
  top: 84px;
  display: flex;
  flex-direction: column;
  padding: 5px;
  gap: 3px;
  z-index: 2;
}
.map-tools .icon-button {
  height: 34px;
  width: 34px;
  color: #61748d;
}
.tool-divider {
  height: 1px;
  background: #edf0f5;
  margin: 3px 4px;
}
.mode-button {
  font-size: 11px;
  font-weight: 600;
  letter-spacing: 0.3px;
}
.map-tools .terrain-button[aria-pressed='true'] {
  color: var(--blue);
  background: #edf3fc;
}
@media (max-width: 900px) {
  .map-tools {
    top: 76px;
    right: 12px;
  }
}
</style>
