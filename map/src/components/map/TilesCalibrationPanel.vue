<script setup lang="ts">
import { X } from '@lucide/vue'
import { ref } from 'vue'
import type { TilesCalibrationOffsets } from '../../map/tilesCalibrationTypes'

const props = defineProps<{
  name: string
  offsets: Record<keyof TilesCalibrationOffsets, number | ''>
  busy: boolean
  ready: boolean
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

const fields = [
  ['east', '东西（米）'],
  ['north', '南北（米）'],
  ['up', '高度（米）'],
  ['yaw', '偏航（°）'],
  ['pitch', '俯仰（°）'],
  ['roll', '横滚（°）'],
] as const

function change(key: keyof TilesCalibrationOffsets, event: Event) {
  const value = (event.target as HTMLInputElement).valueAsNumber
  emit('change', key, Number.isFinite(value) ? value : '')
}
</script>

<template>
  <section class="calibration-editor panel" aria-label="校准模型" :aria-busy="props.busy">
    <header>
      <div><h2>校准模型</h2><p :title="name">{{ name }}</p></div>
      <button class="icon-button" type="button" aria-label="取消模型校准" :disabled="busy" @click="emit('cancel')"><X :size="16" /></button>
    </header>
    <p class="hint">拖动地图上的手柄水平移动。正值向东、向北或向上；正偏航从上方看为顺时针。</p>
    <form @submit.prevent="emit('save', 'copy', copyName)">
      <fieldset :disabled="busy">
        <label v-for="[key, title] in fields" :key="key">
          {{ title }}<input :value="offsets[key]" type="number" step="any" @input="change(key, $event)" />
        </label>
      </fieldset>
      <div class="reference-actions">
        <button type="button" class="text-button" :disabled="!canPick || busy" @click="emit('pick', 'pivot')">另选旋转中心</button>
        <button type="button" class="text-button" :disabled="!ready || busy" @click="emit('pick', 'ground')">选择模型贴地点</button>
      </div>
      <p v-if="message" role="status">{{ message }}</p>
      <p v-if="error" class="calibration-error" role="alert">{{ error }}</p>
      <label v-if="copying" class="copy-name">
        新资产名称<input v-model="copyName" maxlength="120" required :disabled="busy" />
      </label>
      <footer>
        <template v-if="copying">
          <button type="button" class="text-button" :disabled="busy" @click="copying = false">返回</button>
          <button type="submit" class="primary-button" :disabled="!ready || !copyName.trim() || busy">保存新资产</button>
        </template>
        <template v-else>
          <button type="button" class="text-button" :disabled="!ready || busy" @click="emit('save', 'update')">更新原资产</button>
          <button type="button" class="primary-button" :disabled="!ready || busy" @click="copying = true">另存为新资产</button>
        </template>
      </footer>
    </form>
  </section>
</template>

<style scoped>
.calibration-editor { width: 270px; max-width: calc(100vw - 24px); overflow: auto; max-height: 60vh; padding: 12px; font-size: 12px; }
header, footer { display: flex; align-items: center; justify-content: space-between; gap: 8px; }
header div { min-width: 0; }
h2 { font-size: 14px; }
header p { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; color: #53657e; }
.hint { margin: 8px 0; line-height: 1.5; }
fieldset { padding: 0; min-width: 0; margin: 0 0 8px; border: 0; display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 6px; }
label { display: grid; min-width: 0; gap: 4px; }
input { width: 100%; min-width: 0; padding: 4px 6px; border: 1px solid var(--line); border-radius: 4px; }
.calibration-error { color: #a33d32; overflow-wrap: anywhere; }
.reference-actions { display: flex; flex-wrap: wrap; gap: 8px; }
form p, footer, .copy-name { margin-top: 8px; }
footer { justify-content: flex-end; }
</style>
