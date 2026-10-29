<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { X, RefreshCw, LoaderCircle, RotateCcw } from '@lucide/vue'
import type { RunRecord, SceneRecord } from '../simulationTypes'
import { useRunHistory } from '../composables/useRunHistory'

const props = defineProps<{ scenes: SceneRecord[]; locked: boolean; selected: string; revision: string; recovery?: number }>()
const emit = defineEmits<{ close: []; select: [identity: string]; rerun: [identity: string] }>()
const { items, total, page, pageSize, loading, error, refresh, setQuery, setPage } = useRunHistory()
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
function escape(event: KeyboardEvent) { if (event.key === 'Escape') emit('close') }
watch([() => props.revision, () => props.recovery], () => { void refresh() })
onMounted(() => { void refresh(); document.addEventListener('keydown', escape) })
onBeforeUnmount(() => document.removeEventListener('keydown', escape))
</script>

<template>
  <aside class="run-history panel" aria-label="运行历史">
    <header><div><span class="eyebrow">RUN HISTORY</span><h2>运行历史</h2></div><button class="icon-button" aria-label="关闭运行历史" @click="emit('close')"><X :size="18" /></button></header>
    <form class="history-filters" @submit.prevent="apply">
      <label>场景ID<input v-model="scene" list="history-scenes" aria-label="历史场景ID" placeholder="全部场景，可输入已删除场景ID"><datalist id="history-scenes"><option v-for="item in scenes" :key="item.id" :value="item.id">{{ item.name }}</option></datalist></label>
      <label>状态<select v-model="status" aria-label="历史状态"><option value="">全部状态</option><option v-for="(label, value) in states" :key="value" :value="value">{{ label }}</option></select></label>
      <label>开始时间（北京时间）<input v-model="from" type="datetime-local" aria-label="历史开始时间"></label>
      <label>结束时间（北京时间）<input v-model="to" type="datetime-local" aria-label="历史结束时间"></label>
      <div class="filter-actions"><button type="submit" class="primary-button">筛选</button><button type="button" class="text-button" @click="clear">清除筛选</button><button type="button" class="text-button" :disabled="loading" aria-label="刷新运行历史" @click="refresh"><RefreshCw :size="13" />刷新</button></div>
    </form>
    <p v-if="loading" class="history-message"><LoaderCircle :size="14" class="spin" />正在读取运行记录…</p>
    <p v-if="error" class="history-error" role="alert">{{ error }}</p>
    <p v-else-if="!loading && !items.length" class="history-message">没有符合筛选条件的运行记录。</p>
    <div v-if="items.length" class="history-table">
      <table><thead><tr><th>运行 / 场景</th><th>状态</th><th>提交时间</th><th>操作</th></tr></thead><tbody>
        <tr v-for="item in items" :key="item.run_id" :class="{ selected: item.run_id === selected }">
          <td><button :disabled="locked" class="run-id" :aria-label="`查看运行 ${item.run_id}`" @click="emit('select', item.run_id)">{{ item.run_id }}</button><span>{{ item.scene_id }} · v{{ item.scene_version }}</span><small>{{ item.model_version }} · {{ item.data_version }}</small></td>
          <td>{{ states[item.status] }}</td><td>{{ date(item.submitted_at) }}</td><td><button class="text-button" :disabled="locked" :aria-label="`重跑运行 ${item.run_id}`" @click="emit('rerun', item.run_id)"><RotateCcw :size="12" />重跑</button></td>
        </tr>
      </tbody></table>
    </div>
    <footer><span>{{ total }} 条运行 · 第 {{ page }} / {{ pages }} 页</span><button :disabled="loading || page <= 1" aria-label="上一页运行" @click="setPage(page - 1)">上一页</button><button :disabled="loading || page >= pages" aria-label="下一页运行" @click="setPage(page + 1)">下一页</button></footer>
    <p class="history-hint">查看使用固定输入快照；重跑创建新的run_id，保留原输入哈希和版本。</p>
  </aside>
</template>

<style scoped>
.run-history { position: absolute; z-index: 4; top: 84px; bottom: 28px; right: 24px; width: min(650px, calc(100% - 48px)); padding: 22px; display: flex; flex-direction: column; }
header { display: flex; align-items: center; justify-content: space-between; }
h2 { margin: 5px 0 0; font-size: 22px; }
.history-filters { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; margin-top: 22px; }
label { display: grid; gap: 6px; font-size: 11px; color: #65788e; min-width: 0; }
input, select { min-width: 0; width: 100%; padding: 9px; border: 1px solid var(--line); border-radius: 5px; background: white; color: #29405a; }
.filter-actions { grid-column: 1 / -1; display: flex; align-items: center; gap: 16px; }
.filter-actions .primary-button { padding: 8px 18px; font-size: 11px; }
.text-button { display: inline-flex; align-items: center; gap: 5px; color: var(--blue); font-size: 11px; }
.history-message { margin: 22px 0; font-size: 12px; color: #73859a; display: flex; align-items: center; gap: 7px; }
.history-error { color: #b94e46; font-size: 12px; overflow-wrap: anywhere; }
.history-table { overflow: auto; flex: 1; margin-top: 20px; min-height: 0; }
table { border-collapse: collapse; width: 100%; font-size: 11px; text-align: left; }
th { color: #8c9aab; font-weight: 500; padding: 10px 8px; background: #f6f8fb; position: sticky; top: 0; }
td { color: #52657d; padding: 13px 8px; border-bottom: 1px solid var(--line); vertical-align: top; }
td:first-child { min-width: 185px; max-width: 290px; }
td span, td small { display: block; overflow-wrap: anywhere; margin-top: 5px; font-size: 10px; }
td small { color: #8c9aab; }
.run-id { text-align: left; font-size: 10px; color: var(--blue); overflow-wrap: anywhere; }
tr.selected { background: #edf4ff; }
footer { display: flex; align-items: center; gap: 14px; margin-top: 18px; font-size: 11px; color: #73859a; }
footer span { margin-right: auto; }
footer button { color: var(--blue); }
button:disabled { opacity: .45; cursor: default; }
.history-hint { margin: 15px 0 0; font-size: 10px; color: #8c9aab; line-height: 1.6; }
@media (max-width: 600px) { .run-history { top: 72px; left: 12px; right: 12px; bottom: 12px; width: auto; padding: 16px; } }
</style>
