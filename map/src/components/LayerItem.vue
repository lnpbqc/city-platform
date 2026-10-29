<script setup lang="ts">
import { computed, ref } from 'vue'
import {
  Box,
  LoaderCircle,
  Eye,
  EyeOff,
  LocateFixed,
  X,
  Download,
  ArrowUpRight,
  ArrowUp,
  ArrowDown,
} from '@lucide/vue'
import { fetchLayerDownload, layerDownload } from '../layerDownload'
import type { MapLayer } from '../types'
import { objectCountLabel } from '../layerTree'
const props = defineProps<{ layer: MapLayer; canMoveUp?: boolean; canMoveDown?: boolean; ordering?: boolean }>()
const downloadTarget = computed(() => layerDownload(props.layer))
const downloading = ref(false)
const downloadError = ref('')
async function download() {
  if (downloading.value) return
  downloading.value = true
  downloadError.value = ''
  const target = downloadTarget.value
  try {
    const blob = await fetchLayerDownload(target.url)
    const url = URL.createObjectURL(blob)
    const anchor = document.createElement('a')
    anchor.href = url
    anchor.download = target.filename
    document.body.append(anchor)
    anchor.click()
    anchor.remove()
    setTimeout(() => URL.revokeObjectURL(url), 1000)
  } catch (error) {
    downloadError.value =
      error instanceof Error ? error.message : '下载失败，请重试'
  } finally {
    downloading.value = false
  }
}
const emit = defineEmits<{
  toggle: []
  load: []
  locate: []
  remove: []
  opacity: [value: number]
  move: [direction: number]
}>()
function changeOpacity(event: Event) {
  emit('opacity', Number((event.target as HTMLInputElement).value))
}
</script>

<template>
  <article class="layer-item" :class="{ detached: !layer.attached }">
    <div class="layer-main">
      <button
        class="visibility-button"
        :class="{ enabled: layer.attached && layer.visible }"
        :aria-label="`${layer.attached && layer.visible ? '隐藏' : '显示'}${layer.name}`"
        :aria-pressed="layer.attached && layer.visible"
        @click="emit('toggle')"
      >
        <LoaderCircle
          v-if="layer.status === 'loading'"
          :size="17"
          class="spin"
        /><Eye v-else-if="layer.attached && layer.visible" :size="17" /><EyeOff
          v-else
          :size="17"
        /></button
      ><span
        class="layer-symbol"
        :class="
          layer.id.includes('roads')
            ? 'line-symbol'
            : layer.id.includes('areas')
              ? 'area-symbol'
              : layer.type === '3dtiles' || layer.id === 'campus-buildings'
                ? 'box-symbol'
                : 'point-symbol'
        "
        :style="{ '--layer-color': layer.color }"
        ><Box
          v-if="layer.type === '3dtiles' || layer.id === 'campus-buildings'"
          :size="18"
      /></span>
      <div class="layer-name">
        <strong>{{ layer.name }}</strong
        ><span
          >{{ layer.id === 'basemap' ? '影像服务' : layer.type === '3dtiles' ? '3D Tiles' : 'GeoJSON' }}<i>·</i
          >{{
            layer.id === 'basemap' ? '地球底图' : layer.builtin
              ? layer.id === 'campus-buildings'
                ? '公开轮廓'
                : '合成演示'
              : '已登记'
          }}</span
        >
      </div>
      <button
        class="icon-button locate-button"
        :aria-label="`定位${layer.name}`"
        :disabled="layer.id === 'basemap' || !layer.attached || layer.status === 'idle' || layer.status === 'error'"
        @click="emit('locate')"
      >
        <LocateFixed :size="16" />
      </button>
    </div>
    <div class="layer-metadata">
      <span>{{ objectCountLabel(layer) }}</span>
      <span v-if="layer.orderable">叠加序 {{ (layer.order ?? 0) + 1 }}</span>
      <span v-else-if="layer.id !== 'basemap'">按深度绘制</span>
    </div>
    <div v-if="layer.status === 'loading'" class="load-progress" role="status">
      <progress :value="layer.progress ?? undefined" max="100" :aria-label="`${layer.name}加载进度`"></progress>
      <span>{{ layer.loadPhase || '正在加载资源' }}{{ layer.progress == null ? '' : ` · ${Math.round(layer.progress)}%` }}</span>
    </div>
    <div class="layer-detail">
      <span class="status" :class="layer.status"
        ><i></i
        >{{
          layer.status === 'loading'
            ? '正在加载'
            : layer.status === 'ready'
              ? '已加载'
              : layer.status === 'error'
                ? '加载失败'
                : '未加入地图'
        }}</span
      >
      <div class="layer-actions">
        <template v-if="layer.orderable">
          <button :aria-label="`上移${layer.name}`" :disabled="ordering || !canMoveUp" title="上移，更靠前显示" @click="emit('move', -1)"><ArrowUp :size="13" /></button>
          <button :aria-label="`下移${layer.name}`" :disabled="ordering || !canMoveDown" title="下移，更靠后显示" @click="emit('move', 1)"><ArrowDown :size="13" /></button>
        </template>
        <a
          v-if="layer.id !== 'basemap' && downloadTarget.external"
          :href="downloadTarget.url"
          target="_blank"
          rel="noopener noreferrer"
          :aria-label="`打开${layer.name}数据源`"
          title="打开三维服务入口；服务未提供完整下载包"
          ><ArrowUpRight :size="13"
        /></a>
        <button
          v-else-if="layer.id !== 'basemap'"
          :disabled="downloading"
          :aria-label="`${downloading ? '正在准备下载' : '下载'}${layer.name}`"
          :title="downloadTarget.label"
          @click="download"
        >
          <LoaderCircle v-if="downloading" :size="13" class="spin" /><Download
            v-else
            :size="13"
          />
        </button>
        <button
          v-if="layer.status === 'error' || !layer.attached"
          :aria-label="`加载${layer.name}`"
          @click="emit('load')"
        >
          {{ layer.status === 'error' ? '重试' : '加载' }}</button
        ><button
          v-if="layer.attached"
          :aria-label="`从地图移除${layer.name}`"
          title="仅从地图移除"
          @click="emit('remove')"
        >
          <X :size="13" />
        </button>
      </div>
    </div>
    <div
      v-if="layer.attached && layer.status === 'ready'"
      class="opacity-control"
    >
      <span>不透明度</span
      ><input
        :value="layer.opacity"
        type="range"
        min="0"
        max="1"
        step="0.05"
        :aria-label="`${layer.name}不透明度`"
        @input="changeOpacity"
      /><output>{{ Math.round(layer.opacity * 100) }}%</output>
    </div>
    <p v-if="layer.source" class="layer-source" :title="layer.source">
      {{ layer.source }}
    </p>
    <p v-if="layer.error" class="layer-error">{{ layer.error }}</p>
    <p v-if="downloadError" class="layer-error" role="alert">
      {{ downloadError }}
    </p>
  </article>
</template>

<style scoped>
.layer-metadata { display: flex; flex-wrap: wrap; justify-content: space-between; gap: 4px; margin: 5px 0 5px 30px; font-size: 9px; color: #7a879a; }
.layer-item {
  padding: 6px 16px 10px;
  border-bottom: 1px solid #f1f4f8;
}
.layer-main {
  display: flex;
  align-items: center;
  gap: 8px;
  min-height: 38px;
}
.visibility-button {
  width: 22px;
  padding: 0;
  color: #a5afbc;
  flex-shrink: 0;
}
.visibility-button.enabled {
  color: #4b78c4;
}
.layer-symbol {
  width: 22px;
  height: 22px;
  display: grid;
  place-items: center;
  flex-shrink: 0;
  color: var(--layer-color);
}
.point-symbol:after {
  content: '';
  width: 9px;
  height: 9px;
  background: var(--layer-color);
  border-radius: 50%;
  box-shadow: 0 0 0 3px #347af015;
}
.line-symbol:after {
  content: '';
  width: 15px;
  height: 3px;
  background: var(--layer-color);
  transform: rotate(-35deg);
  border-radius: 2px;
}
.area-symbol:after {
  content: '';
  width: 13px;
  height: 12px;
  border: 1.5px solid var(--layer-color);
  background: #36b9ba20;
  transform: skewY(-15deg);
}
.layer-name {
  display: flex;
  flex-direction: column;
  gap: 3px;
  min-width: 0;
}
.layer-name strong {
  font-size: 12px;
  font-weight: 500;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.layer-name > span {
  font-size: 9px;
  color: #99a3b2;
  display: flex;
  align-items: center;
  gap: 5px;
}
.layer-name i {
  font-style: normal;
}
.locate-button {
  margin-left: auto;
  flex-shrink: 0;
  width: 24px;
}
.layer-detail {
  padding-left: 60px;
  display: flex;
  align-items: center;
  min-height: 22px;
  gap: 5px;
  justify-content: space-between;
}
.status {
  font-size: 9px;
  display: flex;
  align-items: center;
  gap: 5px;
  color: #9aa6b5;
  white-space: nowrap;
}
.status i {
  height: 4px;
  width: 4px;
  background: currentColor;
  border-radius: 50%;
}
.status.ready {
  color: #699a8d;
}
.status.loading {
  color: #447ed4;
}
.load-progress { display: grid; gap: 4px; margin: 6px 0; font-size: 10px; color: #61748d; }
.load-progress progress { width: 100%; height: 5px; accent-color: var(--blue); }
.status.error {
  color: #cf625c;
}
.layer-actions {
  display: flex;
  gap: 7px;
  align-items: center;
}
.layer-actions button,
.layer-actions a {
  font-size: 9px;
  padding: 2px;
  color: #9aa6b5;
  min-width: 13px;
}
.layer-actions a {
  display: inline-flex;
}
.opacity-control {
  display: flex;
  align-items: center;
  gap: 9px;
  font-size: 9px;
  color: #a0aab8;
  margin: 6px 0 0 60px;
}
.opacity-control input {
  height: 3px;
  flex: 1;
  min-width: 20px;
}
.opacity-control output {
  font-size: 9px;
  min-width: 28px;
  text-align: right;
  font-variant-numeric: tabular-nums;
  color: #8190a4;
}
.detached .layer-name strong {
  color: #7d8b9e;
}
.layer-error {
  margin: 6px 0 0 60px;
  font-size: 10px;
  line-height: 1.6;
  color: #c05a55;
  overflow-wrap: anywhere;
}
.layer-source {
  font-size: 9px;
  color: #a1acba;
  margin: 7px 0 0 60px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
</style>
