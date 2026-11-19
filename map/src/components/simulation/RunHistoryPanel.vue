<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { X, RefreshCw, LoaderCircle, RotateCcw } from '@lucide/vue'
import type { RunRecord, SceneRecord } from '../../simulation/simulationTypes'
import { useRunHistory } from '../../composables/useRunHistory'
import { ApiError } from '../../api/api'

const props = withDefaults(defineProps<{ scenes: SceneRecord[]; locked: boolean; selected: string; revision: string; recovery?: number; embedded?: boolean; active?: boolean }>(), { active: true })
const emit = defineEmits<{ close: []; select: [identity: string]; rerun: [identity: string]; deleted: [identity: string] }>()
const { items, total, page, pageSize, loading, error, refresh, setQuery, setPage, remove } = useRunHistory()
const pendingDelete = ref('')
const deleting = ref(false)
const deleteError = ref('')
const terminal = (item: RunRecord) => ['succeeded', 'failed', 'cancelled'].includes(item.status)
async function confirmDelete() {
  if (!pendingDelete.value || deleting.value || props.locked) return
  const identity = pendingDelete.value
  deleting.value = true
  deleteError.value = ''
  try {
    await remove(identity)
    pendingDelete.value = ''
    emit('deleted', identity)
  } catch (cause) {
    const references = cause instanceof ApiError ? (cause.detail as { references?: { name: string; type: string }[] } | null)?.references : undefined
    deleteError.value = (cause instanceof Error ? cause.message : '删除失败') + (references?.length ? `：${references.map(item => `${item.type === 'scene' ? '场景' : '收藏'}「${item.name}」`).join('、')}` : '')
  } finally { deleting.value = false }
}
const scene = ref('')
const status = ref<RunRecord['status'] | ''>('')
const from = ref('')
const to = ref('')
const pages = computed(() => Math.max(1, Math.ceil(total.value / pageSize.value)))
const states: Record<RunRecord['status'], string> = { queued: '排队', running: '运行中', succeeded: '成功', failed: '失败', cancelled: '已取消' }
function apply() {
  const iso = (value: string) => value ? new Date(`${value}+08:00`).toISOString() : ''
  void setQuery({ scene_id: scene.value, status: status.value, from: iso(from.value), to: iso(to.value) })
}
function clear() { scene.value = ''; status.value = ''; from.value = ''; to.value = ''; apply() }
function date(value: string) { return new Date(value).toLocaleString('zh-CN', { timeZone: 'Asia/Shanghai', hour12: false }) }
function escape(event: KeyboardEvent) {
  if (event.defaultPrevented || !props.active || event.key !== 'Escape') return
  if (pendingDelete.value) {
    event.preventDefault(); event.stopPropagation()
    if (!deleting.value) pendingDelete.value = ''
  } else if (!props.embedded && !deleting.value) { event.preventDefault(); emit('close') }
}
watch([() => props.active, () => props.revision, () => props.recovery], () => { if (props.active) void refresh() })
onMounted(() => { if (props.active) void refresh(); document.addEventListener('keydown', escape) })
onBeforeUnmount(() => document.removeEventListener('keydown', escape))
</script>

<template>
  <aside class="run-history" :class="{ panel: !embedded, embedded }" aria-label="运行历史" @keydown="escape">
    <header v-if="!embedded"><div><span class="eyebrow">RUN HISTORY</span><h2>运行历史</h2></div><button class="icon-button" :disabled="deleting" aria-label="关闭运行历史" @click="emit('close')"><X :size="18" /></button></header>
    <details class="history-filter-disclosure"><summary>筛选运行记录</summary>
    <form class="history-filters" @submit.prevent="apply">
      <label>场景ID<input v-model="scene" list="history-scenes" aria-label="历史场景ID" placeholder="全部场景，可输入已删除场景ID"><datalist id="history-scenes"><option v-for="item in scenes" :key="item.id" :value="item.id">{{ item.name }}</option></datalist></label>
      <label>状态<select v-model="status" aria-label="历史状态"><option value="">全部状态</option><option v-for="(label, value) in states" :key="value" :value="value">{{ label }}</option></select></label>
      <label>开始时间（北京时间）<input v-model="from" type="datetime-local" aria-label="历史开始时间"></label>
      <label>结束时间（北京时间）<input v-model="to" type="datetime-local" aria-label="历史结束时间"></label>
      <div class="filter-actions"><button type="submit" class="primary-button">筛选</button><button type="button" class="text-button" @click="clear">清除筛选</button><button type="button" class="text-button" :disabled="loading" aria-label="刷新运行历史" @click="refresh"><RefreshCw :size="13" />刷新</button></div>
    </form></details>
    <p v-if="loading" class="history-message"><LoaderCircle :size="14" class="spin" />正在读取运行记录…</p>
    <p v-if="error" class="history-error" role="alert">{{ error }}</p>
    <div v-if="pendingDelete" class="delete-confirm" role="alertdialog" aria-label="删除运行确认">
      <strong>{{ pendingDelete }}</strong>
      <p>将彻底删除此运行的输入快照、计算结果和日志，并释放它的资产引用。源数据、场景和收藏保留。</p>
      <p v-if="deleteError" class="history-error" role="alert">{{ deleteError }}</p>
      <button :disabled="deleting || locked" @click="confirmDelete">{{ deleting ? '正在删除…' : '确认删除' }}</button>
      <button :disabled="deleting" @click="pendingDelete = ''; deleteError = ''">取消</button>
    </div>
    <p v-if="!error && !loading && !items.length" class="history-message">没有符合筛选条件的运行记录。</p>
    <ol v-if="items.length" class="history-list">
      <li v-for="item in items" :key="item.run_id" :class="{ selected: item.run_id === selected }">
        <div class="record-heading"><strong>{{ scenes.find(scene => scene.id === item.scene_id)?.name ?? '场景' }} · v{{ item.scene_version }}</strong><span class="record-status">{{ states[item.status] }}</span></div>
        <button :disabled="locked || deleting" class="run-id" :aria-label="`查看运行 ${item.run_id}`" @click="emit('select', item.run_id)">{{ item.run_id }}</button>
        <p class="record-scene">场景ID：{{ item.scene_id }}</p><time :datetime="item.submitted_at">{{ date(item.submitted_at) }}</time>
        <details class="record-details"><summary>版本信息</summary><p>{{ item.model_version }} · {{ item.data_version }}</p></details>
        <div class="record-actions"><button class="text-button" :disabled="locked || deleting" :aria-label="`重跑运行 ${item.run_id}`" @click="emit('rerun', item.run_id)"><RotateCcw :size="12" />重跑</button>
          <button class="text-button delete-run" :disabled="locked || deleting || !terminal(item)" :title="terminal(item) ? '删除运行及结果文件' : '请先取消运行，再删除'" :aria-label="`删除运行 ${item.run_id}`" @click="pendingDelete = item.run_id; deleteError = ''">删除</button></div>
      </li>
    </ol>
    <footer><span>{{ total }} 条运行 · 第 {{ page }} / {{ pages }} 页</span><button :disabled="loading || page <= 1" aria-label="上一页运行" @click="setPage(page - 1)">上一页</button><button :disabled="loading || page >= pages" aria-label="下一页运行" @click="setPage(page + 1)">下一页</button></footer>
    <p class="history-hint">查看使用固定输入快照；重跑创建新的run_id，保留原输入哈希和版本。</p>
  </aside>
</template>

<style scoped>
.run-history { position: absolute; z-index: 4; inset: 84px 24px 28px auto; width: min(650px, calc(100% - 48px)); padding: 16px; display: flex; flex-direction: column; gap: 16px; color: var(--text); }
.run-history.embedded { position: relative; inset: auto; width: 100%; min-height: 0; }
.embedded .history-list { flex: none; overflow: visible; }
.embedded .history-filter-disclosure, .embedded .delete-confirm { max-height: none; }
header, .record-heading { display: flex; align-items: center; justify-content: space-between; gap: 12px; }
h2 { margin: 0; font-size: 18px; }
summary { cursor: pointer; color: #475569; font-size: 12px; }
.history-filter-disclosure { flex-shrink: 0; max-height: 45%; overflow: auto; }
.history-filter-disclosure > summary { min-height: 36px; line-height: 36px; font-size: 14px; }
.history-filters { display: grid; gap: 12px; margin-top: 12px; }
label { display: grid; gap: 8px; font-size: 14px; min-width: 0; color: #334155; }
input, select { width: 100%; min-width: 0; padding: 9px; border: 1px solid var(--line); border-radius: 5px; background: white; color: var(--text); font: inherit; }
.filter-actions, .record-actions { display: flex; flex-wrap: wrap; align-items: center; gap: 8px; }
.filter-actions button, .record-actions button { min-height: 36px; gap: 8px; }
.filter-actions .primary-button { padding: 8px 12px; }
.text-button { color: var(--blue); font-size: 14px; }
.history-message { display: flex; align-items: center; gap: 8px; color: #475569; font-size: 12px; line-height: 1.7; }
.history-error { color: #b42318; font-size: 12px; overflow-wrap: anywhere; }
.history-list { flex: 1; min-height: 0; overflow: auto; overscroll-behavior: contain; list-style: none; padding: 0; margin: 0; }
.history-list li { display: grid; gap: 8px; padding: 12px; margin-bottom: 12px; border: 1px solid var(--line); border-radius: 6px; }
.history-list li.selected { border-color: var(--blue); background: #eff6ff; }
.record-heading strong { font-size: 14px; overflow-wrap: anywhere; }
.record-status { flex-shrink: 0; color: #475569; font-size: 12px; }
.run-id { text-align: left; justify-content: start; padding: 0; color: var(--blue); font-size: 12px; overflow-wrap: anywhere; }
time, .record-scene, .record-details { color: #475569; font-size: 12px; line-height: 1.7; overflow-wrap: anywhere; }
.record-details p { margin-top: 8px; }
.record-actions { justify-content: flex-end; }
.delete-run { color: #b42318; }
footer { display: flex; flex-wrap: wrap; align-items: center; gap: 8px; flex-shrink: 0; border-top: 1px solid var(--line); padding-top: 12px; font-size: 12px; color: #475569; }
footer span { width: 100%; }
footer button { min-height: 36px; color: var(--blue); }
.history-hint { font-size: 12px; color: #475569; line-height: 1.7; }
button:disabled { opacity: .45; cursor: default; }
.delete-confirm { flex-shrink: 0; max-height: 45%; overflow: auto; padding: 12px; border: 1px solid #efd6ce; border-radius: 6px; font-size: 12px; line-height: 1.7; }
.delete-confirm button { color: var(--blue); margin: 8px 8px 0 0; min-height: 36px; }
.delete-confirm strong { overflow-wrap: anywhere; }
@media (max-width: 600px) { .run-history:not(.embedded) { inset: 72px 12px 12px; width: auto; } }
</style>
