<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import MapCanvas from './MapCanvas.vue'
import TimeAxis from './TimeAxis.vue'
import { useTemporalLayers } from '../composables/useTemporalLayers'
import { mapLayer, type MapLayer } from '../types'
import type { MapController } from '../mapController'
import type { CameraState, NavigationReading } from '../mapNavigation'
import type { TemporalContext } from '../temporalTypes'
import { demoRegion } from '../regions'

const props = defineProps<{ active: boolean; layers: MapLayer[]; camera: CameraState; initialTime: TemporalContext; recovery?: number }>()
const emit = defineEmits<{ ready: [controller: MapController]; navigation: [value: NavigationReading]; time: [value: TemporalContext] }>()
const layers = ref<MapLayer[]>([])
const error = ref('')
let controller: MapController | undefined
let alive = true, version = 0
const temporal = useTemporalLayers(() => layers.value, () => controller)
const { time, resolution, rate, playing, maximum, position, times, loading, metadataLoading, counts, errors, allMissing } = temporal
time.value = props.initialTime.time
resolution.value = props.initialTime.resolution
watch([time, resolution], () => emit('time', { time: time.value, resolution: resolution.value }), { immediate: true })
const sourceKey = (layer: MapLayer) => JSON.stringify([layer.id, layer.asset_id, layer.asset_version, layer.url, layer.type])
const sources = computed(() => props.layers.filter(layer => layer.attached))
async function syncLayers() {
  const current = ++version
  if (!controller) return
  error.value = ''
  const desired = new Set(sources.value.map(sourceKey))
  for (const layer of [...layers.value]) if (!desired.has(sourceKey(layer))) {
    controller.remove(layer)
    layers.value = layers.value.filter(item => item !== layer)
  }
  await Promise.all(sources.value.map(async source => {
    let layer = layers.value.find(layer => sourceKey(layer) === sourceKey(source))
    if (!layer) {
      layer = mapLayer({ ...source, map_attached: true, map_visible: source.visible, map_opacity: source.opacity })
      layers.value.push(layer)
      layer = layers.value.at(-1)!
      await controller?.load(layer)
    } else if (layer.status === 'error') await controller?.load(layer)
    if (!alive || current !== version) return
    layer.visible = source.visible; layer.opacity = source.opacity; layer.order = source.order
    layer.static = source.static; layer.unit = source.unit; layer.legend = source.legend; layer.color = source.color
    controller?.appearance(layer)
  }))
  if (alive && current === version) { controller?.syncOrder(layers.value); temporal.paint() }
}
watch(() => JSON.stringify(sources.value.map(layer => [sourceKey(layer), layer.visible, layer.opacity, layer.order, layer.static, layer.unit, layer.legend])), syncLayers)
watch(() => props.recovery, async () => { await syncLayers(); await temporal.refreshAvailability(); await temporal.refresh() })
function ready(value: MapController) {
  controller = value
  controller.initialize(demoRegion, props.camera)
  emit('ready', value)
  void syncLayers()
}
function visibility() { if (document.hidden) temporal.pause() }
onMounted(() => document.addEventListener('visibilitychange', visibility))
watch(() => props.active, async value => { if (value) { await nextTick(); controller?.resume() } else temporal.pause() })
onBeforeUnmount(() => { alive = false; ++version; document.removeEventListener('visibilitychange', visibility); controller = undefined })
</script>

<template>
  <section class="comparison-view" aria-label="右侧对比地图">
    <MapCanvas @ready="ready" @navigation="emit('navigation', $event)" @notice="error = $event" @fatal="error = $event" />
    <TimeAxis class="comparison-time" label="右侧时间轴" :time="time" v-model:resolution="resolution" v-model:rate="rate" :playing="playing"
      :maximum="maximum" :position="position" :times="times" :loading="loading" :metadata-loading="metadataLoading" :counts="counts" :errors="errors" :all-missing="allMissing"
      @select="temporal.setTime" @seek="temporal.seek" @step="temporal.step" @play="temporal.play" @pause="temporal.pause" @refresh="temporal.refreshAvailability(); temporal.refresh()" />
    <div v-if="error || layers.some(layer => layer.status === 'error')" class="comparison-errors panel" role="alert"><p>{{ error }}</p><p v-for="layer in layers.filter(layer => layer.status === 'error')" :key="layer.id">{{ layer.name }}：{{ layer.error }}</p><button class="text-button" @click="syncLayers">刷新对比图层</button></div>
  </section>
</template>

<style scoped>
.comparison-view { position: absolute; top: 0; bottom: 0; left: 50%; right: 0; border-left: 2px solid white; }
.comparison-time { left: 12px; right: 24px; }
.comparison-errors { position: absolute; top: 135px; left: 12px; right: 24px; padding: 12px; font-size: 11px; color: #b94e46; }
.comparison-errors p { margin: 0 0 8px; overflow-wrap: anywhere; }
@media (max-width: 600px) { .comparison-time { right: 12px; padding: 10px; } }
</style>
