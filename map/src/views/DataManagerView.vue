<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import {
  Database,
  FolderOpen,
  Upload,
  Pencil,
  Trash2,
  RefreshCw,
  Search,
  FileJson,
  Box,
  LoaderCircle,
  ArrowUpRight,
  Files,
  Layers,
} from '@lucide/vue'
import type { AssetRecord, LayerRecord, MapLayer } from '../layers/types'
import { getScenes } from '../api/api'
import { useAssets } from '../composables/useAssets'
import SceneManager from '../components/data/SceneManager.vue'
import type { SceneRecord } from '../simulation/simulationTypes'
import AssetDetails from '../components/data/AssetDetails.vue'
import AssetReferences from '../components/data/AssetReferences.vue'
import { canRegisterAsset } from '../catalog/assetReferences'
import ConfirmDialog from '../components/common/ConfirmDialog.vue'

const props = defineProps<{
  active: boolean
  recovery: number
  layers: MapLayer[]
  backend: 'loading' | 'online' | 'offline'
  catalogError: string
  deleting: string
  revision: number
  blockedTilesAsset?: string
}>()
const emit = defineEmits<{
  add: []
  edit: [record: LayerRecord]
  registerAsset: [asset: AssetRecord]
  join: [layer: MapLayer]
  deleteRecord: [layer: MapLayer]
  refresh: []
  openScene: [scene: SceneRecord]
}>()
const tabs = ['records', 'scenes', 'assets'] as const
const tab = ref<typeof tabs[number]>('records')
const sceneCount = ref<number | null>(null)
const sceneQuery = ref('')
const sceneJump = ref(0)
const query = ref('')
const kind = ref('all')
const source = ref('all')
const status = ref('')
const sort = ref<'' | 'byte_size' | '-byte_size'>('')
const from = ref('')
const to = ref('')
const {
  assets,
  page,
  pageSize,
  total,
  stats,
  statsLoading,
  statsError,
  setQuery,
  setPage,
  loading,
  scanning,
  error,
  message,
  refresh,
  refreshStats,
  scan,
  detail,
  detailId,
  detailLoading,
  detailError,
  openDetail,
  closeDetail,
  pendingDelete,
  deleting: deletingAsset,
  deleteError,
  conflicts,
  askDelete,
  cancelDelete,
  confirmDelete,
} = useAssets()
const records = computed(() => props.layers.filter((layer) => !layer.builtin))
const filteredRecords = computed(() =>
  records.value.filter(
    (layer) =>
      (!query.value.trim() ||
        `${layer.name} ${layer.category}`
          .toLocaleLowerCase()
          .includes(query.value.trim().toLocaleLowerCase())) &&
      (kind.value === 'all' || kind.value === layer.type) &&
      (source.value === 'all' ||
        (source.value === 'local'
          ? !!layer.asset_id && layer.asset_source_kind !== 'external'
          : !layer.asset_id || layer.asset_source_kind === 'external')),
  ),
)
const filteredAssets = assets
const hasAssetFilters = computed(() => !!(query.value.trim() || kind.value !== 'all' || status.value || from.value || to.value))
let filterTimer: ReturnType<typeof setTimeout> | undefined
function applyAssetFilters() {
  const timestamp = (value: string) => {
    if (!value) return ''
    const date = new Date(value)
    return Number.isNaN(date.valueOf()) ? value : date.toISOString()
  }
  void setQuery({
    q: query.value.trim(),
    type: kind.value === 'all' ? '' : (kind.value as AssetRecord['type']),
    status: status.value as AssetRecord['status'] | '',
    sort: sort.value,
    from: timestamp(from.value),
    to: timestamp(to.value),
  })
}
watch([query, kind, status, sort, from, to], () => {
  clearTimeout(filterTimer)
  if (tab.value === 'assets') filterTimer = setTimeout(applyAssetFilters, 250)
})
let sceneCountRequest: AbortController | undefined
async function refreshSceneCount() {
  sceneCountRequest?.abort()
  const request = new AbortController()
  sceneCountRequest = request
  try {
    const result = await getScenes({ page_size: 1 }, request.signal)
    if (!request.signal.aborted) sceneCount.value = result.total
  } catch { if (!request.signal.aborted) sceneCount.value = null }
}
function sceneRemoved() {
  void refresh()
  void refreshSceneCount()
}
onBeforeUnmount(() => { clearTimeout(filterTimer); sceneCountRequest?.abort() })
const statusText: Record<AssetRecord['status'], string> = {
  active: '可用',
  deleting: '删除中',
  delete_error: '删除失败',
  missing: '文件缺失',
  unsafe: '路径不安全',
}
function bytes(value: number | null) {
  if (value === null) return '未知'
  const unit = value > 0 ? Math.min(4, Math.floor(Math.log(value) / Math.log(1024))) : 0
  return `${unit === 0 ? value : (value / 1024 ** unit).toFixed(1)} ${['B', 'KB', 'MB', 'GB', 'TB'][unit]}`
}
const count = (value: number) => value.toLocaleString('zh-CN')
const assetTypeNames: Record<string, string> = { geojson: 'GeoJSON', '3dtiles': '3D Tiles', network: '路网', unknown: '未知类型' }
const overviewMetrics = computed(() => [
  { label: '资产数量', value: stats.value ? count(stats.value.asset_count) : '—', unit: '份' },
  { label: '对象数量', value: stats.value ? count(stats.value.object_count) : '—', unit: '个' },
  { label: '运行次数', value: stats.value ? count(stats.value.run_count) : '—', unit: '次' },
  { label: '源资产容量', value: stats.value ? bytes(stats.value.total_byte_size).split(' ')[0] : '—', unit: stats.value ? bytes(stats.value.total_byte_size).split(' ')[1] : '' },
])
function date(value?: string | null) {
  if (!value) return '未知'
  const parsed = new Date(value)
  return Number.isNaN(parsed.valueOf())
    ? value
    : parsed.toLocaleString('zh-CN', { hour12: false })
}
function state(layer: MapLayer) {
  if (!layer.attached) return layer.map_attached ? '待恢复' : '未加入'
  if (layer.status === 'loading') return '加载中'
  if (layer.status === 'error') return '加载失败'
  return layer.visible ? '已加载' : '已隐藏'
}
function canRegister(asset: AssetRecord) {
  return canRegisterAsset(asset)
}
function retryDetail() {
  if (detailId.value) void openDetail(detailId.value)
}
function refreshAll() {
  emit('refresh')
  void refresh()
}
function changeTab(value: typeof tabs[number]) {
  tab.value = value
  if (value === 'records' && ['unknown', 'network'].includes(kind.value))
    kind.value = 'all'
  if (value === 'assets') applyAssetFilters()
}
function navigateTabs(event: KeyboardEvent) {
  if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return
  event.preventDefault()
  const index = tabs.indexOf(tab.value)
  const next = event.key === 'Home' ? 0 : event.key === 'End' ? tabs.length - 1
    : (index + (event.key === 'ArrowRight' ? 1 : -1) + tabs.length) % tabs.length
  changeTab(tabs[next]!)
  const buttons = (event.currentTarget as HTMLElement).querySelectorAll<HTMLButtonElement>('[role="tab"]')
  buttons[next]?.focus()
}
function showScene(id: string) {
  closeDetail()
  cancelDelete()
  sceneQuery.value = id
  sceneJump.value++
  changeTab('scenes')
}

watch(
  [() => props.active, () => props.recovery, () => props.revision],
  ([active]) => {
    if (!active) return
    void refresh()
    void refreshSceneCount()
    if (detailId.value) void openDetail(detailId.value)
  },
  { immediate: true },
)
</script>

<template>
  <main class="data-manager" aria-label="我的数据管理">
    <div class="manager-content">
      <header class="manager-header">
        <div>
          <span class="eyebrow">DATA WORKSPACE</span>
          <h1>我的数据</h1>
          <p>管理图层登记与本机保存的完整数据集，按需加入地图。</p>
        </div>
        <button class="primary-button" @click="emit('add')">
          <Upload :size="16" aria-hidden="true" />上传 / 登记数据
        </button>
      </header>
      <section class="asset-stats stats-overview" aria-label="资产统计" :aria-busy="statsLoading">
        <div class="stats-metrics">
          <div v-for="(metric, index) in overviewMetrics" :key="metric.label" class="stat-card">
            <h2>{{ metric.label }}</h2>
            <p class="stat-value"><strong>{{ metric.value }}</strong><span>{{ metric.unit }}</span></p>
            <p v-if="index === 0" class="stat-caption">{{ stats ? `近 7 天新增 ${count(stats.assets_added_last_7_days)} 份` : '近 7 天新增 — 份' }}</p>
          </div>
        </div>
        <p v-if="statsLoading" class="stats-message" role="status">正在读取综合统计…</p>
        <div v-else-if="statsError" class="stats-message stats-error" role="alert">
        <strong>{{ statsError.startsWith('无权限：') ? '无权限查看综合统计' : '综合统计加载失败' }}</strong>
        <span>{{ statsError }}</span><button class="text-button" @click="refreshStats">重试统计</button>
        </div>
        <details v-else-if="stats" class="stats-details">
          <summary>查看明细</summary>
          <div class="stats-breakdowns">
            <section><h3>资产类型</h3><dl class="type-breakdown"><div v-for="(amount, type) in stats.assets_by_type" :key="type"><dt>{{ assetTypeNames[type] ?? type }}</dt><dd>{{ count(amount) }} 份</dd></div></dl><p v-if="!Object.keys(stats.assets_by_type).length" class="stat-caption">暂无资产</p></section>
            <section class="storage-card"><h3>空间明细</h3><dl>
              <div><dt>源资产容量</dt><dd>{{ bytes(stats.total_byte_size) }}</dd></div>
              <div><dt>显示产物</dt><dd>{{ stats.storage ? bytes(stats.storage.render_bytes) : '暂不可用' }}</dd></div>
              <div><dt>数据库（含索引）</dt><dd>{{ stats.storage ? bytes(stats.storage.database_bytes) : '暂不可用' }}</dd></div>
              <div><dt>临时空间</dt><dd>{{ stats.storage ? bytes(stats.storage.temporary_bytes) : '暂不可用' }}</dd></div>
            </dl></section>
          </div>
        </details>
      </section>

      <section class="manager-surface">
        <div
          class="manager-tabs"
          role="tablist"
          aria-label="数据管理分类"
          @keydown="navigateTabs"
        >
          <button
            id="record-tab"
            role="tab"
            :aria-selected="tab === 'records'"
            :tabindex="tab === 'records' ? 0 : -1"
            aria-controls="record-panel"
            :class="{ active: tab === 'records' }"
            @click="changeTab('records')"
          >
            <Database :size="16" />图层登记<span>{{ records.length }}</span>
          </button>
          <button id="scene-tab" role="tab" :aria-selected="tab === 'scenes'" :tabindex="tab === 'scenes' ? 0 : -1"
            aria-controls="scene-panel" :class="{ active: tab === 'scenes' }" @click="changeTab('scenes')">
            <Layers :size="16" />场景<span>{{ sceneCount ?? '—' }}</span>
          </button>
          <button
            id="asset-tab"
            role="tab"
            :aria-selected="tab === 'assets'"
            :tabindex="tab === 'assets' ? 0 : -1"
            aria-controls="asset-panel"
            :class="{ active: tab === 'assets' }"
            @click="changeTab('assets')"
          >
            <FolderOpen :size="16" />资产目录<span>{{
              stats?.asset_count ?? total
            }}</span>
          </button>
        </div>
        <div v-if="tab !== 'scenes'" class="table-tools">
          <label class="search-field"
            ><span>搜索</span><Search :size="15" /><input
              v-model="query"
              aria-label="搜索数据"
              :placeholder="
                tab === 'records' ? '搜索名称或分类' : '搜索文件名称或资产 ID'
              "
          /></label>
          <label class="filter-field">类型<select v-model="kind" aria-label="筛选数据类型">
            <option value="all">全部类型</option>
            <option value="geojson">GeoJSON</option>
            <option value="3dtiles">3D Tiles</option>
            <option v-if="tab === 'assets'" value="network">路网</option>
            <option v-if="tab === 'assets'" value="unknown">未知类型</option>
          </select></label>
          <template v-if="tab === 'assets'">
            <label class="filter-field">状态<select v-model="status" aria-label="筛选资产状态">
              <option value="">全部状态</option>
              <option
                v-for="(label, value) in statusText"
                :key="value"
                :value="value"
              >
                {{ label }}
              </option>
            </select></label>
            <label class="filter-field">排序<select v-model="sort" aria-label="资产排序">
              <option value="">时间从新到旧</option>
              <option value="-byte_size">体积从大到小</option>
              <option value="byte_size">体积从小到大</option>
            </select></label>
            <label class="date-filter"
              >起始时间<input
                v-model="from"
                type="datetime-local"
                aria-label="资产起始时间"
            /></label>
            <label class="date-filter"
              >结束时间<input
                v-model="to"
                type="datetime-local"
                aria-label="资产结束时间"
            /></label>
          </template>
          <label v-if="tab === 'records'" class="filter-field">来源<select
            v-model="source"
            aria-label="筛选数据来源"
          >
            <option value="all">全部来源</option>
            <option value="local">本地文件</option>
            <option value="external">外部地址</option>
          </select></label>
          <button
            v-if="tab === 'assets'"
            class="secondary-button scan-button"
            :disabled="scanning || loading || backend !== 'online'"
            @click="scan"
          >
            <LoaderCircle v-if="scanning" :size="14" class="spin" /><Files
              v-else
              :size="14"
            />{{ scanning ? '正在扫描' : '扫描已有文件' }}
          </button>
          <button
            class="secondary-button refresh-button"
            aria-label="刷新数据列表"
            :disabled="loading || scanning"
            @click="refreshAll"
          >
            <RefreshCw :size="16" :class="{ spin: loading }" aria-hidden="true" />刷新
          </button>
        </div>
        <div
          v-if="backend === 'offline' || catalogError"
          class="notice error"
          role="alert"
        >
          {{ catalogError || '图层服务未连接，请启动后端后刷新。'
          }}<button @click="emit('refresh')">重试连接</button>
        </div>
        <div v-if="tab !== 'scenes' && error" class="notice error" role="alert">
          {{ error }}<button @click="refresh">重试文件列表</button>
        </div>
        <p v-if="tab !== 'scenes' && message" class="notice success" role="status">{{ message }}</p>

        <section
          v-if="tab === 'records'"
          id="record-panel"
          role="tabpanel"
          aria-labelledby="record-tab"
        >
          <div class="table-description">
            <span>{{ filteredRecords.length }} 条登记</span>
            <p>登记保存在本机；删除登记保留文件。</p>
          </div>
          <div
            v-if="backend === 'loading' && !records.length"
            class="empty-state"
          >
            <LoaderCircle :size="24" class="spin" /><strong
              >正在读取登记目录</strong
            >
          </div>
          <div v-else-if="!filteredRecords.length && (catalogError || backend === 'offline')" class="empty-state">
            <Database :size="32" :stroke-width="1.3" />
            <strong>{{ catalogError.startsWith('无权限：') ? '无权限查看图层登记' : '图层登记加载失败' }}</strong>
            <p>{{ catalogError || '图层服务连接中断，正在等待恢复。' }}</p>
          </div>
          <div v-else-if="!filteredRecords.length" class="empty-state">
            <Database :size="32" :stroke-width="1.3" /><strong>{{
              records.length ? '没有匹配的登记' : '还没有图层登记'
            }}</strong>
            <p>
              {{
                records.length
                  ? '调整名称、类型或来源筛选。'
                  : '上传数据或登记地址后，在这里管理并加入地图。'
              }}
            </p>
            <button
              v-if="!records.length"
              class="secondary-button"
              @click="emit('add')"
            >
              添加第一条登记
            </button>
          </div>
          <div v-else class="table-scroll" tabindex="0" aria-label="图层登记表格，可横向滚动">
            <table class="record-table">
              <thead>
                <tr>
                  <th>图层名称 / 分类</th>
                  <th>类型</th>
                  <th>数据来源</th>
                  <th>创建时间</th>
                  <th>地图状态</th>
                  <th class="actions-heading">操作</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="layer in filteredRecords" :key="layer.id">
                  <td>
                    <div class="name-cell">
                      <span class="file-icon"
                        ><component
                          :is="layer.type === 'geojson' ? FileJson : Box"
                          :size="19"
                          :stroke-width="1.5"
                      /></span>
                      <div>
                        <strong>{{ layer.name }}</strong
                        ><small>{{ layer.category }}</small>
                      </div>
                    </div>
                  </td>
                  <td class="nowrap">
                    {{ layer.type === 'geojson' ? 'GeoJSON' : '3D Tiles' }}
                  </td>
                  <td class="source-cell">
                    <span class="source-badge">{{
                      layer.asset_id && layer.asset_source_kind !== 'external'
                        ? '本地文件'
                        : '外部地址'
                    }}</span
                    ><span class="data-url" :title="layer.url">{{
                      layer.url
                    }}</span
                    ><small v-if="layer.source">{{ layer.source }}</small>
                  </td>
                  <td class="date-cell">{{ date(layer.created_at) }}</td>
                  <td>
                    <span
                      class="status"
                      :class="{
                        ready: layer.attached && layer.status === 'ready',
                        failed: layer.status === 'error',
                      }"
                      ><i></i>{{ state(layer) }}</span
                    ><small
                      v-if="layer.attached && layer.error"
                      class="row-error"
                      >{{ layer.error }}</small
                    >
                  </td>
                  <td>
                    <div class="row-actions">
                      <button class="text-button" @click="emit('join', layer)">
                        {{
                          layer.attached || layer.map_attached
                            ? '查看地图'
                            : '加入地图'
                        }}<ArrowUpRight :size="13" /></button
                      ><button class="text-button" @click="emit('edit', layer)">
                        <Pencil :size="14" aria-hidden="true" />编辑</button
                      ><button
                        class="text-button danger-text"
                        :disabled="!!deleting"
                        @click="emit('deleteRecord', layer)"
                      >
                        <Trash2 :size="14" aria-hidden="true" />{{ deleting === layer.id ? '正在删除' : '删除登记' }}
                      </button>
                    </div>
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
        </section>

        <section
          v-else-if="tab === 'assets'"
          id="asset-panel"
          role="tabpanel"
          aria-labelledby="asset-tab"
        >
          <div class="table-description">
            <span
              >共 {{ total }} 份资产，本页 {{ filteredAssets.length }} 份</span
            >
            <p>上传与扫描更新目录快照；默认文件受保护，外部地址只移除登记。</p>
          </div>
          <div v-if="loading && !assets.length" class="empty-state">
            <LoaderCircle :size="24" class="spin" /><strong
              >正在读取资产目录</strong
            >
          </div>
          <div v-else-if="error" class="empty-state">
            <FolderOpen :size="32" :stroke-width="1.3" /><strong
              >{{ error.startsWith('无权限：') ? '无权限查看资产目录' : '资产目录加载失败' }}</strong
            >
            <p>{{ error }}</p>
          </div>
          <div v-else-if="!filteredAssets.length" class="empty-state">
            <FolderOpen :size="32" :stroke-width="1.3" /><strong>{{
              stats?.asset_count || hasAssetFilters ? '没有匹配的资产' : '还没有资产'
            }}</strong>
            <p>
              {{
                stats?.asset_count || hasAssetFilters
                  ? '调整文件名称或类型筛选。'
                  : '上传数据后自动纳入管理，也可扫描历史存储目录。'
              }}
            </p>
          </div>
          <div v-else class="table-scroll" tabindex="0" aria-label="资产目录表格，可横向滚动">
            <table class="asset-table">
              <thead>
                <tr>
                  <th>文件资产 / 入口</th>
                  <th>类型</th>
                  <th>体积 / 文件数</th>
                  <th>时间</th>
                  <th>引用 / 状态</th>
                  <th class="actions-heading">操作</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="asset in filteredAssets" :key="asset.id">
                  <td class="asset-name">
                    <strong>{{
                      asset.name ||
                      asset.original_name ||
                      '历史文件 · 原始名称未知'
                    }}</strong
                    ><span
                      class="data-url"
                      :title="asset.entry_url || asset.id"
                      >{{ asset.entry_url || asset.id }}</span
                    >
                  </td>
                  <td class="nowrap">
                    {{
                      asset.type === 'geojson'
                        ? 'GeoJSON'
                        : asset.type === '3dtiles'
                          ? '3D Tiles'
                          : '未知'
                    }}
                  </td>
                  <td class="nowrap">
                    <strong class="normal-weight">{{
                      bytes(asset.byte_size)
                    }}</strong
                    ><small>{{ asset.file_count ?? '未知' }} 个文件</small>
                  </td>
                  <td class="date-cell">
                    {{ date(asset.uploaded_at || asset.discovered_at)
                    }}<small>{{
                      asset.uploaded_at ? '上传时间' : '发现时间 · 上传时间未知'
                    }}</small>
                  </td>
                  <td>
                    <button
                      class="reference-button"
                      :aria-label="`查看 ${asset.reference_count} 条引用：${asset.original_name || asset.id}`"
                      @click="openDetail(asset.id)"
                    >
                      {{ asset.reference_count }} 条引用</button
                    ><span
                      class="status"
                      :class="{
                        ready: asset.status === 'active',
                        failed: asset.status !== 'active',
                      }"
                      ><i></i>{{ statusText[asset.status] }}</span
                    ><small v-if="asset.error" class="row-error">{{
                      asset.error
                    }}</small>
                  </td>
                  <td>
                    <div class="row-actions">
                      <button class="text-button" @click="openDetail(asset.id)">
                        详情</button
                      ><button
                        v-if="canRegister(asset)"
                        class="text-button"
                        @click="emit('registerAsset', asset)"
                      >
                        登记为图层</button
                      ><button
                        class="text-button danger-text"
                        :disabled="
                          asset.reference_count > 0 ||
                          asset.protected ||
                          asset.status === 'unsafe' ||
                          deletingAsset
                        "
                        :title="
                          asset.protected
                            ? '默认资产文件受保护'
                            : asset.reference_count
                              ? '查看引用类型与解除方式；历史运行持续保护源版本'
                              : asset.status === 'unsafe'
                                ? '路径不安全，禁止删除'
                                : '永久删除整个数据集'
                        "
                        @click="askDelete(asset)"
                      >
                        <Trash2 :size="14" aria-hidden="true" />{{
                          asset.status === 'delete_error' ||
                          asset.status === 'deleting'
                            ? '重试删除'
                            : asset.source_kind === 'external'
                              ? '移除登记'
                              : '彻底删除'
                        }}
                      </button>
                    </div>
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
          <nav class="pagination" aria-label="资产分页">
            <button :disabled="loading || page <= 1" @click="setPage(page - 1)">
              上一页
            </button>
            <span
              >第 {{ page }} / {{ Math.max(1, Math.ceil(total / pageSize)) }} 页
              · 每页 {{ pageSize }} 份</span
            >
            <button
              :disabled="loading || page * pageSize >= total"
              @click="setPage(page + 1)"
            >
              下一页
            </button>
          </nav>
        </section>
        <SceneManager v-else :key="sceneJump" :initial-query="sceneQuery" :active="active" :revision="recovery"
          @open="emit('openScene', $event)" @removed="sceneRemoved" />
      </section>
      <footer class="manager-note">
        <i :class="{ online: backend === 'online' }"></i
        >{{
          backend === 'online'
            ? '本地图层服务已连接'
            : backend === 'loading'
              ? '正在连接本地图层服务'
              : '本地图层服务未连接'
        }}<span
          >自定义图层会记住地图加入状态；“从地图移除”保留登记和文件。</span
        >
      </footer>
    </div>

    <AssetDetails
      v-if="detailId"
      :asset="detail"
      :busy="detailLoading"
      :error="detailError"
      :download-blocked="!!blockedTilesAsset && blockedTilesAsset === detailId"
      @close="closeDetail"
      @retry="retryDetail"
      @scene="showScene"
    />
    <ConfirmDialog
      v-if="pendingDelete"
      :title="
        pendingDelete.source_kind === 'external'
          ? '移除外部资产登记？'
          : '彻底删除文件资产？'
      "
      :confirm-label="
        pendingDelete.source_kind === 'external' ? '移除登记' : '确认永久删除'
      "
      :busy="deletingAsset"
      :error="deleteError"
      :blocked="conflicts.length > 0"
      @close="cancelDelete"
      @confirm="confirmDelete"
    >
      <p class="delete-name">
        {{ pendingDelete.original_name || `历史文件资产 ${pendingDelete.id}` }}
      </p>
      <p v-if="pendingDelete.source_kind === 'external'">
        移除本机的资产登记，远端文件保留。
      </p>
      <p v-else>
        将永久删除整个数据集，共
        <strong>{{ pendingDelete.file_count }} 个文件</strong>，占用
        <strong>{{ bytes(pendingDelete.byte_size) }}</strong
        >。
      </p>
      <p v-if="pendingDelete.source_kind !== 'external'" class="irreversible">
        此操作不可恢复，请确认已保存需要的数据。
      </p>
      <template #error
        ><div v-if="conflicts.length" class="conflict-records">
          <p>当前引用：</p>
          <AssetReferences :references="conflicts" scene-links @scene="showScene" />
        </div></template
      >
    </ConfirmDialog>
  </main>
</template>

<style scoped>
.asset-stats {
  display: flex;
  gap: 22px;
  flex-wrap: wrap;
  margin: 0 0 18px;
  font-size: 14px;
  color: #475569;
}
.asset-stats strong {
  color: #1e293b;
  font-weight: 550;
}
.date-filter {
  display: flex;
  gap: 6px;
  align-items: center;
  font-size: 12px;
  color: #475569;
  flex-direction: column;
  align-items: flex-start;
}
.date-filter input {
  border: 1px solid #dfe6ee;
  border-radius: 5px;
  padding: 8px;
  color: inherit;
  background: white;
}
.pagination, :deep(.scene-manager .pagination) {
  display: flex;
  flex-wrap: wrap;
  gap: 16px;
  align-items: center;
  justify-content: flex-end;
  padding: 18px 24px;
  border-top: 1px solid var(--line);
  font-size: 14px;
  color: #475569;
}
.pagination button, :deep(.scene-manager .pagination button) {
  color: var(--blue);
}
.data-manager {
  position: absolute;
  inset: 64px 0 0;
  overflow-y: auto;
  overflow-x: hidden;
  color: #1e293b;
  font-size: 14px;
  background: #f5f7fa;
}
.manager-content {
  max-width: 1500px;
  margin: 0 auto;
  padding: 36px 40px 24px;
}
.manager-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 24px;
  margin-bottom: 28px;
}
h1 {
  font-size: 27px;
  font-weight: 550;
  letter-spacing: 0.3px;
  margin-top: 7px;
}
.manager-header p {
  color: #475569;
  font-size: 14px;
  line-height: 1.8;
  margin-top: 10px;
}
.manager-surface {
  background: white;
  border: 1px solid #e6ebf2;
  border-radius: 9px;
  overflow: hidden;
  box-shadow: 0 2px 9px #20395d03;
}
.manager-tabs {
  display: flex;
  gap: 24px;
  flex-wrap: wrap;
  border-bottom: 1px solid var(--line);
  padding: 0 24px;
}
.manager-tabs > button {
  height: 59px;
  gap: 8px;
  font-size: 14px;
  color: #475569;
  position: relative;
}
.manager-tabs > button.active {
  color: var(--blue);
  font-weight: 550;
}
.manager-tabs > button.active:after {
  content: '';
  position: absolute;
  inset: auto 0 0;
  height: 2px;
  background: var(--blue);
}
.manager-tabs span {
  background: #f0f3f8;
  border-radius: 4px;
  padding: 2px 6px;
  font-size: 12px;
  color: #475569;
}
.table-tools, :deep(.scene-manager .table-tools) {
  padding: 22px 24px 15px;
  display: flex;
  gap: 10px;
  flex-wrap: wrap;
  align-items: center;
}
.search-field, :deep(.scene-manager .search-field) {
  display: flex;
  align-items: center;
  gap: 9px;
  border: 1px solid #dfe6ee;
  border-radius: 5px;
  padding: 0 11px;
  width: 320px;
  max-width: 100%;
  min-width: 0;
  min-height: 40px;
  color: #475569;
}
.search-field:focus-within, :deep(.scene-manager .search-field:focus-within) {
  border-color: var(--blue);
}
.search-field input, :deep(.scene-manager .search-field input) {
  border: 0;
  outline: 0;
  min-width: 0;
  flex: 1;
  font-size: 14px;
  background: transparent;
  color: #1e293b;
}
.search-field input::placeholder, :deep(.scene-manager .search-field input::placeholder) {
  color: #475569;
}
.table-tools select {
  border: 1px solid #dfe6ee;
  background: white;
  border-radius: 5px;
  min-height: 40px;
  padding: 0 28px 0 10px;
  color: #475569;
  font-size: 14px;
}
.secondary-button, :deep(.scene-manager .secondary-button) {
  gap: 7px;
  font-size: 14px;
  border: 1px solid #dce4ee;
  border-radius: 5px;
  padding: 9px 12px;
  background: white;
  color: #475569;
  white-space: nowrap;
}
.scan-button {
  margin-left: auto;
}
.refresh-button, :deep(.scene-manager .refresh-button) {
  margin-left: auto;
}
.scan-button + .refresh-button {
  margin-left: 0;
}
.notice {
  margin: 0 24px 14px;
  border-radius: 5px;
  padding: 10px 13px;
  font-size: 14px;
  line-height: 1.8;
}
.notice.error {
  background: #fff3f1;
  color: #b64d46;
}
.notice.success {
  background: #eff8f3;
  color: #428469;
}
.notice button {
  margin-left: 12px;
  text-decoration: underline;
}
.table-description, :deep(.scene-manager .table-description) {
  display: flex;
  gap: 20px;
  justify-content: space-between;
  align-items: baseline;
  padding: 0 24px 17px;
  font-size: 12px;
  color: #475569;
}
.table-description > span, :deep(.scene-manager .table-description > span) {
  color: #475569;
}
.table-description > p, :deep(.scene-manager .table-description > p) {
  text-align: right;
  line-height: 1.7;
}
.table-scroll {
  max-width: 100%;
  overflow-x: auto;
}
table {
  width: 100%;
  border-collapse: collapse;
  font-size: 14px;
}
th {
  background: #f8fafd;
  font-size: 14px;
  color: #475569;
  font-weight: 500;
  text-align: left;
  padding: 13px 18px;
  border-top: 1px solid var(--line);
  border-bottom: 1px solid var(--line);
  white-space: nowrap;
}
td {
  padding: 20px 18px;
  border-bottom: 1px solid var(--line);
  vertical-align: middle;
  color: #475569;
}
th:first-child,
td:first-child {
  padding-left: 24px;
}
th:last-child,
td:last-child {
  padding-right: 24px;
}
tbody tr:last-child td {
  border-bottom: 0;
}
tbody tr:hover {
  background: #fbfcfe;
}
td strong {
  display: block;
  color: #1e293b;
  font-size: 14px;
  font-weight: 500;
  overflow-wrap: anywhere;
}
td small {
  display: block;
  color: #475569;
  font-size: 12px;
  margin-top: 6px;
  line-height: 1.6;
}
.name-cell {
  display: flex;
  align-items: center;
  gap: 11px;
  min-width: 155px;
}
.file-icon {
  display: grid;
  place-items: center;
  width: 36px;
  height: 40px;
  border-radius: 6px;
  background: #f0f5ff;
  color: #6d91cb;
  flex-shrink: 0;
}
.source-cell {
  min-width: 180px;
  max-width: 300px;
}
.source-badge {
  color: #475569;
  font-size: 12px;
  background: #f0f4f8;
  padding: 2px 5px;
  border-radius: 3px;
}
.data-url {
  font-size: 12px;
  display: block;
  margin-top: 7px;
  max-width: 260px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: #475569;
}
.date-cell {
  min-width: 140px;
  font-size: 12px;
  line-height: 1.7;
  color: #475569;
}
.nowrap {
  white-space: nowrap;
}
.status {
  font-size: 12px;
  color: #475569;
  display: inline-flex;
  align-items: center;
  gap: 5px;
  white-space: nowrap;
}
.status i,
.manager-note > i {
  width: 5px;
  height: 5px;
  border-radius: 50%;
  background: #a8b3c1;
}
.status.ready {
  color: #187351;
}
.status.ready i {
  background: #69a68f;
}
.status.failed {
  color: #b42318;
}
.status.failed i {
  background: #cd7b6c;
}
.row-error {
  max-width: 150px;
  overflow-wrap: anywhere;
  color: #b42318;
}
.row-actions {
  display: flex;
  gap: 13px;
  justify-content: flex-end;
  flex-wrap: wrap;
  min-width: 173px;
}
.text-button {
  font-size: 12px;
  color: #1d4ed8;
  padding: 4px 0;
  gap: 3px;
  white-space: nowrap;
}
.danger-text {
  color: #b42318;
}
.danger-text:hover:not(:disabled) {
  color: #b63e36;
}
.actions-heading {
  text-align: right;
}
.asset-name {
  min-width: 220px;
}
.asset-name strong {
  font-size: 14px;
  max-width: 270px;
}
.normal-weight {
  font-size: 14px;
  font-weight: 400;
}
.reference-button {
  display: block;
  font-size: 12px;
  color: #1d4ed8;
  padding: 0;
  margin-bottom: 7px;
  white-space: nowrap;
}
.empty-state, :deep(.scene-manager .empty-state) {
  min-height: 300px;
  padding: 45px 20px;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-direction: column;
  gap: 15px;
  color: #475569;
}
.empty-state strong, :deep(.scene-manager .empty-state strong) {
  color: #475569;
  font-size: 14px;
  font-weight: 500;
}
.empty-state p, :deep(.scene-manager .empty-state p) {
  font-size: 14px;
  color: #475569;
  line-height: 1.8;
  text-align: center;
}
.manager-note {
  display: flex;
  align-items: center;
  gap: 7px;
  font-size: 12px;
  color: #475569;
  margin-top: 18px;
  line-height: 1.8;
}
.manager-note > i.online {
  background: #61a18c;
}
.manager-note > span {
  margin-left: auto;
  text-align: right;
}
.delete-name {
  color: #1e293b;
  font-weight: 550;
  margin-bottom: 10px;
}
.irreversible {
  margin-top: 10px;
  color: #b45e54;
  font-size: 14px;
}
.conflict-records {
  margin-top: 8px;
  font-size: 12px;
}
.conflict-records ul {
  padding-left: 18px;
  margin: 6px 0 0;
}
@media (max-width: 900px) {
  .manager-content {
    padding: 25px 20px;
  }
  .manager-header {
    align-items: flex-start;
  }
  .manager-header p {
    max-width: 360px;
  }
  .search-field, :deep(.scene-manager .search-field) {
    width: 240px;
  }
  .table-tools, :deep(.scene-manager .table-tools) {
    gap: 8px;
  }
  .manager-note > span {
    max-width: 55%;
  }
}
@media (max-width: 600px) {
  .data-manager {
    top: 58px;
  }
  .manager-content {
    padding: 24px 12px;
  }
  .manager-header {
    flex-direction: column;
    gap: 16px;
    margin-bottom: 20px;
  }
  h1 {
    font-size: 24px;
  }
  .manager-tabs {
    padding: 0 16px;
    gap: 12px;
  }
  .table-tools, :deep(.scene-manager .table-tools) {
    padding: 16px;
  }
  .search-field, :deep(.scene-manager .search-field) {
    width: 100%;
  }
  .table-tools select {
    flex: 1;
    padding-right: 20px;
  }
  .scan-button {
    margin-left: 0;
  }
  .table-description, :deep(.scene-manager .table-description) {
    padding: 0 16px 13px;
    flex-direction: column;
    gap: 6px;
  }
  .table-description > p, :deep(.scene-manager .table-description > p) {
    text-align: left;
  }
  .notice {
    margin-left: 16px;
    margin-right: 16px;
  }
  .manager-note {
    flex-wrap: wrap;
  }
  .manager-note > span {
    margin-left: 0;
    max-width: 100%;
    text-align: left;
    width: 100%;
  }
}

.stats-overview {
  display: block;
  background: #fff;
  border: 1px solid var(--line);
  border-radius: 9px;
  overflow: hidden;
}
.stats-metrics { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); }
.stat-card {
  min-width: 0;
  padding: 20px 24px;
  overflow-wrap: anywhere;
}
.stat-card + .stat-card { border-left: 1px solid var(--line); }
.stat-card h2 { margin: 0; font-size: 14px; color: #475569; font-weight: 500; }
.stat-value { display: flex; flex-wrap: wrap; align-items: baseline; gap: 8px; margin: 8px 0 0; }
.stat-value strong { font-size: 28px; font-weight: 600; line-height: 1.3; font-variant-numeric: tabular-nums; }
.stat-value > span { font-size: 12px; color: #475569; }
.stat-caption { min-height: 20px; margin: 8px 0 0; font-size: 12px; line-height: 1.7; color: #475569; }
.stats-details, .stats-message { border-top: 1px solid var(--line); padding: 12px 24px; }
.stats-details > summary { width: fit-content; cursor: pointer; font-size: 14px; color: var(--blue); line-height: 24px; }
.stats-details > summary:focus-visible { outline: 2px solid var(--blue); outline-offset: 3px; }
.stats-breakdowns { display: grid; grid-template-columns: 1fr 1fr; gap: 24px; padding-top: 16px; }
.stats-breakdowns h3 { margin: 0; font-size: 14px; }
.stats-breakdowns dl { display: grid; gap: 12px; margin: 12px 0 0; }
.stats-breakdowns dl > div { display: flex; justify-content: space-between; gap: 12px; }
.stats-breakdowns dt { color: #475569; font-size: 12px; }
.stats-breakdowns dd { margin: 0; color: #1e293b; font-size: 14px; font-variant-numeric: tabular-nums; }
.stats-message { margin: 0; display: flex; flex-wrap: wrap; align-items: center; gap: 8px; font-size: 12px; min-height: 49px; }
.stats-error { color: #b42318; }
.filter-field { display: flex; flex-direction: column; gap: 6px; font-size: 12px; color: #475569; min-width: 0; }
.date-filter input { min-width: 0; max-width: 100%; font-size: 14px; }
.table-tools { align-items: flex-end; }
.search-field { align-self: flex-end; }
.search-field > span { font-size: 12px; color: #475569; }
.table-tools > button { min-height: 40px; }
.text-button { min-height: 36px; font-size: 14px; }
.table-tools input, .table-tools select { color: #1e293b; }
.manager-content, .manager-surface { min-width: 0; }
button, tbody tr { transition: background-color 150ms ease, color 150ms ease; }
@media (max-width: 1023px) {
  .stats-metrics { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .stat-card:nth-child(3) { border-left: 0; }
  .stat-card:nth-child(n+3) { border-top: 1px solid var(--line); }
}
@media (max-width: 600px) {
  .stat-card { padding: 16px; }
  .stat-value strong { font-size: 24px; }
  .stats-details, .stats-message { padding: 12px 16px; }
  .stats-breakdowns { grid-template-columns: minmax(0, 1fr); gap: 24px; }
  .filter-field { flex: 1 1 120px; }
  .date-filter { flex: 1 1 220px; }
  .date-filter input { width: 100%; }
  .manager-tabs > button { font-size: 14px; }
}
</style>
