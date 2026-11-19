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
  ChevronDown,
  SlidersHorizontal,
} from '@lucide/vue'
import { fetchLayerDownload, layerDownload, startTilesZipDownload } from '../../layers/layerDownload'
import type { MapLayer } from '../../layers/types'
import { objectCountLabel } from '../../layers/layerTree'
import RenderStatus from '../data/RenderStatus.vue'
import UiTooltip from '../common/UiTooltip.vue'
const props = defineProps<{ layer: MapLayer; canMoveUp?: boolean; canMoveDown?: boolean; ordering?: boolean;
  allowCalibration?: boolean; downloadBlocked?: boolean }>()
const downloadTarget = computed(() => layerDownload(props.layer))
const downloading = ref(false)
const downloadError = ref('')
const detailsOpen = ref(false)
const calibrationHint = computed(() => {
  const layer = props.layer
  if (!layer.tiles_calibration_allowed) return '上传本地 3D Tiles 副本后可校准。'
  if (!layer.attached || !layer.visible) return '显示模型后可校准。'
  if (layer.status === 'loading') return '等待模型加载后校准。'
  if (layer.status !== 'ready') return '模型加载完成后可校准。'
  if (layer.tilesTerrainNotice?.startsWith('正在采样')) return '等待地形采样后校准。'
  return ''
})
async function download() {
  if (downloading.value) return
  if (props.downloadBlocked) {
    downloadError.value = '请先保存校准，或取消预览后再下载。'
    return
  }
  downloading.value = true
  downloadError.value = ''
  const target = downloadTarget.value
  try {
    if ('native' in target) { await startTilesZipDownload(target); return }
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
  roadMaxLevel: [value: number]
  calibrate: []
  move: [direction: number]
}>()
function changeOpacity(event: Event) {
  emit('opacity', Number((event.target as HTMLInputElement).value))
}
</script>

<template>
  <article class="layer-item" :class="{ detached: !layer.attached, 'details-open': detailsOpen }">
    <div class="layer-main">
      <span class="layer-symbol" :class="layer.id.includes('roads') ? 'line-symbol' : layer.id.includes('areas') ? 'area-symbol' : layer.type === '3dtiles' || layer.id === 'campus-buildings' ? 'box-symbol' : 'point-symbol'" :style="{ '--layer-color': layer.color }"><Box v-if="layer.type === '3dtiles' || layer.id === 'campus-buildings'" :size="18" aria-hidden="true" /></span>
      <button class="layer-name" :aria-label="`查看${layer.name}详情`" :aria-expanded="detailsOpen" :aria-controls="`layer-details-${layer.id}`" @click="detailsOpen = !detailsOpen">
        <strong>{{ layer.name }}</strong>
      </button>
      <UiTooltip :text="layer.attached && layer.visible ? '隐藏图层' : '显示图层'">
      <button class="visibility-button" :class="{ enabled: layer.attached && layer.visible }"
        :aria-label="`${layer.attached && layer.visible ? '隐藏' : '显示'}${layer.name}`"
        :aria-pressed="layer.attached && layer.visible" @click="emit('toggle')">
        <LoaderCircle v-if="layer.status === 'loading'" :size="16" class="spin" aria-hidden="true" />
        <Eye v-else-if="layer.attached && layer.visible" :size="16" aria-hidden="true" /><EyeOff v-else :size="16" aria-hidden="true" />
      </button></UiTooltip>
      <UiTooltip text="定位到图层">
      <button class="locate-button" :aria-label="`定位${layer.name}`"
        :disabled="layer.id === 'basemap' || !layer.attached || layer.status === 'idle' || layer.status === 'error'" @click="emit('locate')">
        <LocateFixed :size="16" aria-hidden="true" />
      </button></UiTooltip>
      <button class="details-toggle" :aria-label="`${detailsOpen ? '收起' : '展开'}${layer.name}设置`" :aria-expanded="detailsOpen" :aria-controls="`layer-details-${layer.id}`" @click="detailsOpen = !detailsOpen"><ChevronDown :size="16" aria-hidden="true" /></button>
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
      <span class="object-count">{{ objectCountLabel(layer) }}</span>
      <button v-if="layer.status === 'error' || !layer.attached" :aria-label="`加载${layer.name}`" @click="emit('load')">{{ layer.status === 'error' ? '重试' : '加载' }}</button>
    </div>
    </div>
    <div v-if="layer.status === 'loading'" class="load-progress" role="status">
      <progress :value="layer.progress ?? undefined" max="100" :aria-label="`${layer.name}加载进度`"></progress>
      <span>{{ layer.loadPhase || '正在加载资源' }}{{ layer.progress == null ? '' : ` · ${Math.round(layer.progress)}%` }}</span>
    </div>
    <RenderStatus v-if="layer.render && layer.render.status !== 'succeeded'" :render="layer.render" :asset-id="layer.asset_id" :version="layer.asset_version" :category="layer.category" @updated="layer.render = $event" />
    <div :id="`layer-details-${layer.id}`" v-show="detailsOpen" class="layer-expanded">
      <strong class="settings-title">图层设置</strong>
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
      <label v-if="layer.category === '道路' || layer.category === '线状网络' || layer.id === 'demo-roads'" class="road-level-control">
        道路显示到
        <select :value="layer.road_max_level ?? 2" :aria-label="`道路显示到 ${layer.name}`" @change="emit('roadMaxLevel', Number(($event.target as HTMLSelectElement).value))">
          <option :value="1">第 1 级 · 高速/快速路/主干路</option>
          <option :value="2">第 2 级 · 增加次干路/三级道路</option>
          <option :value="3">第 3 级 · 增加住宅街道/普通街道</option>
          <option :value="4">第 4 级 · 增加服务道路/步行等</option>
        </select>
      </label>
    <div v-if="layer.type === '3dtiles'" class="calibration-trigger">
      <button v-if="layer.tiles_calibration_allowed" class="calibration-button" type="button" :disabled="!allowCalibration || !!calibrationHint"
        :aria-describedby="calibrationHint ? `calibration-hint-${layer.id}` : undefined" @click="emit('calibrate')">
        <SlidersHorizontal :size="14" aria-hidden="true" />校准模型
      </button>
      <span v-if="calibrationHint" :id="`calibration-hint-${layer.id}`" class="calibration-hint">{{ calibrationHint }}</span>
    </div>
      <dl class="layer-metadata">
        <dt>数据</dt><dd>{{ layer.id === 'basemap' ? '影像服务 · 地球底图' : `${layer.type === '3dtiles' ? '3D Tiles' : 'GeoJSON'} · ${layer.builtin ? layer.id === 'campus-buildings' ? '公开轮廓' : '合成演示' : '已登记'}` }}</dd>
        <template v-if="layer.id !== 'basemap'"><dt>绘制</dt><dd>{{ layer.orderable ? `叠加序 ${(layer.order ?? 0) + 1}` : '按深度绘制' }}</dd></template>
      </dl>
      <p v-if="layer.source" class="layer-source" :title="layer.source">
        来源 · {{ layer.source }}
      </p>
      <RenderStatus v-if="layer.render?.status === 'succeeded'" :render="layer.render" :asset-id="layer.asset_id" :version="layer.asset_version" :category="layer.category" @updated="layer.render = $event" />
      <div class="layer-actions">
        <template v-if="layer.orderable">
          <UiTooltip :text="ordering ? '正在保存图层顺序，请稍候' : !canMoveUp ? '没有可上移的位置' : '上移，更靠前显示'"><button :aria-label="`上移${layer.name}`" :disabled="ordering || !canMoveUp" @click="emit('move', -1)"><ArrowUp :size="13" aria-hidden="true" /><span>上移</span></button></UiTooltip>
          <UiTooltip :text="ordering ? '正在保存图层顺序，请稍候' : !canMoveDown ? '没有可下移的位置' : '下移，更靠后显示'"><button :aria-label="`下移${layer.name}`" :disabled="ordering || !canMoveDown" @click="emit('move', 1)"><ArrowDown :size="13" aria-hidden="true" /><span>下移</span></button></UiTooltip>
        </template>
        <UiTooltip v-if="layer.id !== 'basemap' && downloadTarget.external" text="打开三维服务入口；服务未提供完整下载包"><a
          :href="downloadTarget.url"
          target="_blank"
          rel="noopener noreferrer"
          :aria-label="`打开${layer.name}数据源`"
          ><ArrowUpRight :size="13" aria-hidden="true" /><span>数据源</span></a></UiTooltip>
        <UiTooltip v-else-if="layer.id !== 'basemap'" :text="downloadBlocked ? '请先保存校准或取消预览' : downloadTarget.label"><button
          :disabled="downloading"
          :aria-label="`${downloading ? ('native' in downloadTarget ? '正在校验模型文件' : '正在准备下载') : '下载'} ${layer.name}`"
          @click="download"
        >
          <LoaderCircle v-if="downloading" :size="13" class="spin" aria-hidden="true" /><Download
            v-else
            :size="13"
            aria-hidden="true"
          />
          <span>{{ downloading ? '准备中' : '下载' }}</span>
        </button></UiTooltip>
        <UiTooltip text="仅从地图移除"><button
          v-if="layer.attached"
          :aria-label="`从地图移除${layer.name}`"
          @click="emit('remove')"
        >
          <X :size="13" aria-hidden="true" /><span>移除</span>
        </button></UiTooltip>
      </div>
    </div>
    <p v-if="layer.error" class="layer-error" role="alert">{{ layer.error }}</p>
    <p v-if="downloadError" class="layer-error" role="alert">
      {{ downloadError }}
    </p>
  </article>
</template>

<style scoped>
.layer-item {
  --layer-inset: 0px;
  color: #1e293b;
  padding: 8px;
  border-bottom: 1px solid var(--line);
}
.layer-metadata { display: grid; grid-template-columns: auto minmax(0, 1fr); gap: 4px 12px; margin: 0; padding-top: 10px; border-top: 1px solid var(--line); font-size: 12px; color: #475569; }
.layer-metadata dt { color: #64748b; }
.layer-metadata dd { margin: 0; overflow-wrap: anywhere; }
.layer-main {
  display: grid;
  grid-template-columns: 22px minmax(0, 1fr) 32px 32px 24px;
  grid-template-rows: 32px auto;
  align-items: center;
  column-gap: 4px;
  min-height: 48px;
}
.visibility-button {
  min-height: 32px;
  padding: 0;
  border-radius: 5px;
  color: #475569;
  flex-shrink: 0;
}
.visibility-button.enabled {
  color: #1d4ed8;
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
  display: block;
  min-width: 0;
  width: 100%;
  height: 32px;
  padding: 0;
  color: inherit;
  text-align: left;
}
.layer-name strong {
  font-size: 14px;
  font-weight: 600;
  display: block;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.locate-button {
  flex-shrink: 0;
}
.layer-main :is(.visibility-button, .locate-button, .details-toggle) { display: inline-flex; align-items: center; justify-content: center; width: 100%; height: 32px; padding: 0; border-radius: 5px; color: #475569; }
.layer-main .visibility-button.enabled { color: #1d4ed8; }
.details-toggle[aria-expanded="true"] > svg { transform: rotate(180deg); }
.layer-detail > button { margin-left: auto; color: #1d4ed8; font-size: 12px; }
.layer-expanded { display: flex; flex-direction: column; gap: 10px; margin: 8px 0 4px 26px; padding: 12px; border: 1px solid var(--line); border-left: 3px solid #b8cff5; border-radius: 6px; background: #f5f8fc; }
.settings-title { font-size: 12px; font-weight: 600; color: #334155; }
.details-open .layer-main { grid-template-rows: minmax(32px, auto) auto; }
.details-open .layer-name { height: auto; min-height: 32px; }
.details-open .layer-name strong { white-space: normal; overflow-wrap: anywhere; }
.layer-item button:focus-visible { outline: 2px solid var(--blue); outline-offset: -2px; }
.object-count { min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-size: 12px; color: #64748b; }
.layer-detail {
  grid-column: 2 / -1;
  margin-left: var(--layer-inset);
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  min-height: 16px;
  gap: 4px 8px;
}
.status {
  font-size: 12px;
  display: flex;
  align-items: center;
  gap: 5px;
  color: #475569;
  white-space: nowrap;
}
.status i {
  height: 4px;
  width: 4px;
  background: currentColor;
  border-radius: 50%;
}
.status.ready {
  color: #36776b;
}
.status.loading {
  color: #1d4ed8;
}
.load-progress { display: grid; gap: 4px; margin: 6px 0; font-size: 12px; color: #475569; }
.load-progress progress { width: 100%; height: 5px; accent-color: var(--blue); }
.status.error {
  color: #b42318;
}
.layer-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  align-items: center;
  border-top: 1px solid var(--line);
  padding-top: 10px;
}
.layer-actions button,
.layer-actions a {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: 32px;
  min-height: 32px;
  padding: 2px 8px;
  gap: 4px;
  border: 1px solid #d5dfeb;
  border-radius: 5px;
  color: #475569;
  background: white;
  font-size: 12px;
}
.layer-actions :is(button:not(:disabled), a):hover,
.visibility-button:hover {
  color: var(--blue);
  background: #edf3fc;
}
.road-level-control { display: grid; gap: 4px; font-size: 12px; }
.road-level-control select { width: 100%; min-width: 0; font: inherit; }
.opacity-control {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 12px;
  color: #475569;
}
.opacity-control input {
  flex: 1;
  min-width: 20px;
  margin: 0;
}
.opacity-control output {
  min-width: 32px;
  text-align: right;
  font-variant-numeric: tabular-nums;
  color: #475569;
}
.detached .layer-name strong {
  color: #475569;
}
.layer-error {
  margin: 6px 0 0 var(--layer-inset);
  font-size: 12px;
  line-height: 1.6;
  color: #b42318;
  overflow-wrap: anywhere;
}
.layer-source {
  font-size: 12px;
  color: #475569;
  margin: 7px 0 0 var(--layer-inset);
  overflow-wrap: anywhere;
  white-space: normal;
}
.calibration-trigger {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 4px 8px;
}
.calibration-button {
  min-height: 28px;
  gap: 5px;
  padding: 4px 8px;
  border: 1px solid #dce7f7;
  border-radius: 5px;
  background: #f2f6fc;
  color: var(--blue);
  font-size: 12px;
}
.calibration-hint { font-size: 12px; color: #475569; overflow-wrap: anywhere; }
@media (max-width: 767px) {
  .layer-main { grid-template-columns: 22px minmax(0, 1fr) 44px 44px 44px; grid-template-rows: 44px auto; }
  .layer-name, .layer-main :is(.visibility-button, .locate-button, .details-toggle) { height: 44px; }
  .details-open .layer-main { grid-template-rows: minmax(44px, auto) auto; }
  .details-open .layer-name { height: auto; min-height: 44px; }
  .layer-actions :is(button, a), .calibration-button { min-width: 44px; min-height: 44px; }
}
@media (max-width: 380px) {
  .layer-item { padding-inline: 8px; }
  .layer-detail, .layer-metadata, .opacity-control, .calibration-trigger { margin-left: 0; }
}
</style>
