<script setup lang="ts">
import { computed, ref } from 'vue'
import {
  Layers,
  Plus,
  Search,
  X,
  ChevronRight,
  ChevronDown,
  PanelLeftClose,
  PanelLeftOpen,
  RefreshCw,
} from '@lucide/vue'
import LayerItem from './LayerItem.vue'
import type { MapLayer } from '../types'
import { layerGroups, moveTarget } from '../layerTree'
const props = defineProps<{
  layers: MapLayer[]
  open: boolean
  filter: 'all' | 'mine'
  backend: 'loading' | 'online' | 'offline'
  catalogError: string
  ordering: boolean
  orderError: string
}>()
const emit = defineEmits<{
  'update:open': [value: boolean]
  'update:filter': [value: 'all' | 'mine']
  add: []
  refresh: []
  toggle: [layer: MapLayer]
  load: [layer: MapLayer]
  locate: [layer: MapLayer]
  remove: [layer: MapLayer]
  opacity: [layer: MapLayer, value: number]
  move: [layer: MapLayer, direction: number]
}>()
const search = ref('')
const folded = ref(new Set<string>())
const visibleLayers = computed(() =>
  props.layers.filter(
    (layer) =>
      layer.attached &&
      (props.filter !== 'mine' || !layer.builtin) &&
      `${layer.name} ${layer.category}`
        .toLowerCase()
        .includes(search.value.toLowerCase()),
  ),
)
const groups = computed(() => layerGroups(visibleLayers.value))
function toggleGroup(category: string) {
  if (folded.value.has(category)) folded.value.delete(category)
  else folded.value.add(category)
}
</script>

<template>
  <aside v-if="open" class="layer-panel panel">
    <header class="panel-heading">
      <div>
        <Layers :size="18" />
        <h1>地图图层</h1>
        <span class="count">{{ visibleLayers.length }}</span>
      </div>
      <button
        class="icon-button"
        aria-label="收起图层面板"
        @click="emit('update:open', false)"
      >
        <PanelLeftClose :size="18" />
      </button>
    </header>
    <div class="panel-body-top">
      <button class="primary-button add-data" @click="emit('add')">
        <Plus :size="17" />添加图层
      </button>
      <div class="search-field">
        <Search :size="15" /><input
          v-model="search"
          aria-label="搜索图层"
          placeholder="搜索图层名称或分类"
        /><button
          v-if="search"
          class="icon-button"
          aria-label="清空搜索"
          @click="search = ''"
        >
          <X :size="14" />
        </button>
      </div>
    </div>
    <div class="layer-tabs">
      <button
        :class="{ active: filter === 'all' }"
        @click="emit('update:filter', 'all')"
      >
        全部</button
      ><button
        :class="{ active: filter === 'mine' }"
        @click="emit('update:filter', 'mine')"
      >
        自定义
      </button>
    </div>
    <div class="layer-scroll">
      <div v-if="!visibleLayers.length" class="empty-state">
        <Layers :size="28" /><strong>{{
          search ? '没有匹配的图层' : '当前没有地图图层'
        }}</strong
        ><span>{{
          search ? '尝试其他名称或分类' : '点击添加图层，从示例或已有登记中选择'
        }}</span>
      </div>
      <section
        v-for="group in groups"
        :key="group.category"
        class="layer-group"
      >
        <button
          class="group-title"
          :aria-expanded="!folded.has(group.category)"
          @click="toggleGroup(group.category)"
        >
          <ChevronRight
            v-if="folded.has(group.category)"
            :size="14"
          /><ChevronDown v-else :size="14" /><span>{{ group.category }}</span
          ><span>{{ group.layers.length }}</span>
        </button>
        <div v-if="!folded.has(group.category)">
          <p v-if="!group.layers.length" class="group-empty">{{ search ? '没有匹配图层' : '暂无已加入图层' }}</p>
          <LayerItem
            v-for="layer in group.layers"
            :key="layer.id"
            :layer="layer"
            :can-move-up="moveTarget(layers, layer, -1) !== null"
            :can-move-down="moveTarget(layers, layer, 1) !== null"
            :ordering="ordering"
            @toggle="emit('toggle', layer)"
            @load="emit('load', layer)"
            @locate="emit('locate', layer)"
            @remove="emit('remove', layer)"
            @opacity="emit('opacity', layer, $event)"
            @move="emit('move', layer, $event)"
          />
        </div>
      </section>
    </div>
    <footer class="panel-footer">
      <p v-if="orderError" class="order-error" role="alert">{{ orderError }}</p>
      <div>
        <i :class="backend"></i
        ><span>{{
          backend === 'online'
            ? '图层服务已连接'
            : backend === 'loading'
              ? '正在连接图层服务'
              : '图层服务未连接'
        }}</span>
      </div>
      <button
        class="icon-button"
        aria-label="刷新后端图层"
        :disabled="backend === 'loading'"
        @click="emit('refresh')"
      >
        <RefreshCw :size="14" :class="{ spin: backend === 'loading' }" />
      </button>
      <p v-if="backend === 'offline'">
        {{ catalogError }}。可继续浏览内置小样。
      </p>
    </footer>
  </aside>
  <button
    v-else
    class="panel-reopen panel icon-button"
    aria-label="展开图层面板"
    @click="emit('update:open', true)"
  >
    <PanelLeftOpen :size="20" />
  </button>
</template>

<style scoped>
.group-empty { margin: 8px 16px 12px; font-size: 10px; color: #8795a7; }
.order-error { color: #a55145; }
.layer-panel {
  position: absolute;
  z-index: 3;
  left: 20px;
  top: 84px;
  width: 308px;
  max-height: calc(100svh - 128px);
  display: flex;
  flex-direction: column;
  overflow: hidden;
  animation: panel-in 0.25s ease-out;
}
.panel-heading {
  height: 59px;
  flex-shrink: 0;
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 16px;
  border-bottom: 1px solid var(--line);
}
.panel-heading > div {
  display: flex;
  align-items: center;
  gap: 9px;
}
.panel-heading > div > svg {
  color: #5a6e8b;
}
.panel-heading h1 {
  font-size: 14px;
  font-weight: 600;
}
.count {
  font-size: 10px;
  color: #8a95a5;
  background: #f1f4f8;
  min-width: 20px;
  text-align: center;
  padding: 2px 5px;
  border-radius: 4px;
}
.panel-body-top {
  padding: 16px 16px 0;
}
.add-data {
  width: 100%;
  height: 36px;
}
.search-field {
  display: flex;
  align-items: center;
  background: #f6f8fb;
  color: #96a1b0;
  border: 1px solid #edf0f4;
  border-radius: 5px;
  gap: 7px;
  padding: 0 10px;
  height: 34px;
  margin-top: 12px;
}
.search-field input {
  background: transparent;
  border: 0;
  outline: 0;
  min-width: 0;
  width: 100%;
  color: #34455b;
  font-size: 11px;
}
.search-field input::placeholder {
  color: #9ba5b3;
}
.search-field:focus-within {
  border-color: #b9d0fa;
}
.search-field .icon-button {
  width: 18px;
  height: 18px;
}
.layer-tabs {
  display: flex;
  border-bottom: 1px solid var(--line);
  margin-top: 8px;
  padding: 0 16px;
  gap: 22px;
  flex-shrink: 0;
}
.layer-tabs button {
  position: relative;
  height: 42px;
  font-size: 11px;
  color: #8a95a5;
  padding: 0 2px;
}
.layer-tabs button.active {
  color: var(--blue);
  font-weight: 550;
}
.layer-tabs button.active:after {
  content: '';
  position: absolute;
  bottom: 0;
  height: 2px;
  background: var(--blue);
  inset-inline: 0;
}
.layer-scroll {
  overflow-y: auto;
  min-height: 0;
  scrollbar-width: thin;
  scrollbar-color: #dbe2ec transparent;
  padding: 7px 0 14px;
}
.group-title {
  height: 37px;
  display: flex;
  width: 100%;
  padding: 0 17px;
  gap: 7px;
  color: #748296;
  font-size: 10px;
  text-align: left;
}
.group-title span:last-child {
  margin-left: auto;
  font-size: 10px;
  color: #a7b0bd;
}
.panel-footer {
  padding: 9px 14px 9px 18px;
  border-top: 1px solid var(--line);
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  background: #fafbfd;
  font-size: 10px;
  color: #95a0af;
  flex-shrink: 0;
}
.panel-footer > div {
  display: flex;
  align-items: center;
  gap: 6px;
}
.panel-footer > div > i {
  width: 5px;
  height: 5px;
  border-radius: 50%;
  background: #c3ccd8;
}
.panel-footer > div > i.online {
  background: #68a494;
}
.panel-footer > div > i.offline {
  background: #d79a5b;
}
.panel-footer > .icon-button {
  margin-left: auto;
  width: 25px;
  height: 25px;
}
.panel-footer p {
  font-size: 9px;
  width: 100%;
  line-height: 1.6;
  color: #ad865e;
  margin-top: 3px;
  overflow-wrap: anywhere;
}
.empty-state {
  padding: 40px 16px;
  color: #a0aaba;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 12px;
  font-size: 10px;
}
.empty-state strong {
  font-size: 12px;
  font-weight: 500;
  color: #718097;
}
.panel-reopen {
  position: absolute;
  left: 20px;
  top: 84px;
  width: 42px;
  height: 42px;
  z-index: 3;
}
@media (min-width: 1500px) {
  .layer-panel {
    width: 322px;
  }
}
@media (max-width: 900px) {
  .layer-panel {
    width: 280px;
    left: 12px;
    top: 76px;
  }
  .panel-reopen {
    left: 12px;
    top: 76px;
  }
}
@media (max-width: 600px) {
  .layer-panel {
    width: min(280px, calc(100% - 72px));
    max-height: calc(100svh - 155px);
  }
}
</style>
