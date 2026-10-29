<script setup lang="ts">
import { nextTick, ref, watch } from 'vue'
import { X, Scan, Pentagon, Search } from '@lucide/vue'
import FeatureInspector from './FeatureInspector.vue'
import type { MapLayer, ObjectRecord, Selection } from '../types'

const props = defineProps<{
  layers: MapLayer[]; layerId: string; items: ObjectRecord[]; total: number; page: number; pageSize: number
  loading: boolean; error: string; q: string; type: string; selectedId: string; selection: Selection | null
  area: boolean; drawing: 'box' | 'polygon' | null; progress: { loaded: number; total: number } | null
}>()
const emit = defineEmits<{
  close: []; layer: [id: string]; page: [page: number]; select: [item: ObjectRecord]; apply: []
  'update:q': [value: string]; 'update:type': [value: string]
  draw: [mode: 'box' | 'polygon']; finish: []; cancel: []; clearArea: []; clearSelection: []; retry: []
}>()
const list = ref<HTMLElement>()
watch(() => [props.selectedId, props.items], async () => {
  await nextTick()
  list.value?.querySelector<HTMLElement>('[aria-selected="true"]')?.scrollIntoView({ block: 'nearest' })
})
</script>

<template>
  <section class="objects panel" aria-label="对象查询面板">
    <header><h2>对象查询</h2><button class="icon-button" aria-label="关闭对象查询" @click="emit('close')"><X :size="17" /></button></header>
    <label class="object-layer">查询图层<select :value="layerId" aria-label="对象查询图层" @change="emit('layer', ($event.target as HTMLSelectElement).value)">
      <option v-if="!layers.length" value="">暂无已加入图层</option>
      <option v-for="layer in layers" :key="layer.id" :value="layer.id">{{ layer.name }}</option>
    </select></label>
    <form class="object-filters" @submit.prevent="emit('apply')">
      <input :value="q" aria-label="对象关键词" placeholder="名称、ID或属性" @input="emit('update:q', ($event.target as HTMLInputElement).value)" />
      <input :value="type" aria-label="对象类型筛选" placeholder="类型，例如 building" @input="emit('update:type', ($event.target as HTMLInputElement).value)" />
      <button type="submit" :disabled="!layerId || loading"><Search :size="13" />查询</button>
    </form>
    <div class="selection-tools">
      <button :disabled="!layerId || loading" :aria-pressed="drawing === 'box'" @click="emit('draw', 'box')"><Scan :size="13" />框选</button>
      <button :disabled="!layerId || loading" :aria-pressed="drawing === 'polygon'" @click="emit('draw', 'polygon')"><Pentagon :size="13" />多边形</button>
      <button v-if="drawing === 'polygon'" @click="emit('finish')">完成</button>
      <button v-if="drawing" @click="emit('cancel')">取消绘制</button>
      <button v-if="area" @click="emit('clearArea')">清除范围</button>
    </div>
    <p v-if="drawing" class="object-hint" role="status">{{ drawing === 'box' ? '按住鼠标左键拖出地面范围' : '依次点击地面添加顶点，至少三个点后点击完成' }}；Esc取消。</p>
    <p v-if="loading" class="object-hint" role="status">{{ progress ? `正在读取选择集 ${progress.loaded}/${progress.total || '…'}` : '正在读取对象…' }}</p>
    <p v-else-if="error" class="object-error" role="alert"><strong>{{ error.startsWith('无权限：') ? '无权限读取对象' : '对象加载失败' }}</strong> · {{ error }} <button @click="emit('retry')">重试查询</button></p>
    <p v-else class="object-count" role="status">{{ area ? '范围内' : '当前筛选' }}共 {{ total }} 个对象</p>
    <div ref="list" class="object-list" role="listbox" aria-label="对象列表">
      <button v-for="item in items" :key="item.object_id" role="option" :aria-selected="selectedId === item.object_id" @click="emit('select', item)">
        <strong>{{ item.name ?? '名称未提供' }}</strong><span>{{ item.type }} · {{ item.object_id }}</span>
        <small v-if="item.temporal">{{ item.temporal.missing ? '该时次缺测 / 未覆盖' : `${item.temporal.value?.toLocaleString('zh-CN', { maximumFractionDigits: 2 })} ${item.temporal.unit}` }}{{ item.temporal.resolution === 'day' ? ' · 日均' : '' }}</small>
      </button>
      <p v-if="!loading && !error && !items.length" class="object-hint">当前图层或范围内无匹配对象。</p>
    </div>
    <nav class="object-pages" aria-label="对象分页">
      <button :disabled="loading || page <= 1" @click="emit('page', page - 1)">上一页</button>
      <span>{{ page }} / {{ Math.max(1, Math.ceil(total / pageSize)) }}</span>
      <button :disabled="loading || page * pageSize >= total" @click="emit('page', page + 1)">下一页</button>
    </nav>
    <FeatureInspector :selection="selection" embedded @close="emit('clearSelection')" />
  </section>
</template>

<style scoped>
.objects { position: absolute; z-index: 4; top: 134px; right: 78px; width: 360px; max-height: calc(100svh - 200px); overflow: auto; padding: 14px 16px; scrollbar-width: thin; }
header { display: flex; align-items: center; justify-content: space-between; margin-bottom: 12px; }
h2 { font-size: 15px; font-weight: 550; }
.object-layer { display: grid; gap: 6px; font-size: 10px; color: #7a879a; }
select, input { width: 100%; min-width: 0; border: 1px solid var(--line); border-radius: 5px; padding: 7px; background: white; color: #52647d; font: inherit; }
.object-filters { display: grid; grid-template-columns: 1fr 1fr auto; gap: 6px; margin: 9px 0; font-size: 10px; }
button { font-size: 10px; }
.object-filters button, .selection-tools button { display: inline-flex; align-items: center; gap: 4px; padding: 5px 7px; border: 1px solid var(--line); border-radius: 4px; color: var(--blue); }
.selection-tools { display: flex; gap: 5px; flex-wrap: wrap; }
.selection-tools [aria-pressed="true"] { background: #edf4ff; border-color: #a7c4fb; }
.object-hint, .object-count, .object-error { margin: 10px 0; font-size: 10px; line-height: 1.7; color: #7a879a; overflow-wrap: anywhere; }
.object-error { color: #a55145; }
.object-error button { color: var(--blue); }
.object-list { max-height: 190px; overflow: auto; scrollbar-width: thin; }
.object-list > button { display: grid; gap: 4px; padding: 9px; width: 100%; text-align: left; border-bottom: 1px solid var(--line); }
.object-list strong { font-size: 11px; font-weight: 500; color: #52647d; }
.object-list span { font-size: 9px; color: #8d9baa; overflow-wrap: anywhere; }
.object-list small { font-size: 10px; color: #52647d; }
.object-list [aria-selected="true"] { background: #fff6e7; box-shadow: inset 3px 0 #f59e0b; }
.object-pages { display: flex; align-items: center; justify-content: space-between; margin: 8px 0 0; font-size: 10px; color: #7a879a; }
.object-pages button { color: var(--blue); }
@media (max-width: 600px) { .objects { left: 12px; right: 64px; width: auto; top: 125px; max-height: calc(100svh - 200px); } }
</style>
