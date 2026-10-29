<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref } from 'vue'
import { X, LoaderCircle, RefreshCw } from '@lucide/vue'
import type { AssetDetail } from '../types'
import AssetReferences from './AssetReferences.vue'

defineProps<{ asset: AssetDetail | null; busy: boolean; error: string }>()
const emit = defineEmits<{ close: []; retry: [] }>()
const dialog = ref<HTMLElement | null>(null)
let previousFocus: HTMLElement | null = null
function bytes(value: number | null) {
  if (value === null) return '未知'
  if (value < 1024) return `${value} B`
  if (value < 1024 ** 2) return `${(value / 1024).toFixed(1)} KB`
  return `${(value / 1024 ** 2).toFixed(1)} MB`
}
function keydown(event: KeyboardEvent) {
  if (event.key === 'Escape') emit('close')
  if (event.key !== 'Tab' || !dialog.value) return
  const items = [
    ...dialog.value.querySelectorAll<HTMLElement>(
      'button:not(:disabled), a[href], [tabindex="0"]',
    ),
  ]
  const first = items[0],
    last = items.at(-1)
  if (
    document.activeElement === dialog.value ||
    (event.shiftKey && document.activeElement === first)
  ) {
    event.preventDefault()
    ;(event.shiftKey ? last : first)?.focus()
  } else if (!event.shiftKey && document.activeElement === last) {
    event.preventDefault()
    first?.focus()
  }
}
onMounted(() => {
  previousFocus = document.activeElement as HTMLElement
  dialog.value?.focus()
  document.addEventListener('keydown', keydown)
})
onBeforeUnmount(() => {
  document.removeEventListener('keydown', keydown)
  if (previousFocus?.isConnected) previousFocus.focus()
})
</script>

<template>
  <div class="detail-backdrop" @click.self="emit('close')">
    <section
      ref="dialog"
      class="asset-dialog"
      role="dialog"
      aria-modal="true"
      aria-labelledby="asset-detail-title"
      tabindex="-1"
    >
      <header>
        <div>
          <span class="eyebrow">LOCAL FILE ASSET</span>
          <h2 id="asset-detail-title">文件资产详情</h2>
        </div>
        <button
          class="icon-button"
          aria-label="关闭文件详情"
          @click="emit('close')"
        >
          <X :size="20" />
        </button>
      </header>
      <p v-if="busy" class="loading">
        <LoaderCircle :size="18" class="spin" />正在读取文件清单…
      </p>
      <div v-else-if="error" class="detail-error" role="alert">
        {{ error
        }}<button class="text-button" @click="emit('retry')">
          <RefreshCw :size="14" />重试
        </button>
      </div>
      <div v-else-if="asset" class="asset-content">
        <h3>
          {{ asset.name || asset.original_name || '历史文件 · 原始名称未知' }}
        </h3>
        <p class="asset-id">资产 ID：{{ asset.id }}</p>
        <dl>
          <div>
            <dt>数据入口</dt>
            <dd>{{ asset.entry_url || '未找到有效入口' }}</dd>
          </div>
          <div>
            <dt>已发布文件</dt>
            <dd>
              {{ asset.file_count ?? '未知' }} 个 · {{ bytes(asset.byte_size) }}
            </dd>
          </div>
          <div>
            <dt>版本 / 状态</dt>
            <dd>
              {{ asset.current_version || '未提供' }} · {{ asset.status }}
            </dd>
          </div>
          <div>
            <dt>来源</dt>
            <dd>
              {{ asset.source || '未提供' }} ·
              {{
                asset.source_kind === 'external'
                  ? '外部地址'
                  : asset.protected
                    ? '默认资产'
                    : '上传文件'
              }}
            </dd>
          </div>
          <div>
            <dt>坐标说明</dt>
            <dd>{{ asset.coordinate_description || '未提供' }}</dd>
          </div>
          <div>
            <dt>WGS84 范围</dt>
            <dd v-if="asset.bounds">
              西 {{ asset.bounds.west }}，南 {{ asset.bounds.south }}，东
              {{ asset.bounds.east }}，北 {{ asset.bounds.north }}；高程
              {{ asset.bounds.min_height ?? '未知' }} ～
              {{ asset.bounds.max_height ?? '未知' }} 米
            </dd>
            <dd v-else>未知</dd>
          </div>
          <div>
            <dt>SHA-256</dt>
            <dd>{{ asset.sha256 || '未提供' }}</dd>
          </div>
        </dl>
        <p v-if="asset.error" class="detail-error">{{ asset.error }}</p>
        <section class="detail-section">
          <h3>
            资产引用 <span>{{ asset.reference_count }}</span>
          </h3>
          <p v-if="!asset.references.length" class="empty">
            {{
              asset.protected
                ? '默认资产实体文件受保护，可重新登记。'
                : asset.source_kind === 'external'
                  ? '没有引用，可加入地图或移除外部资产登记。'
                  : '没有引用，可重新登记或删除文件。'
            }}
          </p>
          <AssetReferences v-else :references="asset.references" />
        </section>
        <section class="detail-section">
          <h3>
            相对文件清单 <span>{{ asset.files.length }}</span>
          </h3>
          <p v-if="!asset.files.length" class="empty">
            {{
              asset.source_kind === 'external'
                ? '外部资源由浏览器直接加载，文件体积与校验和未知。'
                : '当前没有可读取的文件。'
            }}
          </p>
          <div v-else class="file-list" tabindex="0" aria-label="相对文件清单">
            <table>
              <thead>
                <tr>
                  <th>路径</th>
                  <th>体积</th>
                  <th>SHA-256</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="file in asset.files" :key="file.path">
                  <td>{{ file.path }}</td>
                  <td>{{ bytes(file.size) }}</td>
                  <td class="checksum">
                    {{
                      asset.file_checksums?.find(
                        (item) => item.path === file.path,
                      )?.sha256 || '未提供'
                    }}
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
        </section>
        <p class="hint">
          按完整数据集管理；3D Tiles 的内部瓦片、模型和贴图不单独删除。
        </p>
      </div>
    </section>
  </div>
</template>

<style scoped>
.checksum {
  overflow-wrap: anywhere;
  font-family: Consolas, monospace;
  font-size: 11px;
}
.detail-backdrop {
  position: fixed;
  inset: 0;
  z-index: 35;
  display: grid;
  grid-template-columns: minmax(0, 1fr);
  place-items: center;
  padding: 24px;
  background: #14233555;
  backdrop-filter: blur(3px);
}
.asset-dialog {
  width: min(820px, 100%);
  min-width: 0;
  max-width: 100%;
  max-height: calc(100svh - 48px);
  overflow: hidden;
  display: flex;
  flex-direction: column;
  border-radius: 12px;
  background: #fff;
  box-shadow: 0 20px 80px #15233435;
}
.asset-dialog:focus {
  outline: none;
}
.asset-content {
  min-height: 0;
  overflow-y: auto;
  padding: 24px 28px;
  scrollbar-width: thin;
}
header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 20px;
  flex-shrink: 0;
  padding: 20px 28px;
  border-bottom: 1px solid var(--line);
}
header .icon-button {
  flex-shrink: 0;
}
h2 {
  font-size: 20px;
  font-weight: 550;
  margin-top: 6px;
}
h3 {
  font-size: 14px;
  font-weight: 550;
  overflow-wrap: anywhere;
  margin: 0;
}
h3 span {
  color: #8a9aae;
  font-size: 11px;
  margin-left: 5px;
}
.asset-id {
  color: #8c9aab;
  font-size: 11px;
  margin-top: 7px;
  overflow-wrap: anywhere;
}
dl {
  margin: 20px 0;
  display: grid;
  gap: 12px;
}
dl > div {
  display: grid;
  grid-template-columns: 82px minmax(0, 1fr);
  gap: 10px;
  font-size: 12px;
  line-height: 1.7;
}
dt {
  color: #8a97a9;
}
dd {
  margin: 0;
  color: #52657d;
  overflow-wrap: anywhere;
}
.detail-section {
  border-top: 1px solid var(--line);
  padding-top: 18px;
  margin-top: 22px;
}
.file-list {
  margin-top: 12px;
  max-height: 280px;
  overflow: auto;
  border: 1px solid var(--line);
  border-radius: 6px;
}
table {
  border-collapse: collapse;
  table-layout: fixed;
  width: 100%;
  font-size: 12px;
}
th {
  text-align: left;
  color: #7d8da1;
  font-weight: 500;
  background: #f7f9fc;
  position: sticky;
  top: 0;
}
td,
th {
  padding: 10px 12px;
  border-bottom: 1px solid var(--line);
  vertical-align: top;
  line-height: 1.6;
}
th:first-child {
  width: 44%;
}
th:nth-child(2) {
  width: 90px;
}
td:first-child {
  overflow-wrap: anywhere;
}
td:nth-child(2),
th:nth-child(2) {
  white-space: nowrap;
  text-align: right;
}
.hint,
.empty {
  font-size: 11px;
  line-height: 1.8;
  color: #8d9aac;
  margin-top: 13px;
}
.loading {
  padding: 30px 0;
  display: flex;
  justify-content: center;
  gap: 9px;
  color: #8191a6;
}
.detail-error {
  font-size: 12px;
  color: #b64d46;
  background: #fff4f2;
  padding: 10px 12px;
  line-height: 1.8;
  border-radius: 6px;
}
.text-button {
  color: var(--blue);
  gap: 5px;
  margin-left: 12px;
}
@media (max-width: 600px) {
  .detail-backdrop {
    padding: 12px;
  }
  .asset-dialog {
    max-height: calc(100svh - 24px);
  }
  header,
  .asset-content {
    padding: 20px;
  }
  td,
  th {
    padding: 9px 8px;
  }
  th:first-child {
    width: 40%;
  }
  th:nth-child(2) {
    width: 72px;
  }
}
</style>
