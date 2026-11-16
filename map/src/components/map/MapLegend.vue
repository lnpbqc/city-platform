<script setup lang="ts">
import { computed, ref, useId } from 'vue'
import { ChevronDown } from '@lucide/vue'
import type { MapLayer } from '../../layers/types'
const props = defineProps<{ layers: MapLayer[] }>()
const showLegend = ref(true)
const entriesId = useId()
const legend = computed(() => props.layers.flatMap(layer => {
  if (layer.id === 'basemap' || layer.type !== 'geojson' || !layer.attached || !layer.visible || layer.status !== 'ready') return []
  const bins = layer.legend?.filter(item => item.label !== '缺测') ?? []
  if (new Set(bins.map(item => item.color)).size < 2) return []
  const unit = layer.unit && !bins.every(item => item.label.endsWith(` ${layer.unit}`)) ? layer.unit : ''
  return [{ id: layer.id, name: layer.name, unit, bins, missing: layer.legend?.some(item => item.label === '缺测') }]
}))
</script>

<template>
  <aside v-if="legend.length" class="legend panel" aria-label="专题图例">
    <button
      class="legend-heading"
      :aria-expanded="showLegend"
      :aria-controls="entriesId"
      @click="showLegend = !showLegend"
    >
      <span>图例</span
      ><ChevronDown :size="14" :class="{ flipped: !showLegend }" />
    </button>
    <div v-show="showLegend" :id="entriesId" class="legend-entries map-panel-scroll" tabindex="0" aria-label="专题颜色分档">
      <div v-for="layer in legend" :key="layer.id" class="legend-layer">
        <strong>{{ layer.name }} <small v-if="layer.unit">{{ layer.unit }}</small></strong>
        <span v-for="(item, index) in layer.bins" :key="index"><i :style="{ background: item.color }" aria-hidden="true"></i>{{ item.label }}</span>
        <small v-if="layer.missing" class="legend-missing">缺测不绘制</small>
      </div>
    </div>
  </aside>
</template>

<style scoped>
.legend {
  position: absolute;
  right: 20px;
  bottom: 60px;
  min-width: 158px;
  max-width: min(240px, calc(100vw - 24px));
  z-index: 2;
  padding: 0 14px;
  overflow: hidden;
}
.legend-heading {
  display: flex;
  justify-content: space-between;
  width: 100%;
  font-size: 11px;
  font-weight: 550;
  height: 38px;
  gap: 30px;
}
.legend-heading svg {
  color: #99a4b3;
  transition: transform 0.2s;
}
.flipped {
  transform: rotate(180deg);
}
.legend-entries {
  max-height: min(260px, 36svh);
  display: flex;
  flex-direction: column;
  gap: 11px;
  padding: 3px 6px 12px 0;
  font-size: 11px;
  color: #52657d;
  overflow-wrap: anywhere;
}
.legend-entries:focus-visible { outline: 2px solid var(--blue); outline-offset: -2px; }
.legend-layer { display: grid; gap: 6px; }
.legend-layer strong { font-weight: 500; }
.legend-layer small { color: #63758b; }
.legend-layer strong small { margin-left: 4px; }
.legend-missing { font-size: 11px; }
.legend-layer > span {
  display: flex;
  align-items: center;
  gap: 9px;
}
.legend-entries i {
  height: 7px;
  width: 7px;
  flex-shrink: 0;
  border-radius: 2px;
}
@media (max-width: 900px) {
  .legend {
    right: 12px;
  }
}
@media (max-width: 600px) {
  .legend {
    bottom: 56px;
    min-width: 120px;
    max-width: 180px;
  }
  .legend-entries {
    gap: 8px;
  }
}
</style>
