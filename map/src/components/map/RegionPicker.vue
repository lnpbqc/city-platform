<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, ref, shallowRef, useId } from 'vue'
import {
  MapPin,
  ChevronDown,
  X,
  Search,
  Globe2,
  LocateFixed,
  LoaderCircle,
} from '@lucide/vue'
import {
  chinaRegion,
  createRegionIndex,
  type RegionCatalog,
  type RegionIndex,
  type RegionTarget,
} from '../../map/regions'
import type { BoundaryState } from '../../map/regionBoundary'

const props = defineProps<{
  selected: RegionTarget
  sidebar: boolean
  boundaryState: BoundaryState
  displayLabel?: string
}>()
const boundaryEnabled = defineModel<boolean>('boundaryEnabled', {
  required: true,
})
const emit = defineEmits<{
  select: [region: RegionTarget]
  retryBoundary: []
  open: []
  'update:open': [value: boolean]
}>()
const open = ref(false)
const activeTab = ref<'display' | 'administrative'>('display')
const tabId = useId()
const trigger = ref<HTMLButtonElement>()
const displayTab = ref<HTMLButtonElement>()
const administrativeTab = ref<HTMLButtonElement>()
const query = ref('')
const province = ref('')
const city = ref('')
const district = ref('')
const catalog = ref<RegionCatalog>()
const loading = ref(false)
const error = ref('')
const index = shallowRef<RegionIndex>()
let abort: AbortController | undefined
const provinces = computed(() => index.value?.children('100000') ?? [])
const cities = computed(
  () =>
    index.value
      ?.children(province.value)
      .filter((region) => region.level === 'city') ?? [],
)
const districts = computed(
  () =>
    index.value
      ?.children(city.value || province.value)
      .filter((region) => region.level === 'district') ?? [],
)
const results = computed(() => index.value?.search(query.value) ?? [])
const chosen = computed(() => district.value || city.value || province.value)
const pathLabel = (id: string) => index.value?.target(id).label ?? ''

function synchronize() {
  const path = index.value?.path(props.selected.id) ?? []
  province.value = path.find((region) => region.level === 'province')?.id ?? ''
  city.value = path.find((region) => region.level === 'city')?.id ?? ''
  district.value = path.find((region) => region.level === 'district')?.id ?? ''
}
async function loadCatalog() {
  if (loading.value || catalog.value) return
  loading.value = true
  error.value = ''
  abort = new AbortController()
  try {
    const response = await fetch('/data/regions.json', { signal: abort.signal })
    if (!response.ok) throw new Error(`HTTP ${response.status}`)
    const data: RegionCatalog = await response.json()
    if (!Array.isArray(data.regions)) throw new Error('地区目录格式无效')
    index.value = createRegionIndex(data.regions)
    catalog.value = data
    synchronize()
  } catch (cause) {
    if (!abort.signal.aborted)
      error.value = `地区目录加载失败：${cause instanceof Error ? cause.message : '未知错误'}`
  } finally {
    loading.value = false
  }
}
function activateTab(tab: typeof activeTab.value) {
  activeTab.value = tab
  if (tab === 'administrative' && !error.value) void loadCatalog()
  void nextTick(() => (tab === 'display' ? displayTab.value : administrativeTab.value)?.focus())
}
function navigateTabs(event: KeyboardEvent) {
  const next = event.key === 'Home' ? 'display'
    : event.key === 'End' ? 'administrative'
    : event.key === 'ArrowLeft' || event.key === 'ArrowRight'
      ? (activeTab.value === 'display' ? 'administrative' : 'display') : undefined
  if (!next) return
  event.preventDefault()
  activateTab(next)
}
function toggle() {
  if (open.value) { close(); return }
  open.value = true
  emit('update:open', true)
  query.value = ''
  synchronize()
  activateTab('display')
  emit('open')
}
function choose(target: RegionTarget) {
  emit('select', target)
  close()
}
function close() {
  if (!open.value) return
  open.value = false
  emit('update:open', false)
  void nextTick(() => trigger.value?.focus())
}
function locate(id: string) {
  if (index.value) choose(index.value.target(id))
}
function changeProvince() {
  city.value = ''
  district.value = ''
}
function changeCity() {
  district.value = ''
}
onBeforeUnmount(() => abort?.abort())
</script>

<template>
  <div
    class="region-picker"
    :class="{ shifted: sidebar }"
    @keydown.esc="close"
  >
    <div class="region-head"><button
      ref="trigger"
      class="region-trigger panel"
      :aria-expanded="open"
      aria-controls="region-options"
      aria-label="选择中国城市和地区"
      @click="toggle"
    >
      <MapPin :size="14" /><span class="region-label">{{ displayLabel ?? selected.label }}</span
      ><span class="region-crs">WGS84</span><ChevronDown :size="13" />
    </button>
    <slot name="bookmarks" /></div>
    <div v-if="!displayLabel && !selected.id.startsWith('demo-')" class="boundary-control panel">
      <label
        ><input
          v-model="boundaryEnabled"
          type="checkbox"
          aria-label="显示行政区边界"
        />边界高亮</label
      >
      <span v-if="boundaryState.status === 'loading'" role="status"
        ><LoaderCircle :size="12" class="spin" />加载中…</span
      >
      <span
        v-else-if="boundaryState.status === 'error'"
        class="boundary-error"
        role="alert"
        :title="boundaryState.error"
        >加载失败 <button @click="emit('retryBoundary')">重试边界</button></span
      >
      <span v-else role="status">{{
        boundaryState.status === 'ready' ? '已显示' : '已关闭'
      }}</span>
    </div>
    <section
      v-if="open"
      id="region-options"
      class="region-menu panel"
      aria-label="地区定位选择器"
    >
      <header>
        <h2>选择城市与地区</h2>
        <button
          class="icon-button"
          aria-label="关闭地区选择"
          @click="close"
        >
          <X :size="16" />
        </button>
      </header>
      <div class="region-tabs" role="tablist" aria-label="地区定位方式" @keydown="navigateTabs">
        <button ref="displayTab" :id="`${tabId}-display-tab`" type="button" role="tab"
          :aria-selected="activeTab === 'display'" :aria-controls="`${tabId}-display-panel`"
          :tabindex="activeTab === 'display' ? 0 : -1" @click="activateTab('display')">展示区域</button>
        <button ref="administrativeTab" :id="`${tabId}-administrative-tab`" type="button" role="tab"
          :aria-selected="activeTab === 'administrative'" :aria-controls="`${tabId}-administrative-panel`"
          :tabindex="activeTab === 'administrative' ? 0 : -1" @click="activateTab('administrative')">行政区定位</button>
      </div>
      <div v-show="activeTab === 'display'" :id="`${tabId}-display-panel`" class="region-tab-panel"
        role="tabpanel" :aria-labelledby="`${tabId}-display-tab`">
        <slot name="display-regions" :close="close" />
      </div>
      <div v-show="activeTab === 'administrative'" :id="`${tabId}-administrative-panel`"
        class="region-tab-panel region-administrative map-panel-scroll" role="tabpanel"
        :aria-labelledby="`${tabId}-administrative-tab`" tabindex="0">
        <div class="quick-regions">
          <button type="button" @click="choose(chinaRegion)"><Globe2 :size="14" />全国概览</button>
        </div>
        <p v-if="loading" class="region-message" role="status">
          <LoaderCircle :size="15" class="spin" />正在读取本地地区目录…
        </p>
        <div v-else-if="error" class="region-error" role="alert">
          {{ error }}<button @click="loadCatalog">重新加载</button>
        </div>
        <template v-else-if="catalog">
          <label class="region-search"
            ><Search :size="15" /><input
              v-model="query"
              aria-label="搜索中国地区"
              placeholder="搜索省、市、区县或行政代码" /><button
              v-if="query"
              class="icon-button"
              aria-label="清空地区搜索"
              @click="query = ''"
            >
              <X :size="13" /></button
          ></label>
          <div v-if="query.trim()" class="region-results">
            <p>
              {{
                results.length
                  ? `找到 ${results.length} 个地区${results.length > 20 ? '，显示前 20 个' : ''}`
                  : '未找到匹配地区'
              }}
            </p>
            <button
              v-for="region in results.slice(0, 20)"
              :key="region.id"
              @click="locate(region.id)"
            >
              <span>{{ pathLabel(region.id) }}</span
              ><small>{{ region.id }}</small>
            </button>
          </div>
          <form v-else class="region-form" @submit.prevent="locate(chosen)">
            <label
              >省 / 自治区 / 直辖市 / 特别行政区<select
                v-model="province"
                aria-label="选择省级地区"
                @change="changeProvince"
              >
                <option value="">请选择省级地区</option>
                <option
                  v-for="region in provinces"
                  :key="region.id"
                  :value="region.id"
                >
                  {{ region.name }}
                </option>
              </select></label
            >
            <div class="region-grid">
              <label
                >城市<select
                  v-model="city"
                  aria-label="选择城市"
                  :disabled="!cities.length"
                  @change="changeCity"
                >
                  <option value="">
                    {{
                      !province
                        ? '请先选省级地区'
                        : cities.length
                          ? '全省 / 省直管地区'
                          : '无市级目录'
                    }}
                  </option>
                  <option
                    v-for="region in cities"
                    :key="region.id"
                    :value="region.id"
                  >
                    {{ region.name }}
                  </option>
                </select></label
              >
              <label
                >区 / 县<select
                  v-model="district"
                  aria-label="选择区县"
                  :disabled="!districts.length"
                >
                  <option value="">
                    {{ districts.length ? '全部 / 不限' : '暂无区县目录' }}
                  </option>
                  <option
                    v-for="region in districts"
                    :key="region.id"
                    :value="region.id"
                  >
                    {{ region.name }}
                  </option>
                </select></label
              >
            </div>
            <p
              v-if="province && !cities.length && !districts.length"
              class="region-message"
            >
              来源未提供该地区的下级目录，可定位当前地区。
            </p>
            <button
              class="primary-button region-locate"
              type="submit"
              :disabled="!chosen"
            >
              <LocateFixed :size="15" />定位所选地区
            </button>
          </form>
          <footer>
            目录：DataV GeoAtlas ·
            {{ catalog.retrievedAt.slice(0, 10) }}
            快照<br />边界：DataV GeoAtlas · 联网按需加载，近似转换至
            WGS84，仅用于定位参考。校区快捷入口切换公开轮廓白模，不显示行政边界；用户数据保持原位置。
          </footer>
        </template>
      </div>
    </section>
  </div>
</template>

<style scoped>
.region-picker {
  --region-left: 78px;
  position: absolute;
  z-index: 4;
  top: 84px;
  left: var(--region-left);
  max-width: calc(100% - 160px);
  transition: left 0.25s;
}
.region-picker.shifted {
  --region-left: 344px;
  max-width: calc(100% - 420px);
}
.region-trigger {
  display: flex;
  align-items: center;
  gap: 9px;
  height: 36px;
  padding: 0 12px;
  font-size: 10px;
  max-width: 100%;
}
.region-head { display: flex; align-items: flex-start; gap: 8px; }
.region-trigger > svg:first-child {
  color: var(--blue);
}
.boundary-control {
  display: flex;
  align-items: center;
  gap: 16px;
  width: fit-content;
  max-width: 100%;
  margin-top: 6px;
  padding: 8px 12px;
  font-size: 10px;
  color: #8291a5;
}
.boundary-control label,
.boundary-control span {
  display: flex;
  align-items: center;
  gap: 6px;
}
.boundary-control label {
  color: #425874;
  cursor: pointer;
}
.boundary-control input {
  margin: 0;
  accent-color: var(--blue);
}
.boundary-control label::after {
  content: '';
  width: 16px;
  border-top: 3px solid #38bdff;
}
.boundary-error {
  color: #be665b;
}
.boundary-error button {
  color: var(--blue);
}
.region-label {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.region-crs {
  border-left: 1px solid #dce2eb;
  padding-left: 9px;
  color: #99a4b3;
}
.region-menu {
  display: flex;
  flex-direction: column;
  width: min(360px, calc(100vw - var(--region-left) - 12px));
  margin-top: 8px;
  max-height: calc(100svh - 190px);
  overflow: hidden;
  animation: panel-in 0.2s ease-out;
}
.region-menu header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex: none;
  padding: 10px 14px 6px;
}
.region-menu h2 {
  font-size: 14px;
  font-weight: 550;
}
.region-tabs {
  flex: none;
  display: flex;
  gap: 4px;
  padding: 0 14px 8px;
  border-bottom: 1px solid var(--line);
}
.region-tabs button {
  flex: 1 1 0;
  min-height: 34px;
  padding: 4px 8px;
  border-radius: 5px;
  color: #53657e;
  font-size: 12px;
}
.region-tabs [aria-selected='true'] {
  background: #edf3fc;
  color: var(--blue);
  font-weight: 600;
}
.region-tab-panel { display: flex; flex-direction: column; min-height: 0; min-width: 0; }
.region-administrative { display: block; padding: 12px 14px; }
.region-administrative:focus-visible { outline: 2px solid var(--blue); outline-offset: -2px; }
.quick-regions {
  display: flex;
  flex-wrap: wrap;
  gap: 9px;
}
.quick-regions button {
  font-size: 11px;
  gap: 6px;
  background: #f2f6fc;
  padding: 7px 10px;
  border-radius: 5px;
  color: #425874;
}
.region-search {
  display: flex;
  align-items: center;
  gap: 8px;
  height: 35px;
  background: #f6f8fb;
  border: 1px solid #edf0f4;
  border-radius: 5px;
  padding: 0 9px;
  margin: 12px 0;
  color: #94a2b5;
}
.region-search input {
  min-width: 0;
  width: 100%;
  border: 0;
  background: none;
  outline: none;
  font-size: 12px;
  color: #34455b;
}
.region-search:focus-within {
  border-color: #b9d0fa;
}
.region-search .icon-button {
  height: 21px;
  width: 21px;
}
.region-form {
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.region-form label {
  display: flex;
  flex-direction: column;
  gap: 7px;
  font-size: 11px;
  color: #53657e;
  min-width: 0;
}
.region-form select {
  height: 34px;
  width: 100%;
  min-width: 0;
  border: 1px solid #dde5ef;
  border-radius: 5px;
  padding: 0 7px;
  background: white;
  color: #3f526b;
  font-size: 12px;
}
.region-form select:disabled {
  color: #a6b0bd;
  background: #f8f9fb;
}
.region-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 12px;
}
.region-locate {
  align-self: flex-end;
  margin-top: 2px;
}
.region-menu footer {
  margin-top: 16px;
  padding-top: 11px;
  border-top: 1px solid var(--line);
  font-size: 10px;
  color: #687994;
  line-height: 1.6;
}
.region-results > p,
.region-message {
  font-size: 10px;
  color: #94a2b5;
  line-height: 1.8;
  margin-bottom: 9px;
}
.region-message {
  display: flex;
  align-items: center;
  gap: 7px;
  margin-top: 14px;
}
.region-results > button {
  width: 100%;
  text-align: left;
  justify-content: space-between;
  gap: 15px;
  padding: 11px 3px;
  border-bottom: 1px solid #f0f3f7;
  font-size: 11px;
}
.region-results > button span { min-width: 0; overflow-wrap: anywhere; }
.region-results > button:focus-visible { outline-offset: -1px; }
.region-results small {
  color: #a1acbb;
  font-size: 9px;
}
.region-error {
  color: #be665b;
  font-size: 11px;
  line-height: 1.8;
  padding-top: 12px;
}
.region-error button {
  display: block;
  color: var(--blue);
  padding: 8px 0;
}
@media (min-width: 1500px) {
  .region-picker.shifted {
    --region-left: 358px;
  }
}
@media (max-width: 900px) {
  .region-picker {
    top: 76px;
    --region-left: 64px;
  }
  .region-picker.shifted {
    --region-left: 304px;
    max-width: calc(100% - 370px);
  }
}
@media (max-width: 600px) {
  .region-picker,
  .region-picker.shifted {
    top: 76px;
    left: auto;
    right: 64px;
    max-width: calc(100% - 88px);
  }
  .region-picker.shifted .region-label {
    max-width: 90px;
  }
  .region-crs {
    display: none;
  }
  .region-menu {
    position: fixed;
    top: 115px;
    left: 12px;
    width: calc(100% - 24px);
    max-height: calc(100svh - 127px);
  }
}
@media (pointer: coarse) {
  .region-tabs button, .region-menu .icon-button, .quick-regions button, .region-form select { min-height: 44px; }
  .region-search { height: 44px; }
  .region-search .icon-button { min-height: 36px; width: 36px; }
}
</style>
