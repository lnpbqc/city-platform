<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import {
  X,
  UploadCloud,
  Link,
  LoaderCircle,
  FileArchive,
  FileJson,
} from '@lucide/vue'
import { ApiError, registerAsset, saveLayer, uploadLayer } from '../api'
import type { LayerInput, LayerKind, LayerRecord } from '../types'

const props = defineProps<{ editing?: LayerRecord; initial?: LayerInput }>()
const emit = defineEmits<{ close: []; saved: [record: LayerRecord] }>()
const initial = props.editing ?? props.initial
const mode = ref<'upload' | 'url'>(initial ? 'url' : 'upload')
const name = ref(initial?.name ?? '')
const category = ref(initial?.category ?? '自定义图层')
const kind = ref<LayerKind>(initial?.type ?? 'geojson')
const url = ref(initial?.url ?? '')
const source = ref(initial?.source ?? '')
const coordinateDescription = ref('')
const file = ref<File | null>(null)
const busy = ref(false)
const error = ref('')
const notice = ref('')
const progress = ref(0)
const phase = ref<'uploading' | 'validating' | ''>('')
let controller: AbortController | null = null
let alive = true
const dialog = ref<HTMLElement | null>(null)
const limit = computed(() => (kind.value === 'geojson' ? 10 : 512))
let previousFocus: HTMLElement | null = null

function selectFile(event: Event) {
  const chosen = (event.target as HTMLInputElement).files?.[0] ?? null
  file.value = chosen
  if (chosen && !name.value)
    name.value = chosen.name.replace(/\.(zip|geojson|json)$/i, '')
  error.value =
    chosen && chosen.size > limit.value * 1024 * 1024
      ? `文件超过 ${limit.value} MB 上限`
      : ''
}
async function submit() {
  if (busy.value) return
  error.value = ''
  notice.value = ''
  if (
    mode.value === 'upload' &&
    (!file.value || file.value.size > limit.value * 1024 * 1024)
  ) {
    error.value = !file.value
      ? '请选择数据文件'
      : `文件超过 ${limit.value} MB 上限`
    return
  }
  busy.value = true
  progress.value = 0
  try {
    let record: LayerRecord
    if (mode.value === 'upload') {
      const data = new FormData()
      data.set('file', file.value!)
      data.set('name', name.value.trim())
      data.set('category', category.value.trim())
      data.set('type', kind.value)
      data.set('source', source.value.trim())
      data.set('coordinate_description', coordinateDescription.value.trim())
      controller = new AbortController()
      phase.value = 'uploading'
      record = await uploadLayer(data, {
        signal: controller.signal,
        onProgress: (loaded, total) => {
          progress.value = total
            ? Math.min(100, Math.round((loaded / total) * 100))
            : 0
        },
        onUploaded: () => {
          progress.value = 100
          phase.value = 'validating'
        },
      })
    } else {
      let location = url.value.trim()
      if (!props.editing && !props.initial && /^https?:\/\//i.test(location)) {
        try {
          const asset = await registerAsset({
            name: name.value.trim(),
            type: kind.value,
            location,
            source: source.value.trim(),
            coordinate_description: coordinateDescription.value.trim(),
          })
          location = asset.entry_url!
        } catch (cause) {
          if (!(
            cause instanceof ApiError &&
            cause.code === 'ASSET_ALREADY_REGISTERED'
          ))
            throw cause
        }
      }
      record = await saveLayer(
        {
          name: name.value.trim(),
          category: category.value.trim(),
          type: kind.value,
          url: location,
          source: source.value.trim(),
        },
        props.editing?.id,
      )
    }
    if (alive) emit('saved', record)
  } catch (cause) {
    if (cause instanceof Error && cause.name === 'AbortError')
      notice.value = '上传已取消'
    else
      error.value =
        cause instanceof Error
          ? cause.message
          : '保存失败，请确认后端服务已启动'
  } finally {
    busy.value = false
    phase.value = ''
    controller = null
  }
}
function onKey(event: KeyboardEvent) {
  if (event.key === 'Escape' && !busy.value) emit('close')
  if (event.key === 'Tab' && dialog.value) {
    const elements = [
      ...dialog.value.querySelectorAll<HTMLElement>(
        'button:not(:disabled), input:not(:disabled), select:not(:disabled)',
      ),
    ]
    const first = elements[0],
      last = elements.at(-1)
    if (document.activeElement === dialog.value) {
      event.preventDefault()
      ;(event.shiftKey ? last : first)?.focus()
    } else if (event.shiftKey && document.activeElement === first) {
      event.preventDefault()
      last?.focus()
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault()
      first?.focus()
    }
  }
}
onMounted(() => {
  previousFocus = document.activeElement as HTMLElement
  dialog.value?.focus()
  document.addEventListener('keydown', onKey)
})
onBeforeUnmount(() => {
  alive = false
  controller?.abort()
  document.removeEventListener('keydown', onKey)
  previousFocus?.focus()
})
</script>

<template>
  <div class="modal-backdrop" @click.self="!busy && emit('close')">
    <section
      ref="dialog"
      class="data-dialog"
      role="dialog"
      aria-modal="true"
      aria-labelledby="dialog-title"
      tabindex="-1"
    >
      <header class="dialog-header">
        <div>
          <span class="eyebrow">DATA CONNECTION</span>
          <h2 id="dialog-title">
            {{ editing ? '编辑图层登记' : '添加数据图层' }}
          </h2>
        </div>
        <button
          class="icon-button"
          aria-label="关闭添加图层"
          :disabled="busy"
          @click="emit('close')"
        >
          <X :size="20" />
        </button>
      </header>
      <div v-if="!editing" class="dialog-tabs">
        <button
          :class="{ active: mode === 'upload' }"
          :disabled="busy"
          @click="mode = 'upload'"
        >
          <UploadCloud :size="16" />上传文件</button
        ><button
          :class="{ active: mode === 'url' }"
          :disabled="busy"
          @click="mode = 'url'"
        >
          <Link :size="16" />登记地址
        </button>
      </div>
      <form @submit.prevent="submit">
        <fieldset :disabled="busy">
          <div class="form-row">
            <label
              >图层名称<input
                v-model="name"
                required
                maxlength="120"
                placeholder="例如：研究区建筑模型" /></label
            ><label
              >数据类型<select v-model="kind" @change="file = null">
                <option value="geojson">GeoJSON · 点 / 线 / 面</option>
                <option value="3dtiles">3D Tiles · 三维模型</option>
              </select></label
            >
          </div>
          <label v-if="mode === 'upload'" class="upload-area"
            ><component
              :is="kind === 'geojson' ? FileJson : FileArchive"
              :size="30"
              :stroke-width="1.5" /><strong>{{
              file?.name || '点击选择数据文件'
            }}</strong
            ><span>{{
              kind === 'geojson'
                ? 'WGS84 GeoJSON，最大 10 MB'
                : '包含 tileset.json 的 ZIP，最大 512 MiB'
            }}</span
            ><input
              :key="kind"
              type="file"
              :accept="kind === 'geojson' ? '.geojson,.json' : '.zip'"
              aria-label="选择数据文件"
              @change="selectFile"
          /></label>
          <label v-else
            >数据地址<input
              v-model="url"
              required
              maxlength="2048"
              placeholder="https://…/tileset.json 或 /data-files/…"
            /><small
              >远程服务需允许跨域访问。地址登记不会检查远端数据是否可加载。</small
            ></label
          >
          <div class="form-row">
            <label
              >分类<input v-model="category" required maxlength="80" /></label
            ><label
              >来源说明<input
                v-model="source"
                maxlength="500"
                placeholder="数据提供方 / 合成演示"
            /></label>
          </div>
          <label v-if="!editing"
            >坐标说明<input
              v-model="coordinateDescription"
              maxlength="1000"
              placeholder="例如：WGS84，经纬度；高程单位：米"
          /></label>
        </fieldset>
        <p v-if="error" class="form-error" role="alert">{{ error }}</p>
        <p v-if="notice" class="form-hint" role="status">{{ notice }}</p>
        <div
          v-if="phase"
          class="upload-progress"
          role="status"
          aria-live="polite"
        >
          <progress
            :value="progress"
            max="100"
            aria-label="上传传输进度"
          ></progress>
          <span>{{
            phase === 'uploading'
              ? `正在传输 ${progress}%`
              : '传输完成 100%，正在校验与发布'
          }}</span>
          <button type="button" @click="controller?.abort()">取消上传</button>
        </div>
        <p v-if="mode === 'upload' && kind === '3dtiles'" class="form-hint">
          支持已地理配准的 3D Tiles。ZIP 解压后不超过 2 GiB、10,000 个文件。
        </p>
        <footer class="dialog-footer">
          <span>{{
            busy
              ? phase === 'validating'
                ? '正在校验与发布…'
                : '正在保存…'
              : '保存后留在管理页，可按需加入地图'
          }}</span
          ><button class="primary-button" type="submit" :disabled="busy">
            <LoaderCircle v-if="busy" :size="16" class="spin" />{{
              busy
                ? '正在保存'
                : editing
                  ? '保存修改'
                  : mode === 'upload'
                    ? '上传并登记'
                    : '保存登记'
            }}
          </button>
        </footer>
      </form>
    </section>
  </div>
</template>

<style scoped>
.upload-progress {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 10px;
  margin-top: 16px;
  font-size: 12px;
  color: #52657d;
}
.upload-progress progress {
  width: 100%;
  accent-color: var(--blue);
}
.upload-progress button {
  margin-left: auto;
  color: #b64d46;
}
.modal-backdrop {
  position: fixed;
  inset: 0;
  z-index: 30;
  background: #14233555;
  backdrop-filter: blur(3px);
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 20px;
}
.data-dialog {
  width: 560px;
  background: #fff;
  border-radius: 12px;
  box-shadow: 0 20px 80px #15233435;
  max-height: calc(100svh - 40px);
  overflow: auto;
  padding: 24px 28px;
  animation: dialog-in 0.22s ease-out;
}
.dialog-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  margin-bottom: 22px;
}
.dialog-header h2 {
  font-size: 20px;
  font-weight: 550;
  margin-top: 7px;
}
.dialog-tabs {
  display: flex;
  gap: 24px;
  border-bottom: 1px solid var(--line);
  margin-bottom: 22px;
}
.dialog-tabs button {
  height: 38px;
  gap: 7px;
  font-size: 12px;
  color: #8e9aac;
  position: relative;
  padding: 0 3px;
}
.dialog-tabs button.active {
  color: var(--blue);
}
.dialog-tabs button.active:after {
  content: '';
  position: absolute;
  bottom: -1px;
  height: 2px;
  background: var(--blue);
  inset-inline: 0;
}
.data-dialog fieldset {
  border: 0;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 18px;
  min-width: 0;
}
.data-dialog label {
  display: flex;
  flex-direction: column;
  gap: 8px;
  font-size: 11px;
  color: #687b93;
  min-width: 0;
}
.data-dialog input:not([type='file']),
.data-dialog select {
  width: 100%;
  height: 38px;
  border: 1px solid #dde5ef;
  border-radius: 5px;
  background: #fff;
  padding: 0 10px;
  color: #3f526b;
  font-size: 11px;
  min-width: 0;
}
.data-dialog input::placeholder {
  color: #a9b2bf;
}
.data-dialog small {
  font-size: 10px;
  color: #9aa6b5;
  line-height: 1.7;
}
.form-row {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 16px;
}
.upload-area {
  position: relative;
  border: 1px dashed #c6d5eb;
  border-radius: 7px;
  min-height: 145px;
  display: flex !important;
  align-items: center;
  justify-content: center;
  gap: 10px !important;
  background: #f8faff;
  cursor: pointer;
  padding: 20px;
  overflow: hidden;
}
.upload-area > svg {
  color: #7a9ac8;
}
.upload-area strong {
  font-size: 12px;
  font-weight: 500;
  color: #627d9e;
  text-align: center;
  overflow-wrap: anywhere;
}
.upload-area span {
  font-size: 10px;
  color: #9aa9bd;
}
.upload-area input {
  position: absolute;
  inset: 0;
  opacity: 0;
  cursor: pointer;
  width: 100%;
  height: 100%;
}
.upload-area:focus-within {
  outline: 2px solid var(--blue);
  outline-offset: 2px;
}
.dialog-footer {
  border-top: 1px solid var(--line);
  margin-top: 24px;
  padding-top: 18px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 15px;
}
.dialog-footer > span {
  font-size: 10px;
  color: #a1acbb;
  line-height: 1.6;
}
.form-error {
  font-size: 11px;
  color: #c25953;
  line-height: 1.7;
  background: #fff5f4;
  border-radius: 5px;
  padding: 9px 12px;
  margin-top: 15px;
}
.form-hint {
  font-size: 10px;
  color: #91a0b3;
  line-height: 1.8;
  margin-top: 15px;
}
@media (max-width: 600px) {
  .data-dialog {
    padding: 20px;
    width: 100%;
  }
  .form-row {
    grid-template-columns: 1fr;
    gap: 16px;
  }
  .dialog-footer > span {
    max-width: 140px;
  }
}
</style>
