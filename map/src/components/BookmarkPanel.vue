<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { Bookmark as BookmarkIcon, MapPin, X, LoaderCircle } from '@lucide/vue'
import { getBookmarks, createBookmark, renameBookmark, deleteBookmark } from '../api'
import type { Bookmark, BookmarkInput } from '../types'
import type { MapController, MapPoint } from '../mapController'
import { resolveRegionTarget, type RegionTarget } from '../regions'

const props = defineProps<{
  selected: RegionTarget
  active: boolean
  getController: () => MapController | undefined
}>()
const emit = defineEmits<{
  select: [region: RegionTarget]
  point: [point: MapPoint]
  notice: [message: string]
}>()
type Draft = Omit<Extract<BookmarkInput, { kind: 'region' }>, 'name'>
  | Omit<Extract<BookmarkInput, { kind: 'point' }>, 'name'>
  | { kind: 'rename'; id: string }
const open = ref(false)
const busy = ref(false)
const bookmarks = ref<Bookmark[]>([])
const draft = ref<Draft>()
const name = ref('')
const picking = ref(false)
const error = ref('')
const deleting = ref<string>()
const trigger = ref<HTMLButtonElement>()
const nameInput = ref<HTMLInputElement>()
const ordered = computed(() => [...bookmarks.value].sort((a, b) =>
  b.created_at.localeCompare(a.created_at)))
let retryAction: (() => Promise<void>) | undefined
let alive = true

function clearError() {
  error.value = ''
  retryAction = undefined
}
function fail(cause: unknown, retry: () => Promise<void>) {
  error.value = cause instanceof Error ? cause.message : '操作失败，请检查后端服务后重试'
  retryAction = retry
}
async function load() {
  if (busy.value) return
  busy.value = true
  clearError()
  try {
    const records = await getBookmarks()
    if (alive) bookmarks.value = records.filter(item => item.kind !== 'scene')
  } catch (cause) {
    if (alive) fail(cause, load)
  } finally {
    busy.value = false
  }
}
function cancelDraft() {
  if (picking.value || draft.value?.kind === 'point')
    props.getController()?.cancelPointPicking()
  picking.value = false
  draft.value = undefined
  deleting.value = undefined
  clearError()
}
function close(focus = true) {
  cancelDraft()
  open.value = false
  if (focus) trigger.value?.focus()
}
function toggle() {
  if (open.value) close()
  else {
    open.value = true
    void load()
  }
}
async function focusName() {
  await nextTick()
  if (alive && open.value) nameInput.value?.focus()
}
function addRegion() {
  cancelDraft()
  draft.value = { kind: 'region', region_id: props.selected.id }
  name.value = props.selected.label
  void focusName()
}
function pickPoint() {
  const controller = props.getController()
  if (!controller) {
    emit('notice', '地图尚未就绪，请稍后重试。')
    return
  }
  cancelDraft()
  picking.value = true
  controller.beginPointPicking((point) => {
    if (!alive || !props.active || !picking.value) return
    picking.value = false
    draft.value = { kind: 'point', ...point }
    name.value = '收藏点位'
    void focusName()
  })
}
function rename(bookmark: Bookmark) {
  cancelDraft()
  draft.value = { kind: 'rename', id: bookmark.id }
  name.value = bookmark.name
  void focusName()
}
async function save() {
  const current = draft.value
  if (busy.value || !current || !name.value.trim()) return
  busy.value = true
  clearError()
  try {
    const record = current.kind === 'rename'
      ? await renameBookmark(current.id, name.value.trim())
      : await createBookmark({ ...current, name: name.value.trim() })
    if (!alive) return
    bookmarks.value = [record, ...bookmarks.value.filter((item) => item.id !== record.id)]
    draft.value = undefined
    emit('notice', current.kind === 'rename' ? '收藏名称已更新。' : '位置已收藏。')
  } catch (cause) {
    if (alive) fail(cause, save)
  } finally {
    busy.value = false
  }
}
async function remove(bookmark: Bookmark) {
  if (busy.value) return
  busy.value = true
  clearError()
  try {
    await deleteBookmark(bookmark.id)
    if (!alive) return
    bookmarks.value = bookmarks.value.filter((item) => item.id !== bookmark.id)
    deleting.value = undefined
  } catch (cause) {
    if (alive) fail(cause, () => remove(bookmark))
  } finally {
    busy.value = false
  }
}
async function locate(bookmark: Bookmark) {
  if (busy.value) return
  cancelDraft()
  busy.value = true
  try {
    if (bookmark.kind === 'point') {
      if (bookmark.longitude === null || bookmark.latitude === null)
        throw new Error('收藏点位坐标无效')
      emit('point', { longitude: bookmark.longitude, latitude: bookmark.latitude })
    } else {
      const target = await resolveRegionTarget(bookmark.region_id ?? '')
      if (!alive || !props.active) return
      emit('select', target)
    }
    close()
  } catch (cause) {
    if (alive) fail(cause, () => locate(bookmark))
  } finally {
    busy.value = false
  }
}
function retry() {
  if (!busy.value) void retryAction?.()
}
function onKey(event: KeyboardEvent) {
  if (event.key === 'Escape' && open.value) {
    event.preventDefault()
    close()
  }
}
watch(() => props.active, (active) => { if (!active) close(false) })
watch(() => props.selected.id, () => {
  if (picking.value || draft.value?.kind === 'point') cancelDraft()
})
onMounted(() => document.addEventListener('keydown', onKey))
onBeforeUnmount(() => {
  alive = false
  cancelDraft()
  document.removeEventListener('keydown', onKey)
})
</script>

<template>
  <div class="bookmark-panel">
    <button ref="trigger" class="bookmark-trigger panel" :aria-expanded="open"
      aria-controls="bookmark-options" :disabled="!active" @click="toggle">
      <BookmarkIcon :size="14" />收藏位置
    </button>
    <section v-if="open" id="bookmark-options" class="bookmark-menu panel" aria-label="收藏位置">
      <header><h2>收藏位置</h2><button class="icon-button" aria-label="关闭位置收藏" @click="close()"><X :size="16" /></button></header>
      <div class="bookmark-actions">
        <button :disabled="busy" @click="addRegion"><BookmarkIcon :size="14" />收藏所选地区</button>
        <button :disabled="busy" @click="pickPoint"><MapPin :size="14" />地图选点收藏</button>
      </div>
      <p v-if="picking" class="bookmark-hint" role="status">请在地图上点击地面选择点位。<button @click="cancelDraft">取消选点</button></p>
      <form v-if="draft" class="bookmark-form" @submit.prevent="save">
        <label>{{ draft.kind === 'rename' ? '重命名收藏' : '收藏名称' }}<input ref="nameInput" v-model="name" required maxlength="120" :disabled="busy" /></label>
        <label v-if="draft.kind === 'point'">WGS84 经度、纬度<input readonly :value="`${draft.longitude.toFixed(6)}, ${draft.latitude.toFixed(6)}`" /></label>
        <div><button :disabled="busy" type="button" @click="cancelDraft">取消</button><button class="primary-button" :disabled="busy || !name.trim()" type="submit">{{ error ? '重试保存' : '保存收藏' }}</button></div>
      </form>
      <p v-if="error" class="bookmark-error" role="alert">{{ error }}<button :disabled="busy" @click="retry">重试</button></p>
      <p v-if="busy" class="bookmark-hint" role="status"><LoaderCircle :size="14" class="spin" />正在处理…</p>
      <p v-if="!busy && !bookmarks.length && !error" class="bookmark-hint">暂无收藏。可保存当前地区，或在地图上选择点位。</p>
      <ul class="bookmark-list">
        <li v-for="bookmark in ordered" :key="bookmark.id">
          <button class="bookmark-location" :disabled="busy" @click="locate(bookmark)"><MapPin :size="14" /><span>{{ bookmark.name }}<small>{{ bookmark.kind === 'point' ? '地图点位 · WGS84' : '城市与地区' }}</small></span></button>
          <div v-if="deleting === bookmark.id" class="bookmark-delete" role="group" aria-label="确认删除收藏">
            <span>删除此收藏？</span><button :disabled="busy" @click="deleting = undefined">取消</button><button :disabled="busy" @click="remove(bookmark)">确认删除</button>
          </div>
          <div v-else class="bookmark-row-actions"><button :disabled="busy" :aria-label="`重命名${bookmark.name}`" @click="rename(bookmark)">重命名</button><button :disabled="busy" :aria-label="`删除${bookmark.name}`" @click="deleting = bookmark.id">删除</button></div>
        </li>
      </ul>
    </section>
  </div>
</template>

<style scoped>
.bookmark-panel { position: relative; }
.bookmark-trigger { height: 36px; padding: 0 12px; gap: 7px; white-space: nowrap; font-size: 10px; }
.bookmark-trigger svg { color: var(--blue); }
.bookmark-menu { position: absolute; top: 44px; right: 0; width: 340px; max-width: calc(100vw - 24px); max-height: calc(100svh - 190px); overflow-y: auto; padding: 16px 18px; z-index: 5; }
.bookmark-menu header { display: flex; align-items: center; justify-content: space-between; margin-bottom: 12px; }
.bookmark-menu h2 { font-size: 14px; font-weight: 550; }
.bookmark-actions { display: flex; flex-wrap: wrap; gap: 8px; padding-bottom: 14px; border-bottom: 1px solid var(--line); }
.bookmark-actions button { padding: 7px 9px; background: #f2f6fc; color: #6882a8; border-radius: 5px; gap: 6px; font-size: 10px; }
.bookmark-hint { display: flex; align-items: center; flex-wrap: wrap; gap: 7px; font-size: 11px; color: #8291a5; line-height: 1.8; margin-top: 13px; }
.bookmark-hint button, .bookmark-error button { color: var(--blue); }
.bookmark-form { display: flex; flex-direction: column; gap: 12px; padding: 14px 0; border-bottom: 1px solid var(--line); }
.bookmark-form label { display: flex; flex-direction: column; gap: 7px; font-size: 10px; color: #8190a4; }
.bookmark-form input { width: 100%; min-width: 0; height: 34px; border: 1px solid #dde5ef; border-radius: 5px; padding: 0 9px; background: white; color: #3f526b; font-size: 11px; }
.bookmark-form input[readonly] { background: #f6f8fb; }
.bookmark-form > div { display: flex; justify-content: flex-end; align-items: center; gap: 14px; font-size: 11px; }
.bookmark-error { color: #be665b; font-size: 11px; line-height: 1.8; padding-top: 12px; }
.bookmark-error button { margin-left: 10px; }
.bookmark-list { list-style: none; padding: 0; margin: 8px 0 0; }
.bookmark-list li { padding: 9px 0; border-bottom: 1px solid #f0f3f7; }
.bookmark-location { width: 100%; gap: 8px; padding: 3px 0; text-align: left; font-size: 12px; }
.bookmark-location > svg { color: #6882a8; flex-shrink: 0; }
.bookmark-location span { min-width: 0; overflow-wrap: anywhere; }
.bookmark-location small { display: block; font-size: 9px; color: #9aa6b5; margin-top: 5px; }
.bookmark-row-actions, .bookmark-delete { display: flex; justify-content: flex-end; gap: 13px; font-size: 10px; color: #8190a4; margin-top: 7px; }
.bookmark-delete { align-items: center; color: #be665b; }
.bookmark-menu button:disabled { opacity: .5; cursor: default; }
@media (max-width: 600px) { .bookmark-menu { position: fixed; top: 120px; left: 12px; width: calc(100% - 24px); max-width: none; max-height: calc(100svh - 140px); } }
</style>
