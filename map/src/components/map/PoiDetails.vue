<script setup lang="ts">
import { computed } from 'vue'
import type { MapLayer, Selection } from '../../layers/types'
import { poiAddress, poiCategory, propertyText } from '../../map/poi'

const props = defineProps<{ selection: Selection | null; layer?: MapLayer; distance?: number; editPoi?: boolean }>()
const emit = defineEmits<{ close: []; back: []; editPoi: [] }>()
const object = computed(() => props.selection?.object)
const properties = computed(() => object.value?.properties ?? props.selection?.properties ?? {})
const name = computed(() => object.value?.name || propertyText(properties.value, 'name', '名称', '名稱', 'name:zh') || props.selection?.title || '未命名 POI')
const source = computed(() => propertyText(properties.value, 'source', '来源', '数据来源') || props.layer?.source || (object.value?.semantic_source === 'manual' ? '人工维护' : '未提供'))
const phone = computed(() => propertyText(properties.value, 'phone', 'contact:phone', '电话', '電話', 'tel'))
const hours = computed(() => propertyText(properties.value, 'opening_hours', '营业时间', '營業時間'))
const text = (value: unknown) => value == null ? '未提供' : typeof value === 'object' ? JSON.stringify(value) : String(value)
</script>

<template>
  <section v-if="selection" class="poi-details panel" aria-label="POI 详情">
    <header><h2>POI 详情</h2><button aria-label="关闭 POI 详情" @click="emit('close')">×</button></header>
    <button class="back" @click="emit('back')">← 返回查询结果</button>
    <h3>{{ name }}</h3>
    <p class="category">{{ poiCategory(properties) }}<span v-if="distance != null"> · {{ distance < 1000 ? `${Math.round(distance)} m` : `${(distance / 1000).toFixed(2)} km` }}</span></p>
    <p v-if="selection.detailLoading" role="status">正在读取地点详情…</p>
    <p v-if="selection.detailError" role="alert">{{ selection.detailError }}</p>
    <dl>
      <div><dt>地址</dt><dd>{{ poiAddress(properties) || '未提供' }}</dd></div>
      <div v-if="phone"><dt>电话</dt><dd>{{ phone }}</dd></div>
      <div v-if="hours"><dt>营业时间</dt><dd>{{ hours }}</dd></div>
      <div><dt>WGS84 坐标</dt><dd>{{ object?.coordinates?.map(value => value.toFixed(6)).join(', ') || '未提供' }}</dd></div>
      <div><dt>所属图层</dt><dd>{{ layer?.name || selection.layerName }}</dd></div>
      <div><dt>来源</dt><dd>{{ source }}</dd></div>
    </dl>
    <button v-if="editPoi" class="edit" @click="emit('editPoi')">编辑 POI</button>
    <details><summary>原始属性</summary><dl><div v-for="(value, key) in properties" :key="key"><dt>{{ key }}</dt><dd>{{ text(value) }}</dd></div></dl></details>
    <details><summary>资产技术信息</summary><dl>
      <div><dt>对象 ID</dt><dd>{{ object?.object_id || selection.objectId || '未提供' }}</dd></div>
      <div><dt>资产版本</dt><dd>{{ object?.asset ? `${object.asset.asset_id}@${object.asset.version}` : '未提供' }}</dd></div>
      <div><dt>原始要素序号</dt><dd>{{ object?.feature_index ?? '未提供' }}</dd></div>
    </dl></details>
  </section>
</template>

<style scoped>
.poi-details { position: absolute; z-index: 5; top: 134px; right: 78px; width: 360px; max-height: calc(100svh - 200px); overflow-y: auto; padding: 16px; font-size: 12px; }
header { display: flex; align-items: center; justify-content: space-between; }
h2 { font-size: 15px; } h3 { margin: 12px 0 5px; font-size: 20px; overflow-wrap: anywhere; }
button { min-height: 36px; padding: 7px; color: var(--blue); font: inherit; }
header button { font-size: 22px; min-width: 36px; }
.back { padding-left: 0; } .category { color: #687b93; margin-bottom: 14px; }
dl { margin: 10px 0; } dl > div { display: grid; grid-template-columns: 85px minmax(0, 1fr); gap: 10px; padding: 7px 0; }
dt { color: #73859a; } dd { margin: 0; overflow-wrap: anywhere; }
details { border-top: 1px solid var(--line); padding: 12px 0; } summary { cursor: pointer; color: #52647d; }
[role="alert"] { color: #a55145; overflow-wrap: anywhere; }
button:focus-visible, summary:focus-visible { outline: 2px solid var(--blue); outline-offset: 2px; }
@media (max-width: 600px) { .poi-details { left: 12px; right: 64px; width: auto; top: 125px; max-height: calc(100svh - 200px); } }
</style>
