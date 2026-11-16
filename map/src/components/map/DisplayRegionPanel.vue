<script setup lang="ts">
import { nextTick, ref, useId, useTemplateRef } from 'vue'
import { Ellipsis, LocateFixed, Plus } from '@lucide/vue'
import type { DisplayRegion, DisplayRegionView } from '../../map/displayRegions'

const props = defineProps<{
  regions: readonly DisplayRegion[]
  loading: boolean
  loadError: string
  capture: () => DisplayRegionView | null
  save: (body: { name: string } | DisplayRegionView | (DisplayRegionView & { name: string }), id?: string) => Promise<void>
  remove: (id: string) => Promise<void>
}>()
const emit = defineEmits<{ open: [region: DisplayRegion]; retry: [] }>()
const panelId = useId()
const nameId = `${panelId}-name`
const expanded = ref('')
const saveButton = ref<HTMLButtonElement>()
let actionButton: HTMLButtonElement | undefined
const edit = ref<{ id?: string; view?: DisplayRegionView } | null>(null)
const name = ref('')
const input = ref<HTMLInputElement>()
let renameInput: HTMLInputElement | null = null
const error = ref('')
const busy = ref(false)
const confirmDelete = ref(false)
const deleteCancel = useTemplateRef<HTMLButtonElement[]>('deleteCancel')

function setRenameInput(element: unknown) {
  renameInput = element as HTMLInputElement | null
}

function closeActions(restoreFocus = false) {
  expanded.value = ''
  confirmDelete.value = false
  if (edit.value?.id) edit.value = null
  const button = actionButton
  actionButton = undefined
  if (restoreFocus) void nextTick(() => (button?.isConnected ? button : saveButton.value)?.focus())
}

function toggleActions(id: string, event: MouseEvent) {
  const open = expanded.value !== id
  closeActions()
  edit.value = null
  error.value = ''
  if (open) {
    expanded.value = id
    actionButton = event.currentTarget as HTMLButtonElement
  }
}

function onEscape(event: KeyboardEvent) {
  if (!expanded.value) return
  event.stopPropagation()
  closeActions(true)
}

function currentView() {
  error.value = ''
  const view = props.capture()
  if (!view) error.value = '请将地图缩放到局部、对准地面，并等待镜头停稳。'
  return view
}

async function begin(region?: DisplayRegion) {
  const view = region ? undefined : currentView()
  if (!region && !view) return
  error.value = ''
  if (!region) closeActions()
  name.value = region?.name ?? ''
  edit.value = { id: region?.id, view: view ?? undefined }
  await nextTick()
  const field = region ? renameInput : input.value
  field?.focus()
}

async function change(action: () => Promise<void>, failure: string) {
  busy.value = true
  error.value = ''
  try {
    await action()
    edit.value = null
    closeActions(true)
  } catch {
    error.value = failure
  } finally {
    busy.value = false
  }
}

function submit() {
  if (!edit.value || !name.value.trim() || busy.value) return
  const { id, view } = edit.value
  void change(() => props.save({ ...view, name: name.value.trim() }, id), '无法保存展示区域，请重试。')
}

function update(region: DisplayRegion) {
  const view = currentView()
  if (view) void change(() => props.save(view, region.id), '无法更新展示视角，请重试。')
}

async function requestDelete() {
  confirmDelete.value = true
  await nextTick()
  deleteCancel.value?.[0]?.focus()
}
</script>

<template>
  <section class="display-regions" aria-label="展示区域" @keydown.esc="onEscape">
    <div class="display-heading">
      <h3>已保存视角</h3>
      <button ref="saveButton" type="button" class="display-save" :disabled="busy || loading || !!loadError" @click="begin()">
        <Plus :size="14" aria-hidden="true" />保存当前视角
      </button>
    </div>
    <div class="display-region-body map-panel-scroll" role="region" aria-label="展示区域列表" tabindex="0">
      <form v-if="edit && !edit.id" class="display-editor" @submit.prevent="submit">
        <label :for="nameId">区域名称</label>
        <input :id="nameId" ref="input" v-model="name" maxlength="120" required />
        <button type="submit" class="display-action" :disabled="busy || !name.trim()">保存</button>
        <button type="button" class="display-action" :disabled="busy" @click="edit = null; saveButton?.focus()">取消</button>
      </form>
      <p v-if="loading && !regions.length" role="status">正在读取展示区域…</p>
      <p v-else-if="loadError" role="alert">{{ loadError }} <button type="button" class="display-action" @click="emit('retry')">重试</button></p>
      <p v-else-if="!regions.length">暂无展示区域</p>
      <ul v-if="regions.length">
        <li v-for="region in regions" :key="region.id">
          <div class="display-row">
            <button type="button" class="display-location" :title="region.name" @click="emit('open', region)">
              <LocateFixed :size="15" aria-hidden="true" /><span>{{ region.name }}</span>
            </button>
            <button type="button" class="icon-button display-manage" :aria-label="`管理${region.name}`" title="管理展示区域"
              :aria-expanded="expanded === region.id" :aria-controls="`${panelId}-${region.id}`" :disabled="busy"
              @click="toggleActions(region.id, $event)">
              <Ellipsis :size="18" aria-hidden="true" />
            </button>
          </div>
          <div v-show="expanded === region.id" :id="`${panelId}-${region.id}`" class="display-editor">
            <form v-if="edit?.id === region.id" @submit.prevent="submit">
              <label :for="nameId">区域名称</label>
              <input :id="nameId" :ref="setRenameInput" v-model="name" maxlength="120" required />
              <button type="submit" class="display-action" :disabled="busy || !name.trim()">保存</button>
              <button type="button" class="display-action" :disabled="busy" @click="closeActions(true)">取消</button>
            </form>
            <div v-else-if="expanded === region.id && confirmDelete" class="display-actions">
              <span>删除「{{ region.name }}」？</span>
              <button type="button" class="display-action display-delete" :disabled="busy" @click="change(() => remove(region.id), '无法删除展示区域，请重试。')">确认删除</button>
              <button ref="deleteCancel" type="button" class="display-action" :disabled="busy" @click="closeActions(true)">取消</button>
            </div>
            <div v-else-if="expanded === region.id" class="display-actions">
              <button type="button" class="display-action" :disabled="busy || loading" @click="begin(region)">改名</button>
              <button type="button" class="display-action" :disabled="busy || loading" @click="update(region)">更新为当前视角</button>
              <button type="button" class="display-action display-delete" :disabled="busy || loading" @click="requestDelete">删除</button>
            </div>
          </div>
        </li>
      </ul>
      <p v-if="error" role="alert">{{ error }}</p>
    </div>
  </section>
</template>

<style scoped>
.display-regions { display: flex; flex-direction: column; min-height: 0; font-size: 12px; overflow-wrap: anywhere; }
.display-region-body { display: grid; align-content: start; gap: 7px; padding: 4px 14px 12px; }
.display-region-body:focus-visible { outline: 2px solid var(--blue); outline-offset: -2px; }
.display-heading, .display-actions, form { display: flex; align-items: center; gap: 6px; flex-wrap: wrap; min-width: 0; }
.display-heading { flex: none; justify-content: space-between; padding: 8px 14px 4px; }
h3, ul, p { margin: 0; }
h3 { font-size: 12px; }
ul { padding: 0; list-style: none; border: 1px solid var(--line); border-radius: 7px; }
li + li { border-top: 1px solid var(--line); }
.display-row { display: grid; grid-template-columns: minmax(0, 1fr) 36px; gap: 2px; align-items: center; padding: 2px 4px; }
.display-location { justify-content: flex-start; gap: 8px; min-width: 0; min-height: 34px; padding: 4px 7px; border-radius: 5px; text-align: left; }
.display-location svg { color: #657b96; }
.display-location span { min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.display-location:hover { background: #f2f6fc; }
.display-manage { width: 36px; height: 34px; color: #566b84; }
.display-manage[aria-expanded="true"] { color: var(--blue); background: #edf3fc; }
.display-location:focus-visible, .display-manage:focus-visible { outline-offset: -1px; }
.display-save, .display-action { gap: 4px; min-height: 30px; padding: 4px 7px; border-radius: 5px; font-size: 11px; }
.display-save { color: var(--blue); background: #eff4fb; }
.display-action:hover:not(:disabled) { background: #edf3fc; }
.display-editor { margin: 0 4px 4px; padding: 4px 7px; border-radius: 5px; background: #f6f8fb; }
.display-delete, .display-delete:hover:not(:disabled) { color: #a33d32; }
form input { min-width: 7em; flex: 1; border: 1px solid var(--line); border-radius: 4px; padding: 5px; font: inherit; }
@media (pointer: coarse) {
  .display-row { grid-template-columns: minmax(0, 1fr) 44px; }
  .display-location, .display-manage, .display-save, .display-action { min-height: 44px; }
  .display-manage { width: 44px; }
}
p[role="alert"] { color: #a33d32; }
</style>
