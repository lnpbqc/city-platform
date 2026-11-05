<script setup lang="ts">
import { ref, shallowRef } from 'vue'
import { ApiError, savePoiData, uploadLayer } from '../api'
import { fetchMapGeoJSON } from '../mapResource'
import { poiAddress, poiCategory, poiFile, propertyText, type PoiData, type PoiFeature } from '../poi'
import type { LayerRecord, MapLayer, ObjectRecord } from '../types'

const props = defineProps<{
  layers: MapLayer[]
  layer?: MapLayer
  object?: ObjectRecord
  coordinates?: number[]
}>()
const emit = defineEmits<{ pick: []; cancel: []; saved: [record: LayerRecord]; refresh: [] }>()
const properties = props.object?.properties ?? {}
const name = ref(props.object?.name || propertyText(properties, 'name', '名称', '名稱', 'name:zh'))
const category = ref(props.object ? poiCategory(properties) : '')
const address = ref(poiAddress(properties))
const layerName = ref('我的 POI')
const target = shallowRef<LayerRecord | null>(null)
const busy = ref(false)
const error = ref('')
const conflict = ref(false)
const confirmingDelete = ref(false)
defineExpose({ busy })

function setTarget(id: string) {
  const layer = props.layers.find(item => item.id === id)
  target.value = layer ? { ...layer } : null
}
if (props.layer) target.value = { ...props.layer }
else setTarget((props.layers.find(layer => layer.attached) ?? props.layers[0])?.id ?? '')

async function save(remove = false) {
  if (busy.value || conflict.value) return
  error.value = ''
  const coordinates = props.coordinates ?? props.object?.coordinates
  if (!remove && (!name.value.trim() || !category.value.trim() || !coordinates)) {
    error.value = '请填写名称和类别，并在地图上选择位置。'
    return
  }
  busy.value = true
  try {
    const layer = target.value
    const data: PoiData = layer
      ? await fetchMapGeoJSON(layer.url, new AbortController().signal)
      : { type: 'FeatureCollection', features: [] }
    if (data.type !== 'FeatureCollection' || !Array.isArray(data.features) ||
        data.features.some(feature => feature.geometry?.type !== 'Point')) throw new Error('POI 图层需要有效的 GeoJSON 点位文件。')
    const index = props.object?.feature_index
    if (props.object && (index == null || !data.features[index])) throw new Error('原点位已不可用，请重新选择。')
    if (remove) data.features.splice(index!, 1)
    else {
      const original = index == null ? undefined : data.features[index]
      const feature: PoiFeature = {
        ...original,
        type: 'Feature',
        geometry: { ...original?.geometry, type: 'Point', coordinates: props.coordinates ?? original?.geometry.coordinates ?? coordinates },
        properties: { ...(original?.properties ?? { semantic_source: 'manual' }),
          name: name.value.trim(), category: category.value.trim(), address: address.value.trim() },
      }
      if (index == null) data.features.push(feature)
      else data.features[index] = feature
    }
    const file = poiFile(data)
    if (layer) emit('saved', await savePoiData(layer.id, layer.asset_id!, layer.asset_version!, file))
    else {
      const body = new FormData()
      body.set('file', file)
      body.set('type', 'geojson')
      body.set('category', 'POI')
      body.set('name', layerName.value.trim())
      body.set('source', '人工维护')
      emit('saved', await uploadLayer(body))
    }
  } catch (cause) {
    conflict.value = cause instanceof ApiError && cause.code === 'POI_SNAPSHOT_CONFLICT'
    error.value = cause instanceof Error ? cause.message : '保存 POI 失败'
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <form class="poi-editor panel" aria-label="POI 编辑" @submit.prevent="save()">
    <h2>{{ object ? '编辑 POI' : '添加 POI' }}</h2>
    <fieldset :disabled="busy || conflict">
      <label v-if="!object">保存到
        <select :value="target?.id ?? ''" @change="setTarget(($event.target as HTMLSelectElement).value)">
          <option v-for="item in layers" :key="item.id" :value="item.id">{{ item.name }}</option>
          <option value="">新建 POI 图层</option>
        </select>
      </label>
      <label v-if="!target">图层名称<input v-model="layerName" required maxlength="120" /></label>
      <label>名称<input v-model="name" required maxlength="120" /></label>
      <label>类别<input v-model="category" list="poi-categories" required maxlength="80" />
        <datalist id="poi-categories"><option v-for="item in ['餐饮','交通','购物','医疗','景点','其他']" :key="item" :value="item" /></datalist>
      </label>
      <label>地址（可选）<input v-model="address" maxlength="500" /></label>
      <div class="coordinates">
        <span>{{ (coordinates ?? object?.coordinates)?.map(value => value.toFixed(6)).join(', ') }}</span>
        <button type="button" @click="emit('pick')">重新选点</button>
      </div>
    </fieldset>
    <p v-if="error" role="alert">{{ error }}</p>
    <p v-if="confirmingDelete" role="status">删除此点位？</p>
    <footer>
      <button type="button" :disabled="busy" @click="emit('cancel')">取消</button>
      <button v-if="conflict" type="button" @click="emit('refresh')">重新加载</button>
      <template v-else>
        <button v-if="object" type="button" :disabled="busy" @click="confirmingDelete ? save(true) : confirmingDelete = true">
          {{ confirmingDelete ? '确认删除' : '删除' }}
        </button>
        <button type="submit" :disabled="busy">{{ busy ? '正在保存…' : '保存' }}</button>
      </template>
    </footer>
  </form>
</template>

<style scoped>
.poi-editor { position: absolute; z-index: 6; left: 50%; bottom: 60px; transform: translateX(-50%); width: min(320px, calc(100% - 32px)); padding: 16px; font-size: 12px; }
h2 { margin: 0 0 10px; font-size: 15px; }
fieldset, label { display: grid; gap: 5px; }
fieldset { border: 0; padding: 0; gap: 8px; }
input, select { padding: 6px; border: 1px solid var(--line); border-radius: 4px; font: inherit; }
.coordinates, footer { display: flex; align-items: center; justify-content: space-between; gap: 8px; }
footer { justify-content: flex-end; margin-top: 12px; }
button { padding: 5px 8px; border: 1px solid var(--line); border-radius: 4px; color: var(--blue); }
[role="alert"] { color: #a55145; overflow-wrap: anywhere; }
</style>
