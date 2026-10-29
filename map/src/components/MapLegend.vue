<script setup lang="ts">
import { computed, ref } from 'vue'
import { ChevronDown } from '@lucide/vue'
import type { MapLayer } from '../types'
const props = defineProps<{ layers: MapLayer[] }>()
const showLegend = ref(true)
const legend = computed(() =>
  props.layers.filter(
    (layer) => layer.id !== 'basemap' && layer.attached && layer.visible && layer.status === 'ready',
  ),
)
</script>

<template>
  <aside class="legend panel">
    <button
      class="legend-heading"
      :aria-expanded="showLegend"
      @click="showLegend = !showLegend"
    >
      <span>图例</span
      ><ChevronDown :size="14" :class="{ flipped: !showLegend }" />
    </button>
    <div v-if="showLegend" class="legend-entries">
      <div v-for="layer in legend" :key="layer.id" class="legend-layer">
        <strong>{{ layer.name }} <small>{{ layer.unit || '单位未提供' }}</small></strong>
        <span v-for="(item, index) in layer.legend || []" :key="index"><i :style="{ background: item.color }"></i>{{ item.label }}{{ item.value == null ? '' : ` · ${item.value}` }}</span>
        <span v-if="!layer.legend?.length" class="muted">未提供图例</span>
      </div>
      <span v-if="!legend.length" class="muted">暂无可见图层</span>
    </div>
  </aside>
</template>

<style scoped>
.legend {
  position: absolute;
  right: 20px;
  bottom: 60px;
  min-width: 158px;
  max-width: 240px;
  z-index: 2;
  padding: 0 14px;
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
  max-height: 260px;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: 11px;
  padding: 0 0 14px;
  font-size: 10px;
  color: #7a879a;
}
.legend-layer { display: grid; gap: 6px; }
.legend-layer strong { font-weight: 500; }
.legend-layer small { margin-left: 6px; color: #8d9baa; }
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
    font-size: 9px;
    gap: 8px;
  }
}
</style>
