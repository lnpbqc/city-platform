<script setup lang="ts">
import { computed } from 'vue'
import { X, Info } from '@lucide/vue'
import type { Selection } from '../types'
import { timeLabel } from '../temporal'
const props = defineProps<{ selection: Selection | null; embedded?: boolean }>()
const emit = defineEmits<{ close: [] }>()
const object = computed(() => props.selection?.object)
const sourceLabels: Record<string, string> = { geometry_model: '几何模型', OSM: 'OpenStreetMap', manual: '人工', synthetic: '合成演示', dataset: '数据集' }
const properties = computed(() => object.value?.properties && Object.keys(object.value.properties).length ? object.value.properties : props.selection?.properties ?? {})
function valueText(value: unknown) {
  return value === null
    ? '未提供'
    : typeof value === 'object'
      ? JSON.stringify(value)
      : String(value)
}
</script>

<template>
  <aside v-if="selection" class="inspector panel" :class="{ embedded }" aria-label="对象详情">
    <header>
      <span class="eyebrow">FEATURE INSPECTOR</span
      ><button
        class="icon-button"
        aria-label="关闭属性面板"
        @click="emit('close')"
      >
        <X :size="17" />
      </button>
    </header>
    <span class="inspector-type">对象属性</span>
    <h2>{{ object?.name ?? selection.title }}</h2>
    <p class="inspector-source">{{ selection.layerName }}</p>
    <p v-if="selection.detailLoading" role="status">正在读取原始对象详情…</p>
    <p v-if="selection.detailError" class="detail-error" role="alert">{{ selection.detailError }}</p>
    <section v-if="object?.temporal" class="temporal-value" aria-label="当前时次属性">
      <span>{{ timeLabel(object.temporal.time, object.temporal.resolution) }} · {{ object.temporal.resolution === 'day' ? '日均' : '小时' }} · 北京时间</span>
      <strong>{{ object.temporal.missing ? '该时次缺测 / 未覆盖' : `${object.temporal.value?.toLocaleString('zh-CN', { maximumFractionDigits: 2 })} ${object.temporal.unit}` }}</strong>
    </section>
    <dl v-if="object" class="object-fields">
      <div><dt>object_id</dt><dd>{{ object.object_id }}</dd></div>
      <div><dt>类型</dt><dd>{{ object.type }}</dd></div>
      <div><dt>名称</dt><dd>{{ object.name ?? '未提供' }}</dd></div>
      <div><dt>高度</dt><dd>{{ object.height_m == null ? '未提供' : `${object.height_m} m` }}</dd></div>
      <div><dt>等级</dt><dd>{{ object.level ?? '未提供' }}</dd></div>
      <div><dt>来源</dt><dd>{{ sourceLabels[object.semantic_source] ?? object.semantic_source }}</dd></div>
      <div><dt>置信度</dt><dd>{{ object.confidence == null ? '未提供' : `${object.confidence * 100}%` }}</dd></div>
      <div><dt>WGS84坐标</dt><dd>{{ object.coordinates?.map(value => value.toFixed(6)).join(', ') ?? '未提供' }}</dd></div>
      <div><dt>资产版本</dt><dd>{{ object.asset.asset_id }}@{{ object.asset.version }}</dd></div>
      <div><dt>原始几何</dt><dd>{{ object.geometry?.type ?? '未提供' }}</dd></div>
    </dl>
    <p v-if="(object?.type === 'model' || selection.resourceType === '3dtiles') && !Object.keys(properties).length" class="no-properties">该瓦片未携带语义属性，来源：几何模型</p>
    <p v-else-if="!Object.keys(properties).length && !selection.detailLoading" class="no-properties">该对象未提供语义属性。</p>
    <p v-if="!selection.objectId && !selection.detailLoading" class="no-properties">该资源尚无本地对象索引，以下为原始可读属性。</p>
    <dl v-if="Object.keys(properties).length">
      <div v-for="(value, key) in properties" :key="key">
        <dt>{{ key }}</dt>
        <dd>{{ valueText(value) }}</dd>
      </div>
    </dl>
    <footer><Info :size="13" />属性来自图层原始数据</footer>
  </aside>
</template>

<style scoped>
.inspector.embedded { position: static; width: auto; padding: 12px 0 0; box-shadow: none; background: transparent; animation: none; }
.embedded dl { max-height: none; }
.detail-error { color: #a55145; font-size: 11px; line-height: 1.7; overflow-wrap: anywhere; }
.temporal-value { display: grid; gap: 8px; padding: 12px; margin-top: 14px; background: #f2f7ff; border-radius: 5px; }
.temporal-value span { font-size: 9px; color: #73859a; }
.temporal-value strong { color: var(--blue); font-size: 13px; font-weight: 550; }
.inspector {
  position: absolute;
  top: 134px;
  right: 78px;
  width: 286px;
  z-index: 3;
  padding: 16px 20px;
  animation: panel-in 0.2s ease-out;
}
.inspector header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin: -5px -5px 14px 0;
}
.inspector-type {
  font-size: 10px;
  color: var(--blue);
  display: block;
  margin-bottom: 7px;
}
.inspector h2 {
  font-size: 18px;
  font-weight: 550;
  line-height: 1.6;
}
.inspector-source {
  font-size: 10px;
  color: #94a0b0;
  margin-top: 5px;
}
.inspector dl {
  margin: 20px 0 15px;
  max-height: calc(100svh - 410px);
  overflow: auto;
  scrollbar-width: thin;
}
.inspector dl > div {
  display: flex;
  justify-content: space-between;
  align-items: baseline;
  gap: 15px;
  padding: 11px 0;
  border-top: 1px solid var(--line);
  font-size: 11px;
}
.inspector dt {
  color: #8e9aac;
  flex-shrink: 0;
  max-width: 45%;
  overflow-wrap: anywhere;
}
.inspector dd {
  margin: 0;
  text-align: right;
  overflow-wrap: anywhere;
  min-width: 0;
  line-height: 1.5;
}
.inspector footer {
  display: flex;
  gap: 6px;
  align-items: center;
  color: #a5aebb;
  font-size: 9px;
  margin-top: 20px;
}
.no-properties {
  font-size: 11px;
  line-height: 1.8;
  color: #8e9aac;
  margin-top: 20px;
}
@media (max-width: 900px) {
  .inspector {
    right: 64px;
    top: 125px;
    width: 250px;
  }
}
@media (max-width: 600px) {
  .inspector {
    right: 64px;
    left: 12px;
    top: auto;
    bottom: 80px;
    width: auto;
    z-index: 5;
  }
  .inspector dl {
    max-height: 180px;
  }
  .inspector header {
    margin-bottom: 4px;
  }
  .inspector h2 {
    font-size: 16px;
  }
}
</style>
