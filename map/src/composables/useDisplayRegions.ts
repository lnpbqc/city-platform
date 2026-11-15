import { ref, shallowRef, watch } from 'vue'
import { deleteDisplayRegion, getDisplayRegions, saveDisplayRegion } from '../api/api.ts'
import type { DisplayRegion, DisplayRegionView } from '../map/displayRegions.ts'

const regions = shallowRef<DisplayRegion[] | null>(null)
const loading = ref(false)
const loadError = ref('')
let refreshPending: Promise<void> | undefined
let revision = 0

function refresh() {
  if (refreshPending) return refreshPending
  loading.value = true
  loadError.value = ''
  const started = revision
  refreshPending = getDisplayRegions().then(rows => {
    if (revision === started) regions.value = rows
  }).catch(() => {
    loadError.value = '展示区域加载失败'
  }).finally(() => {
    loading.value = false
    refreshPending = undefined
  })
  return refreshPending
}

async function save(body: { name: string } | DisplayRegionView | (DisplayRegionView & { name: string }), id?: string) {
  await refreshPending
  const region = await saveDisplayRegion(body, id)
  revision++
  const rows = regions.value ?? []
  regions.value = id ? rows.map(row => row.id === id ? region : row) : [...rows, region]
}

async function remove(id: string) {
  await refreshPending
  await deleteDisplayRegion(id)
  revision++
  regions.value = regions.value?.filter(region => region.id !== id) ?? null
}

export function useDisplayRegions(active: () => boolean, recovery: () => number | undefined) {
  watch(active, value => { if (value) void refresh() }, { immediate: true })
  watch(recovery, () => { if (active() && loadError.value) void refresh() })
  return { regions, loading, loadError, refresh, save, remove }
}
