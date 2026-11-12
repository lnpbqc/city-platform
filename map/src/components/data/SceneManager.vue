<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { Layers, LoaderCircle, RefreshCw, Search } from '@lucide/vue'
import { deleteScene, getScenes } from '../../api/api'
import type { SceneRecord } from '../../simulation/simulationTypes'
import ConfirmDialog from '../common/ConfirmDialog.vue'

const props = defineProps<{ initialQuery: string; active: boolean; revision: number }>()
const emit = defineEmits<{ open: [scene: SceneRecord]; removed: [] }>()
const input = ref(props.initialQuery)
const query = ref(props.initialQuery)
const page = ref(1)
const pageSize = 20
const total = ref(0)
const pages = computed(() => Math.max(1, Math.ceil(total.value / pageSize)))
const scenes = ref<SceneRecord[]>([])
const loading = ref(false)
const error = ref('')
const pending = ref<SceneRecord | null>(null)
const deleting = ref(false)
const deleteError = ref('')
let request: AbortController | undefined
let alive = true

async function load() {
  request?.abort()
  const controller = new AbortController()
  request = controller
  error.value = ''
  loading.value = true
  try {
    const result = await getScenes({ page: page.value, page_size: pageSize, q: query.value }, controller.signal)
    if (controller.signal.aborted) return
    total.value = result.total
    if (page.value > pages.value) { page.value = pages.value; return }
    scenes.value = result.items
  } catch (cause) {
    if (!controller.signal.aborted) error.value = cause instanceof Error ? cause.message : '无法读取场景'
  } finally {
    if (!controller.signal.aborted) loading.value = false
  }
}
function search() {
  if (page.value === 1 && query.value === input.value.trim()) { void load(); return }
  query.value = input.value.trim()
  page.value = 1
}
function ask(scene: SceneRecord) {
  pending.value = scene
  deleteError.value = ''
}
async function remove() {
  const scene = pending.value
  if (!scene || deleting.value) return
  deleting.value = true
  deleteError.value = ''
  try {
    await deleteScene(scene.id, scene.version)
    if (!alive) return
    pending.value = null
    emit('removed')
    await load()
  } catch (cause) {
    if (alive) deleteError.value = cause instanceof Error ? cause.message : '删除场景失败'
  } finally { deleting.value = false }
}
function assetVersions(scene: SceneRecord) {
  const refs = scene.layers.flatMap(layer => layer.asset ? [`${layer.asset.asset_id}@${layer.asset.version}`] : [])
  if (scene.network) refs.push(`${scene.network.asset_id}@${scene.network.version}`)
  return [...new Set(refs)]
}
const dateFormat = new Intl.DateTimeFormat('zh-CN', { dateStyle: 'short', timeStyle: 'short', timeZone: 'Asia/Shanghai' })
watch([query, page, () => props.active, () => props.revision], () => {
  if (props.active) void load()
  else request?.abort()
}, { immediate: true })
onBeforeUnmount(() => { alive = false; request?.abort() })
</script>

<template>
  <section id="scene-panel" class="scene-manager" role="tabpanel" aria-labelledby="scene-tab">
    <form class="table-tools" @submit.prevent="search">
      <label class="search-field"><Search :size="15" /><input v-model="input" aria-label="搜索场景" placeholder="名称或完整场景 ID" maxlength="120"></label>
      <button class="secondary-button" type="submit">搜索</button>
      <button class="secondary-button refresh-button" type="button" @click="load"><RefreshCw :size="14" />刷新场景</button>
    </form>
    <div class="table-description"><span>{{ total }} 个场景</span><p>打开保存的画面，或删除不再使用的场景。</p></div>
    <div v-if="loading" class="empty-state" role="status"><LoaderCircle :size="24" class="spin" /><strong>正在读取场景</strong></div>
    <div v-else-if="error" class="empty-state" role="alert"><Layers :size="32" :stroke-width="1.3" /><strong>场景加载失败</strong><p>{{ error }}</p></div>
    <div v-else-if="!scenes.length" class="empty-state"><Layers :size="32" :stroke-width="1.3" /><strong>{{ query ? '没有匹配的场景' : '还没有保存的场景' }}</strong><p>{{ query ? '调整名称或场景 ID 后再搜索。' : '收藏当前画面或保存仿真场景后，可在这里管理。' }}</p></div>
    <ul v-else class="scenes">
      <li v-for="scene in scenes" :key="scene.id">
        <div class="scene-summary">
          <div><h3>{{ scene.name }}</h3><p>{{ scene.id }} · v{{ scene.version }}</p><p>更新于 {{ dateFormat.format(new Date(scene.updated_at)) }} · 北京时间</p></div>
          <div class="scene-actions"><button class="text-button" @click="emit('open', scene)">打开场景</button><button class="text-button" @click="ask(scene)">删除</button></div>
        </div>
        <details><summary>资产版本（{{ assetVersions(scene).length }}）</summary><ul><li v-for="asset in assetVersions(scene)" :key="asset">{{ asset }}</li></ul></details>
      </li>
    </ul>
    <nav class="pagination" aria-label="场景分页">
      <button :disabled="loading || page <= 1" @click="page--">上一页</button>
      <span>{{ total }} 个场景 · 第 {{ page }} / {{ pages }} 页</span>
      <button :disabled="loading || page >= pages" @click="page++">下一页</button>
    </nav>
    <ConfirmDialog v-if="pending" title="删除场景？" confirm-label="删除场景" :busy="deleting" :error="deleteError"
      @close="pending = null" @confirm="remove">
      <p>将删除「{{ pending.name }}」v{{ pending.version }}。对应复现链接会失效，历史运行仍可查看。</p>
    </ConfirmDialog>
  </section>
</template>

<style scoped>
.scene-manager { color: #435870; }
.scene-summary, .scene-actions { display: flex; flex-wrap: wrap; align-items: center; gap: 10px; }
.scene-summary { justify-content: space-between; }
.scenes { list-style: none; margin: 0; padding: 0 24px; }
.scenes > li { border-bottom: 1px solid var(--line); padding: 12px 0; overflow-wrap: anywhere; }
h3 { margin: 0; font-size: 14px; }
p, details, nav { font-size: 12px; }
.scene-summary p { margin: 4px 0; }
summary { cursor: pointer; color: var(--blue); }
</style>
