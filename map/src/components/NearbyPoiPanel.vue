<script setup lang="ts">
import type { MapLayer, NearbyPoi } from '../types'
import { poiCategory, propertyText } from '../poi'
defineProps<{ items: NearbyPoi[]; layers: MapLayer[]; loading: boolean; error: string; unavailable: string[] }>()
const emit = defineEmits<{ select: [item: NearbyPoi]; close: []; retry: [] }>()
</script>

<template>
  <section class="nearby panel" aria-label="附近 POI">
    <header><h2>附近 POI</h2><button aria-label="关闭附近 POI" @click="emit('close')">×</button></header>
    <p class="hint">距点击位置 1 公里内，按距离排序，最多 20 个。</p>
    <p v-if="loading" role="status">正在查询附近 POI…</p>
    <p v-else-if="error" role="alert">{{ error }} <button @click="emit('retry')">重试</button></p>
    <template v-else>
      <p v-if="!items.length" role="status">1 公里内暂无 POI。</p>
      <ol v-else>
        <li v-for="item in items" :key="`${item.layer_id}:${item.object_id}`"><button @click="emit('select', item)">
          <strong>{{ item.name || propertyText(item.properties, 'name', '名称', 'name:zh') || '未命名 POI' }}</strong>
          <span>{{ poiCategory(item.properties) }} · {{ item.distance_m < 1000 ? `${Math.round(item.distance_m)} m` : `${(item.distance_m / 1000).toFixed(2)} km` }}</span>
          <small>{{ layers.find(layer => layer.id === item.layer_id)?.name || item.layer_id }}</small>
        </button></li>
      </ol>
    </template>
    <p v-for="id in unavailable" :key="id" class="hint">{{ layers.find(layer => layer.id === id)?.name || id }}：暂无可用本地索引，未参与查询。</p>
  </section>
</template>

<style scoped>
.nearby { position: absolute; z-index: 4; top: 134px; right: 78px; width: 360px; max-height: calc(100svh - 200px); overflow-y: auto; padding: 16px; font-size: 12px; }
header { display: flex; align-items: center; justify-content: space-between; } h2 { font-size: 15px; }
header button { font-size: 22px; min-width: 36px; min-height: 36px; }
button { color: var(--blue); font: inherit; } p { margin: 12px 0; line-height: 1.6; }
.hint, small { color: #73859a; } ol { list-style: none; padding: 0; margin: 0; }
li button { display: grid; gap: 6px; width: 100%; text-align: left; padding: 12px 0; border-bottom: 1px solid var(--line); }
strong { color: #3f526b; font-weight: 550; } span { color: #52647d; }
[role="alert"] { color: #a55145; overflow-wrap: anywhere; }
button:focus-visible { outline: 2px solid var(--blue); outline-offset: 2px; }
@media (max-width: 600px) { .nearby { left: 12px; right: 64px; width: auto; top: 125px; max-height: calc(100svh - 200px); } }
</style>
