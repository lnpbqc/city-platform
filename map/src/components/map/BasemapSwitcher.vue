<script setup lang="ts">
import { nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import type { MapController } from '../../map/mapController'
import { readBasemap, saveBasemap, readAnnotations, saveAnnotations, type BasemapKind } from '../../map/basemapSetting'

const props = defineProps<{
  controller?: Pick<MapController, 'setBasemap'>
  vectorAvailable: boolean
}>()
const root = ref<HTMLElement>()
const trigger = ref<HTMLButtonElement>()
const expanded = ref(false)
const selected = ref<BasemapKind>('imagery')
const busy = ref<BasemapKind | null>(null)
const options = [{ kind: 'imagery', label: '影像' }, { kind: 'vector', label: '矢量' }] as const
const annotations = ref({ imagery: readAnnotations(storage(), 'imagery'), vector: readAnnotations(storage(), 'vector') })
let revision = 0
function storage() {
  try { return window.localStorage } catch { return undefined }
}
async function choose(kind: BasemapKind, labels = annotations.value[kind]) {
  if (!props.controller || kind === 'vector' && !props.vectorAvailable) return
  const request = ++revision
  busy.value = kind
  try {
    if (await props.controller.setBasemap(kind, { annotations: props.vectorAvailable && labels }) && request === revision) {
      selected.value = kind
      saveBasemap(storage(), kind)
      annotations.value[kind] = labels
      saveAnnotations(storage(), kind, labels)
    }
  } finally {
    if (request === revision) busy.value = null
  }
}
async function changeAnnotations(kind: BasemapKind, event: Event) {
  const input = event.target as HTMLInputElement
  if (props.vectorAvailable && props.controller) {
    if (selected.value === kind || busy.value === kind) await choose(kind, input.checked)
    else {
      annotations.value[kind] = input.checked
      saveAnnotations(storage(), kind, input.checked)
    }
  }
  input.checked = annotations.value[kind]
}
watch(() => props.controller, value => {
  const kind = readBasemap(storage(), props.vectorAvailable)
  if (value && (kind === 'vector' || props.vectorAvailable && annotations.value.imagery)) void choose(kind)
}, { immediate: true })
function outside(event: PointerEvent) {
  if (!root.value?.contains(event.target as Node)) expanded.value = false
}
function open() {
  expanded.value = true
  void nextTick(() => root.value?.querySelector<HTMLButtonElement>(`[data-basemap="${selected.value}"]`)?.focus())
}
function keydown(event: KeyboardEvent) {
  if (event.key !== 'Escape') return
  event.stopPropagation()
  expanded.value = false
  void nextTick(() => trigger.value?.focus())
}
function focusout(event: FocusEvent) {
  if (!root.value?.contains(event.relatedTarget as Node)) expanded.value = false
}
onMounted(() => document.addEventListener('pointerdown', outside))
onBeforeUnmount(() => {
  revision++
  document.removeEventListener('pointerdown', outside)
})
</script>

<template>
  <div ref="root" class="basemap-switcher" :class="{ expanded }" role="group" aria-label="底图切换"
    :aria-busy="!!busy" @mouseenter="expanded = true" @mouseleave="expanded = false"
    @keydown="keydown" @focusout="focusout">
    <button ref="trigger" class="stack-trigger" :aria-label="`展开底图选择，当前${selected === 'imagery' ? '影像' : '矢量'}`"
      :aria-expanded="expanded" :aria-hidden="expanded" :tabindex="expanded ? -1 : 0" @click="open"></button>
    <div v-for="option in options" :key="option.kind" class="basemap-card"
      :class="{ selected: selected === option.kind, behind: selected !== option.kind }">
    <button class="basemap-select"
      :data-basemap="option.kind" :aria-label="`选择${option.label}底图${option.kind === 'vector' && !vectorAvailable ? '，需配置地图服务' : ''}`"
      :aria-pressed="selected === option.kind" :tabindex="expanded ? 0 : -1"
      :disabled="!controller || option.kind === 'vector' && !vectorAvailable"
      :title="option.kind === 'vector' && !vectorAvailable ? '需配置天地图 Key 后使用' : `${option.label}底图`"
      @click="choose(option.kind)">
      <span class="thumbnail" :class="option.kind" aria-hidden="true"><i></i></span>
      <span class="caption">{{ option.label }}<span v-if="selected === option.kind" aria-hidden="true">✓</span></span>
      <span v-if="busy === option.kind" class="availability" role="status">正在切换…</span>
      <span v-else-if="option.kind === 'vector' && !vectorAvailable" class="availability">需配置地图服务</span>
    </button>
    <label class="annotation-option" :title="vectorAvailable ? '显示道路名、地名，单独消耗天地图注记额度' : '需配置天地图 Key 后使用注记'">
      <input type="checkbox" :aria-label="`${option.label}显示注记`" :checked="annotations[option.kind]"
        :disabled="!controller || !vectorAvailable" :tabindex="expanded ? 0 : -1"
        @change="changeAnnotations(option.kind, $event)" />显示注记
    </label>
    </div>
  </div>
</template>

<style scoped>
.basemap-switcher { position: absolute; z-index: 4; right: 20px; bottom: calc(var(--basemap-bottom, 60px)); width: 100px; height: 106px; }
.basemap-switcher.expanded { width: 200px; }
.basemap-card { position: absolute; right: 0; bottom: 0; width: 96px; height: 100px; border: 2px solid white; border-radius: 7px; overflow: hidden; background: white; box-shadow: 0 3px 12px #243b5326; text-align: left; transition: transform .2s ease, border-color .2s ease; }
.basemap-select { position: absolute; inset: 0 0 26px; width: 100%; color: inherit; text-align: left; }
.annotation-option { position: absolute; bottom: 0; display: flex; align-items: center; gap: 4px; width: 100%; height: 26px; padding: 0 6px; box-sizing: border-box; color: #42556c; font-size: 12px; cursor: pointer; }
.annotation-option input { width: 14px; height: 14px; margin: 0; accent-color: var(--blue); }
.annotation-option:has(input:disabled) { color: #73859a; cursor: default; }
.basemap-card.selected { z-index: 2; border-color: var(--blue); }
.basemap-card.behind { z-index: 1; transform: translate(-7px, -6px); }
.expanded .basemap-card.behind { transform: translateX(-104px); }
.basemap-card:focus-within { outline: 2px solid var(--blue); outline-offset: 3px; }
.stack-trigger:focus-visible { outline: 2px solid var(--blue); outline-offset: 3px; }
.basemap-select:disabled { cursor: not-allowed; }
.thumbnail { position: absolute; inset: 0; display: block; }
.thumbnail.imagery { background: linear-gradient(135deg, transparent 38%, #b2ae91 39% 42%, transparent 43%), repeating-linear-gradient(12deg, #68745b 0 12px, #839077 13px 24px, #777e68 25px 34px); }
.thumbnail.vector { background: linear-gradient(135deg, transparent 38%, #f2d696 39% 44%, transparent 45%), repeating-linear-gradient(0deg, transparent 0 13px, #fff 14px 17px), repeating-linear-gradient(90deg, #e2e8db 0 18px, #fff 19px 22px); }
.thumbnail i { position: absolute; top: -30px; left: 63%; width: 15px; height: 150px; background: #93c4d0; transform: rotate(28deg); }
.imagery i { background: #547b82; }
.caption { position: absolute; inset: auto 0 0; display: flex; justify-content: space-between; padding: 4px 7px; background: #ffffffed; color: #42556c; font-size: 12px; font-weight: 550; }
.selected .caption { color: var(--blue); }
.availability { position: absolute; inset: 0 0 auto; padding: 3px 1px; background: #ffffffed; color: #596a7e; font-size: 10px; text-align: center; }
.stack-trigger { position: absolute; z-index: 3; inset: 6px 0 0 4px; border-radius: 7px; cursor: pointer; }
.expanded .stack-trigger { opacity: 0; pointer-events: none; }
@media (max-width: 900px) { .basemap-switcher { right: 12px; } }
@media (prefers-reduced-motion: reduce) { .basemap-card { transition: none; } }
</style>
