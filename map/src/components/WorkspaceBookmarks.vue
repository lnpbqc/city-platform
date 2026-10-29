<script setup lang="ts">
import { onBeforeUnmount, ref } from 'vue'
import { Bookmark as BookmarkIcon, X } from '@lucide/vue'
import { createBookmark, deleteBookmark, getBookmarks, renameBookmark } from '../api'
import type { Bookmark } from '../types'
import { workspaceURL, type WorkspaceState } from '../workspaceState'

const props = defineProps<{ enabled: boolean; capture: () => Promise<WorkspaceState> }>()
const emit = defineEmits<{ open: [state: WorkspaceState] }>()
const open = ref(false), busy = ref(false), name = ref('工作台画面'), error = ref(''), link = ref(''), message = ref('')
const bookmarks = ref<Bookmark[]>([])
const renaming = ref(''), rename = ref(''), deleting = ref('')
let alive = true
const fail = (cause: unknown) => { error.value = cause instanceof Error ? cause.message : '收藏操作失败' }
async function load() {
  error.value = ''
  try { const records = await getBookmarks(); if (alive) bookmarks.value = records.filter(record => record.kind === 'scene') }
  catch (cause) { if (alive) fail(cause) }
}
function toggle() { open.value = !open.value; if (open.value) void load() }
async function save() {
  if (busy.value || !name.value.trim()) return
  busy.value = true; error.value = ''; message.value = ''
  try {
    const state = await props.capture()
    const record = await createBookmark({ name: name.value.trim(), kind: 'scene', state })
    if (alive) { bookmarks.value = [record, ...bookmarks.value]; message.value = '完整画面已收藏' }
  } catch (cause) { if (alive) fail(cause) }
  finally { busy.value = false }
}
async function copy() {
  if (busy.value) return
  busy.value = true; error.value = ''; message.value = ''
  try {
    link.value = workspaceURL(await props.capture())
    try { await navigator.clipboard.writeText(link.value); if (alive) message.value = '复现链接已复制' }
    catch { if (alive) message.value = '链接已生成，可在下方选中复制' }
  } catch (cause) { if (alive) fail(cause) }
  finally { busy.value = false }
}
async function saveName(record: Bookmark) {
  if (busy.value || !rename.value.trim()) return
  busy.value = true; error.value = ''
  try {
    const updated = await renameBookmark(record.id, rename.value.trim())
    if (alive) { bookmarks.value = bookmarks.value.map(item => item.id === record.id ? updated : item); renaming.value = '' }
  } catch (cause) { if (alive) fail(cause) }
  finally { busy.value = false }
}
async function remove(record: Bookmark) {
  if (busy.value) return
  busy.value = true; error.value = ''
  try { await deleteBookmark(record.id); if (alive) { bookmarks.value = bookmarks.value.filter(item => item.id !== record.id); deleting.value = '' } }
  catch (cause) { if (alive) fail(cause) }
  finally { busy.value = false }
}
function restore(record: Bookmark) {
  if (!record.state) { error.value = '收藏缺少完整画面状态'; return }
  emit('open', record.state)
  open.value = false
}
onBeforeUnmount(() => { alive = false })
</script>

<template>
  <div class="workspace-bookmarks">
    <button class="workspace-bookmarks-trigger" aria-label="完整画面收藏与链接" :aria-expanded="open" @click="toggle"><BookmarkIcon :size="16" /><span>收藏与链接</span></button>
    <section v-if="open" class="workspace-bookmarks-panel panel" aria-label="完整画面收藏">
      <header><h2>完整画面收藏</h2><button class="icon-button" aria-label="关闭完整画面收藏" @click="open = false"><X :size="16" /></button></header>
      <p>保存固定版本图层、相机、时次和仿真运行。双视图同时保存右侧时间。</p>
      <form @submit.prevent="save"><label>画面名称<input v-model="name" aria-label="完整收藏名称" required maxlength="120" :disabled="busy" /></label>
        <div class="actions"><button class="primary-button" :disabled="busy || !enabled">{{ busy ? '正在处理…' : '收藏当前画面' }}</button><button type="button" class="secondary-button" :disabled="busy || !enabled" @click="copy">复制复现链接</button></div></form>
      <p v-if="!enabled">进入地图或仿真工作区，等待加载完成后保存。</p>
      <p v-if="message" role="status">{{ message }}</p>
      <textarea v-if="link" :value="link" readonly aria-label="当前画面复现链接" @focus="($event.target as HTMLTextAreaElement).select()" />
      <div class="list-heading"><strong>已保存画面 · {{ bookmarks.length }}</strong><button class="text-button" :disabled="busy" @click="load">刷新</button></div>
      <p v-if="!bookmarks.length">暂无完整画面收藏。</p>
      <ul><li v-for="record in bookmarks" :key="record.id">
        <form v-if="renaming === record.id" @submit.prevent="saveName(record)"><input v-model="rename" aria-label="完整收藏新名称" maxlength="120" required><div class="actions"><button :disabled="busy">保存名称</button><button type="button" @click="renaming = ''">取消</button></div></form>
        <template v-else><button class="open-bookmark" :disabled="busy" @click="restore(record)">{{ record.name }}<small>{{ record.state?.page === 'simulation' ? '仿真' : '地图' }} · 场景 v{{ record.state?.scene_version }}</small></button><div class="record-actions"><button :disabled="busy" @click="renaming = record.id; rename = record.name">改名</button><button v-if="deleting !== record.id" :disabled="busy" @click="deleting = record.id">删除</button><template v-else><button :disabled="busy" @click="remove(record)">确认删除</button><button @click="deleting = ''">取消</button></template></div></template>
      </li></ul>
      <p v-if="error" class="error" role="alert">{{ error }}</p>
    </section>
  </div>
</template>

<style scoped>
.workspace-bookmarks-trigger { display: flex; align-items: center; gap: 6px; color: var(--blue); font-size: 11px; white-space: nowrap; }
.workspace-bookmarks-panel { position: absolute; top: 74px; right: 24px; width: 360px; max-width: calc(100vw - 32px); max-height: calc(100svh - 95px); overflow-y: auto; padding: 20px; font-size: 12px; }
header, .actions, .list-heading, .record-actions { display: flex; align-items: center; justify-content: space-between; gap: 10px; }
h2 { font-size: 16px; margin: 0; } p { color: #718195; line-height: 1.7; } label { display: grid; gap: 7px; } input, textarea { width: 100%; border: 1px solid var(--line); padding: 9px; border-radius: 5px; background: white; color: #253c55; } textarea { margin-top: 8px; height: 70px; font-size: 10px; }
.actions { margin-top: 10px; justify-content: flex-start; } .actions button { font-size: 11px; padding: 8px 12px; } .list-heading { margin-top: 24px; padding-bottom: 10px; border-bottom: 1px solid var(--line); } ul { padding: 0; list-style: none; } li { padding: 10px 0; border-bottom: 1px solid var(--line); } .open-bookmark { text-align: left; overflow-wrap: anywhere; } small { display: block; font-size: 10px; color: #8290a0; margin-top: 5px; } .record-actions { justify-content: flex-end; color: var(--blue); font-size: 10px; } .error { color: #b94e46; overflow-wrap: anywhere; }
@media (max-width: 600px) { .workspace-bookmarks-trigger span { display: none; } .workspace-bookmarks-panel { top: 68px; right: 16px; } }
</style>
