<script setup lang="ts">
import { LocateFixed, RotateCw, X } from '@lucide/vue'
import { computed, nextTick, ref } from 'vue'
import type { TilesCalibrationOffsets } from '../../map/tilesCalibrationTypes'

const props = defineProps<{
  name: string
  offsets: Record<keyof TilesCalibrationOffsets, number | ''>
  busy: boolean
  ready: boolean
  saveReady: boolean
  canPick: boolean
  message: string
  error: string
}>()
const emit = defineEmits<{
  change: [key: keyof TilesCalibrationOffsets, value: number | '']
  pick: [kind: 'pivot' | 'ground']
  save: [mode: 'update' | 'copy', name?: string]
  cancel: []
}>()
const copying = ref(false)
const copyName = ref(`${props.name.slice(0, 117)}-校准`)
const copyInput = ref<HTMLInputElement>()
const canSave = computed(() => props.saveReady && !props.busy)

const positionFields = [
  ['east', '东西（米）'],
  ['north', '南北（米）'],
  ['up', '高度（米）'],
] as const
const rotationFields = [
  ['yaw', '偏航（°）'],
  ['pitch', '俯仰（°）'],
  ['roll', '横滚（°）'],
] as const

function change(key: keyof TilesCalibrationOffsets, event: Event) {
  const value = (event.target as HTMLInputElement).valueAsNumber
  emit('change', key, Number.isFinite(value) ? value : '')
}

function beginCopy() {
  copying.value = true
  void nextTick(() => copyInput.value?.focus())
}

function submitCopy() {
  if (copying.value && canSave.value && copyName.value.trim()) emit('save', 'copy', copyName.value)
}
</script>

<template>
  <section class="calibration-editor panel" aria-label="校准模型" :aria-busy="props.busy">
    <header>
      <div><h2>校准模型</h2><p :title="name">{{ name }}</p></div>
      <button class="icon-button" type="button" aria-label="取消模型校准" :disabled="busy" @click="emit('cancel')"><X :size="16" /></button>
    </header>
    <form @submit.prevent="submitCopy">
      <div class="calibration-body map-panel-scroll" role="region" aria-label="模型校准参数" tabindex="0">
        <fieldset :disabled="busy">
          <legend>位置</legend>
          <p class="hint">可拖动地图手柄。正值向东、向北或向上。</p>
          <div class="calibration-fields">
            <label v-for="[key, title] in positionFields" :key="key">
              {{ title }}<input :value="offsets[key]" type="number" step="any" @input="change(key, $event)" />
            </label>
          </div>
          <button type="button" class="reference-action text-button" :disabled="!ready || busy" @click="emit('pick', 'ground')">
            <LocateFixed :size="14" aria-hidden="true" />选择模型贴地点（可选）
          </button>
          <p v-if="message" class="hint" role="status">{{ message }}</p>
        </fieldset>
        <fieldset :disabled="busy">
          <legend>旋转</legend>
          <p class="hint">从上方看，正偏航为顺时针。</p>
          <div class="calibration-fields">
            <label v-for="[key, title] in rotationFields" :key="key">
              {{ title }}<input :value="offsets[key]" type="number" step="any" @input="change(key, $event)" />
            </label>
          </div>
          <button type="button" class="reference-action text-button" :disabled="!canPick || busy" @click="emit('pick', 'pivot')">
            <RotateCw :size="14" aria-hidden="true" />另选旋转中心
          </button>
        </fieldset>
        <label v-if="copying" class="copy-name">
          新资产名称<input ref="copyInput" v-model="copyName" maxlength="120" required :disabled="busy" />
        </label>
        <p v-if="error" class="calibration-error" role="alert">{{ error }}</p>
      </div>
      <footer>
        <template v-if="copying">
          <button type="button" class="text-button" :disabled="busy" @click="copying = false">返回</button>
          <button type="submit" class="primary-button" :disabled="!canSave || !copyName.trim()">保存新资产</button>
        </template>
        <template v-else>
          <button type="button" class="text-button" :disabled="!canSave" @click="emit('save', 'update')">更新原资产</button>
          <button type="button" class="primary-button" :disabled="!canSave" @click="beginCopy">另存为新资产</button>
        </template>
      </footer>
    </form>
  </section>
</template>

<style scoped>
.calibration-editor {
  display: flex;
  flex-direction: column;
  width: min(332px, calc(100vw - 24px));
  max-block-size: min(65svh, calc(100svh - 218px));
  overflow: hidden;
  font-size: 12px;
}
header, footer { display: flex; align-items: center; justify-content: space-between; gap: 8px; flex-shrink: 0; padding: 10px 14px; }
header { border-bottom: 1px solid var(--line); }
header div { min-width: 0; }
h2 { font-size: 14px; font-weight: 600; }
header p { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; color: #53657e; }
form { display: flex; flex-direction: column; min-height: 0; }
.calibration-body { padding: 10px 14px; }
.calibration-body:focus-visible { outline: 2px solid var(--blue); outline-offset: -2px; }
.hint { margin: 4px 0 8px; line-height: 1.5; color: #62748b; }
fieldset { padding: 0; min-width: 0; margin: 0; border: 0; }
fieldset + fieldset { margin-top: 12px; }
legend { padding: 0; font-weight: 600; }
.calibration-fields { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 8px; }
label { display: grid; min-width: 0; gap: 4px; }
input { width: 100%; min-width: 0; min-height: 32px; padding: 4px 8px; border: 1px solid #d8e1ed; border-radius: 5px; color: inherit; }
.calibration-error { margin-top: 10px; color: #a33d32; overflow-wrap: anywhere; }
.reference-action { gap: 6px; min-height: 30px; margin-top: 4px; }
.copy-name { margin-top: 10px; }
footer { flex-wrap: wrap; justify-content: flex-end; border-top: 1px solid var(--line); }
@media (max-width: 760px) {
  .calibration-editor { max-block-size: calc(100svh - 126px); }
}
@media (max-width: 350px) {
  .calibration-fields { grid-template-columns: repeat(2, minmax(0, 1fr)); }
}
</style>
