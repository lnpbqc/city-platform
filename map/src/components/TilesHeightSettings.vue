<script setup lang="ts">
import { ref, watch } from 'vue'
import { tilesPlacement, type MapLayer, type TilesPlacement } from '../types'

const props = defineProps<{ placement: MapLayer }>()
const emit = defineEmits<{ save: [placement: TilesPlacement] }>()
const offset = ref<number | ''>(0)
const align = ref(true)
const manual = ref(false)
const longitude = ref<number | ''>('')
const latitude = ref<number | ''>('')
const height = ref<number | ''>('')

watch(() => JSON.stringify(tilesPlacement(props.placement)), () => {
  const { tiles_height_offset_m, tiles_ground_anchor: anchor, tiles_align_to_terrain } = tilesPlacement(props.placement)
  offset.value = tiles_height_offset_m
  align.value = tiles_align_to_terrain ?? true
  manual.value = !!anchor
  longitude.value = anchor?.longitude ?? ''
  latitude.value = anchor?.latitude ?? ''
  height.value = anchor?.height ?? ''
}, { immediate: true })

function save() {
  const anchor = manual.value && longitude.value !== '' && latitude.value !== '' && height.value !== ''
    ? { longitude: longitude.value, latitude: latitude.value, height: height.value }
    : null
  if (offset.value === '' || (align.value && manual.value && !anchor)) return
  emit('save', {
    tiles_height_offset_m: offset.value,
    tiles_align_to_terrain: align.value,
    tiles_ground_anchor: anchor,
  })
}
</script>

<template>
  <details class="tiles-height">
    <summary>模型高度</summary>
    <form @submit.prevent="save">
      <label>高度偏移（米）<input v-model.number="offset" type="number" step="any" required /></label>
      <label class="terrain-align"><input v-model="align" type="checkbox" />对齐地形</label>
      <template v-if="align">
        <label class="terrain-align"><input v-model="manual" type="checkbox" />使用手动锚点</label>
        <template v-if="manual">
          <label>经度（°）<input v-model.number="longitude" type="number" min="-180" max="180" step="any" required /></label>
          <label>纬度（°）<input v-model.number="latitude" type="number" min="-90" max="90" step="any" required /></label>
          <label>原始椭球高（米）<input v-model.number="height" type="number" step="any" required /></label>
        </template>
        <p v-else-if="placement.tilesModelOrigin">
          模型原点 {{ placement.tilesModelOrigin.longitude.toFixed(6) }}°，{{ placement.tilesModelOrigin.latitude.toFixed(6) }}°<br>
          原始椭球高 {{ placement.tilesModelOrigin.height.toFixed(2) }} 米
        </p>
        <p v-else-if="placement.tilesModelOrigin === undefined">加载模型后读取原点坐标。</p>
        <p v-if="placement.tilesTerrainNotice" role="status">{{ placement.tilesTerrainNotice }}</p>
      </template>
      <button class="text-button" type="submit">保存高度设置</button>
    </form>
  </details>
</template>

<style scoped>
.tiles-height { margin: 5px 0 5px 30px; color: #53657e; font-size: 11px; }
summary { cursor: pointer; }
form { display: grid; gap: 6px; margin-top: 6px; }
label { display: grid; grid-template-columns: minmax(0, 1fr) minmax(0, 1fr); align-items: center; gap: 6px; }
.terrain-align { display: flex; }
input[type="number"] { width: 100%; min-width: 0; }
p { margin: 0; }
button { justify-self: start; }
</style>
