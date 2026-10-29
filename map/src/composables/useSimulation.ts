import { computed, onBeforeUnmount, ref, shallowRef, watch } from 'vue'
import { ApiError, cancelRun, getNetwork, getNetworks, getRun, getRunInput, getRunResult, getScene, getScenes, saveScene, submitRun, rerunRun } from '../api.ts'
import type { CameraState } from '../mapNavigation'
import type { Page } from '../types'
import type { NetworkRecord, RunInput, RunRecord, RunResult, RunSnapshot, SceneInput, SceneLayerState, SceneRecord } from '../simulationTypes'

const storageKey = 'city.simulation.scene.v1'
const copy = <T>(value: T): T => JSON.parse(JSON.stringify(value))
const failure = (cause: unknown) => cause instanceof Error ? cause.message : '仿真请求失败'

export function useSimulation(getCamera: () => CameraState, getLayers: () => SceneLayerState[]) {
  const scenes = shallowRef<SceneRecord[]>([])
  const networks = shallowRef<NetworkRecord[]>([])
  const makeDraft = (): SceneInput => ({ name: '未命名场景', camera: copy(getCamera()), layers: copy(getLayers()),
    network: null, origin: 'S', destination: 'T', blocked_edges: [], params: { mode: 'car' }, seed: 0, current_time: null, run_id: null })
  const draft = ref<SceneInput>(makeDraft())
  const initialDraft = JSON.stringify(draft.value)
  const sceneId = ref('')
  const sceneVersion = ref<number | null>(null)
  const historical = ref(false)
  const network = computed(() => networks.value.find(item => item.asset_id === draft.value.network?.asset_id && item.version === draft.value.network.version) ?? null)
  const run = shallowRef<RunRecord | null>(null)
  const result = shallowRef<RunResult | null>(null)
  const snapshot = shallowRef<RunSnapshot | null>(null)
  const resultNetwork = shallowRef<NetworkRecord | null>(null)
  const loading = ref(false)
  const saving = ref(false)
  const submitting = ref(false)
  const cancelling = ref(false)
  const recovering = ref(false)
  const recoveryError = ref('')
  const error = ref('')
  const pending = shallowRef<{ kind: 'submit'; key: string; body: RunInput } | { kind: 'rerun'; key: string; source_id: string } | null>(null)
  const submissionPending = computed(() => pending.value !== null)
  const busy = computed(() => run.value?.status === 'queued' || run.value?.status === 'running')
  const editingLocked = computed(() => historical.value || busy.value || saving.value || submitting.value || submissionPending.value)
  let alive = true
  let initialized = false
  let initializationError = ''
  let scopeVersion = 0
  let viewVersion = 0
  let runVersion = 0
  let viewAbort: AbortController | undefined
  let runAbort: AbortController | undefined
  let postAbort: AbortController | undefined
  let restoringView = false
  let catalogVersion = 0
  let catalogAbort: AbortController | undefined
  const configuration = () => JSON.stringify([draft.value.network, draft.value.origin, draft.value.destination, draft.value.blocked_edges, draft.value.params, draft.value.seed])
  let acceptedConfiguration: string | undefined
  let timer: ReturnType<typeof setTimeout> | undefined

  function remember(id: string) {
    try {
      if (typeof window === 'undefined') return
      if (id) window.localStorage.setItem(storageKey, id)
      else window.localStorage.removeItem(storageKey)
    } catch { /* Storage can be unavailable in private browsing. */ }
  }
  function stopRunRead() {
    clearTimeout(timer)
    timer = undefined
    ++runVersion
    runAbort?.abort()
  }
  function clearRun() {
    stopRunRead()
    run.value = null
    result.value = null
    snapshot.value = null
    resultNetwork.value = null
  }
  function beginView(changeScope = false) {
    ++catalogVersion; catalogAbort?.abort(); recovering.value = false
    ++viewVersion
    viewAbort?.abort()
    viewAbort = new AbortController()
    if (changeScope) { ++scopeVersion; stopRunRead(); cancelling.value = false }
    return { version: viewVersion, scope: scopeVersion, signal: viewAbort.signal }
  }
  const currentView = (version: number, scope: number) => alive && version === viewVersion && scope === scopeVersion
  const currentRun = (version: number, scope: number) => alive && version === runVersion && scope === scopeVersion
  function rejectEdit(allowHistorical = false) {
    if (!busy.value && !saving.value && !submitting.value && !submissionPending.value && (allowHistorical || !historical.value)) return false
    error.value = submissionPending.value ? '提交结果尚未确认，请先重试原提交，暂不能编辑配置。'
      : historical.value && !allowHistorical ? '当前显示历史快照，请先从历史编辑。' : '运行或保存正在进行，暂不能编辑配置。'
    return true
  }
  function rejectRestore() {
    if (!saving.value && !submitting.value && !submissionPending.value) return false
    error.value = submissionPending.value ? '提交结果尚未确认，请先重试原提交，暂不能打开其他画面。' : '保存或提交正在进行，请稍后打开画面。'
    return true
  }
  function addNetwork(value: NetworkRecord) {
    networks.value = [...networks.value.filter(item => item.asset_id !== value.asset_id || item.version !== value.version), value]
  }
  function inputOf(record: SceneRecord): SceneInput {
    const { id: _id, version: _version, created_at: _created, updated_at: _updated, ...body } = record
    return copy(body)
  }
  function acceptScene(record: SceneRecord) {
    historical.value = false
    sceneId.value = record.id
    sceneVersion.value = record.version
    draft.value = inputOf(record)
    acceptedConfiguration = configuration()
    scenes.value = [record, ...scenes.value.filter(item => item.id !== record.id)]
    remember(record.id)
  }
  async function allPages<T>(fetchPage: (query: { page: number; page_size: number }, signal: AbortSignal) => Promise<Page<T>>, signal: AbortSignal) {
    const items: T[] = []
    for (let page = 1, total = 1; items.length < total; page++) {
      const response = await fetchPage({ page, page_size: 100 }, signal)
      total = response.total
      items.push(...response.items)
      if (!response.items.length || signal.aborted) break
    }
    return items
  }
  function useNetwork(value: NetworkRecord) {
    draft.value.network = { asset_id: value.asset_id, version: value.version }
    const nodes = new Set(value.nodes.map(item => item.id))
    if (!draft.value.origin || !nodes.has(draft.value.origin)) draft.value.origin = nodes.has('S') ? 'S' : value.nodes[0]?.id ?? null
    if (!draft.value.destination || !nodes.has(draft.value.destination)) draft.value.destination = nodes.has('T') ? 'T' : value.nodes.at(-1)?.id ?? null
    draft.value.blocked_edges = []
  }
  async function initialize() {
    if (!alive || rejectEdit()) return
    const operation = beginView()
    loading.value = true
    error.value = ''
    const untouched = !initialized && !sceneId.value && JSON.stringify(draft.value) === initialDraft
    try {
      const [savedScenes, savedNetworks] = await Promise.all([allPages(getScenes, operation.signal), allPages(getNetworks, operation.signal)])
      if (!currentView(operation.version, operation.scope)) return
      scenes.value = savedScenes
      networks.value = savedNetworks
      const captureInitial = untouched && JSON.stringify(draft.value) === initialDraft
      let previous: string | null = null
      if (captureInitial) {
        try { previous = typeof window === 'undefined' ? null : window.localStorage.getItem(storageKey) } catch { /* Local storage is optional. */ }
      }
      initialized = true
      if (previous) await chooseScene(previous, undefined, false, initialDraft)
      else if (captureInitial) {
        draft.value.layers = copy(getLayers()); draft.value.camera = copy(getCamera())
        if (!draft.value.network) {
          const preferred = savedNetworks.find(item => item.asset_id === 'net-001') ?? savedNetworks[0]
          if (preferred) useNetwork(preferred)
        }
      }
    } catch (cause) {
      if (currentView(operation.version, operation.scope)) { error.value = failure(cause); initializationError = error.value }
    } finally {
      if (currentView(operation.version, operation.scope)) loading.value = false
    }
  }
  async function refreshCatalogs() {
    if (!alive || loading.value || saving.value || submitting.value || restoringView || cancelling.value) return false
    const version = ++catalogVersion, view = viewVersion, scope = scopeVersion
    catalogAbort?.abort()
    catalogAbort = new AbortController()
    recovering.value = true
    recoveryError.value = ''
    const current = () => alive && version === catalogVersion && view === viewVersion && scope === scopeVersion
    try {
      const [savedScenes, savedNetworks] = await Promise.all([allPages(getScenes, catalogAbort.signal), allPages(getNetworks, catalogAbort.signal)])
      if (!current()) return false
      scenes.value = savedScenes
      const fixed = networks.value.filter(item => item.asset_id === draft.value.network?.asset_id && item.version === draft.value.network.version
        || item.asset_id === resultNetwork.value?.asset_id && item.version === resultNetwork.value.version)
      networks.value = [...savedNetworks, ...fixed.filter(item => !savedNetworks.some(value => value.asset_id === item.asset_id && value.version === item.version))]
      return true
    } catch (cause) {
      if (current()) recoveryError.value = failure(cause)
      return false
    } finally { if (alive && version === catalogVersion) recovering.value = false }
  }
  async function recover() {
    const view = viewVersion
    if (!await refreshCatalogs()) return false
    if (!submissionPending.value && error.value === initializationError) error.value = ''
    initializationError = ''
    if (loading.value || saving.value || submitting.value || restoringView || cancelling.value || submissionPending.value) return true
    if (run.value?.run_id || draft.value.run_id) {
      const restored = await refreshRun(false, true)
      if (view !== viewVersion) return false
      if (!restored && error.value) recoveryError.value = error.value
      return restored
    }
    return true
  }
  async function chooseScene(id: string, expectedVersion?: number, restore = false, initialGuard?: string) {
    if (!alive || (restore ? rejectRestore() : rejectEdit(true))) {
      if (restore) throw new Error(error.value || '仿真工作区已关闭')
      return false
    }
    if (!id) { newScene(); return true }
    const operation = beginView(true)
    restoringView = restore
    loading.value = true
    error.value = ''
    try {
      const record = await getScene(id, operation.signal, expectedVersion)
      if (!currentView(operation.version, operation.scope)) return false
      const reference = record.network
      const savedNetwork = reference ? networks.value.find(item => item.asset_id === reference.asset_id && item.version === reference.version)
        ?? await getNetwork(reference.asset_id, reference.version, operation.signal) : null
      const savedRun = restore && record.run_id ? await readRun(record.run_id, operation.signal) : null
      if (!currentView(operation.version, operation.scope)) return false
      if (initialGuard !== undefined && JSON.stringify(draft.value) !== initialGuard) return false
      clearRun()
      if (savedNetwork) addNetwork(savedNetwork)
      acceptScene(record)
      if (savedRun) {
        run.value = savedRun.value; snapshot.value = savedRun.savedInput; result.value = savedRun.savedResult; resultNetwork.value = savedRun.savedNetwork
        addNetwork(savedRun.savedNetwork)
        if (busy.value) schedulePoll(savedRun.value.run_id, operation.scope)
      } else if (record.run_id && !await refreshRun()) return false
      return currentView(operation.version, operation.scope)
    } catch (cause) {
      if (currentView(operation.version, operation.scope)) error.value = failure(cause)
      if (restore && currentView(operation.version, operation.scope) && busy.value && run.value) schedulePoll(run.value.run_id, operation.scope)
      if (restore) throw cause
      return false
    } finally {
      if (currentView(operation.version, operation.scope)) { loading.value = false; restoringView = false }
    }
  }
  async function chooseNetwork(id: string, version: string) {
    if (!alive || rejectEdit()) return
    const operation = beginView()
    loading.value = true
    error.value = ''
    try {
      const value = networks.value.find(item => item.asset_id === id && item.version === version) ?? await getNetwork(id, version, operation.signal)
      if (!currentView(operation.version, operation.scope)) return
      previewDraft()
      addNetwork(value)
      useNetwork(value)
    } catch (cause) {
      if (currentView(operation.version, operation.scope)) error.value = failure(cause)
    } finally {
      if (currentView(operation.version, operation.scope)) loading.value = false
    }
  }
  function newScene() {
    if (!alive || rejectEdit(true)) return
    beginView(true)
    clearRun()
    historical.value = false
    sceneId.value = ''
    sceneVersion.value = null
    draft.value = makeDraft()
    const preferred = networks.value.find(item => item.asset_id === 'net-001') ?? networks.value[0]
    if (preferred) useNetwork(preferred)
    loading.value = false
    error.value = ''
    remember('')
  }
  function previewDraft() {
    if (!alive || rejectEdit(true)) return
    if (historical.value) {
      beginView(true)
      sceneId.value = ''
      sceneVersion.value = null
    }
    clearRun()
    historical.value = false
    loading.value = false
    draft.value.run_id = null
  }
  async function persist(asNew: boolean, operation: ReturnType<typeof beginView>) {
    saving.value = true
    try {
      const body = { ...copy(draft.value), camera: copy(getCamera()) }
      const value = await saveScene(body, asNew ? undefined : sceneId.value || undefined,
        asNew ? undefined : sceneVersion.value ?? undefined, operation.signal)
      if (!currentView(operation.version, operation.scope)) return
      acceptScene(value)
      return value
    } finally {
      if (currentView(operation.version, operation.scope)) saving.value = false
    }
  }
  async function save(asNew = false) {
    if (!alive || rejectEdit()) return
    if (loading.value) { error.value = '场景正在读取，请稍后保存。'; return }
    const operation = beginView()
    error.value = ''
    try { return await persist(asNew, operation) }
    catch (cause) { if (currentView(operation.version, operation.scope)) error.value = failure(cause) }
  }
  function schedulePoll(identity: string, scope: number, preserveDraft = false) {
    clearTimeout(timer)
    timer = setTimeout(() => {
      timer = undefined
      if (alive && scope === scopeVersion && run.value?.run_id === identity) void refreshRun(false, preserveDraft)
    }, 500)
  }
  function restoreSnapshot(value: RunRecord, savedInput: RunSnapshot, savedNetwork: NetworkRecord, savedResult: RunResult | null) {
    const { scene_id: _sceneId, ...configuration } = savedInput.request
    historical.value = true
    sceneId.value = ''
    sceneVersion.value = null
    draft.value = { ...inputOf(savedInput.scene), ...copy(configuration), run_id: value.run_id }
    run.value = value
    snapshot.value = savedInput
    result.value = savedResult
    resultNetwork.value = savedNetwork
    addNetwork(savedNetwork)
  }
  async function readRun(identity: string, signal: AbortSignal) {
    const [value, savedInput] = await Promise.all([getRun(identity, signal), getRunInput(identity, signal)])
    const [savedNetwork, savedResult] = await Promise.all([
      getNetwork(savedInput.request.network.asset_id, savedInput.request.network.version, signal),
      value.status === 'succeeded' ? getRunResult(identity, signal) : Promise.resolve(null),
    ])
    return { value, savedInput, savedNetwork, savedResult }
  }
  async function openRun(identity: string, restore = false) {
    if (!alive || (restore ? rejectRestore() : rejectEdit(true))) {
      if (restore) throw new Error(error.value || '仿真工作区已关闭')
      return false
    }
    const operation = beginView(true)
    restoringView = restore
    loading.value = true
    error.value = ''
    try {
      const [value, savedInput] = await Promise.all([getRun(identity, operation.signal), getRunInput(identity, operation.signal)])
      if (!currentView(operation.version, operation.scope)) return false
      const [savedNetwork, savedResult] = await Promise.all([
        getNetwork(savedInput.request.network.asset_id, savedInput.request.network.version, operation.signal),
        value.status === 'succeeded' ? getRunResult(identity, operation.signal) : Promise.resolve(null),
      ])
      if (!currentView(operation.version, operation.scope)) return false
      clearRun()
      restoreSnapshot(value, savedInput, savedNetwork, savedResult)
      if (value.status === 'queued' || value.status === 'running') schedulePoll(identity, operation.scope)
      return true
    } catch (cause) {
      if (currentView(operation.version, operation.scope)) error.value = failure(cause)
      if (restore) throw cause
      return false
    }
    finally { if (currentView(operation.version, operation.scope)) { loading.value = false; restoringView = false } }
  }
  function cancelRestore() {
    if (!alive || !restoringView) return
    beginView(true)
    restoringView = false
    loading.value = false
    if (busy.value && run.value) schedulePoll(run.value.run_id, scopeVersion)
  }
  async function acceptRun(value: RunRecord, version: number, scope: number, signal: AbortSignal, preserveDraft = false, expectedView?: number) {
    const current = () => currentRun(version, scope) && (expectedView === undefined || expectedView === viewVersion)
    if (!current()) return
    run.value = value
    const running = value.status === 'queued' || value.status === 'running'
    if (running && !historical.value) { schedulePoll(value.run_id, scope, preserveDraft); return }
    const savedInput = await getRunInput(value.run_id, signal)
    if (!current()) return
    const [savedResult, savedNetwork] = await Promise.all([
      value.status === 'succeeded' ? getRunResult(value.run_id, signal) : Promise.resolve(null),
      getNetwork(savedInput.request.network.asset_id, savedInput.request.network.version, signal),
    ])
    if (!current()) return
    snapshot.value = savedInput
    result.value = savedResult
    resultNetwork.value = savedNetwork
    addNetwork(savedNetwork)
    if (!preserveDraft && historical.value && draft.value.run_id !== value.run_id) restoreSnapshot(value, savedInput, savedNetwork, savedResult)
    if (running) schedulePoll(value.run_id, scope, preserveDraft)
  }
  async function refreshRun(strict = false, preserveDraft = false) {
    if (!alive || submitting.value || submissionPending.value || cancelling.value) return false
    const identity = run.value?.run_id ?? draft.value.run_id
    if (!identity) return false
    stopRunRead()
    const version = runVersion, scope = scopeVersion, view = viewVersion
    runAbort = new AbortController()
    error.value = ''
    try {
      const value = await getRun(identity, runAbort.signal)
      await acceptRun(value, version, scope, runAbort.signal, preserveDraft, preserveDraft ? view : undefined)
      return currentRun(version, scope) && (!preserveDraft || view === viewVersion)
    } catch (cause) {
      if (currentRun(version, scope) && (!preserveDraft || view === viewVersion)) error.value = failure(cause)
      if (strict) throw cause
      return false
    }
  }
  async function submit() {
    if (!alive || busy.value || submitting.value || saving.value) return
    if (loading.value) { error.value = '场景正在读取，请稍后提交。'; return }
    if (historical.value && !pending.value) { rejectEdit(); return }
    const operation = beginView()
    submitting.value = true
    error.value = ''
    try {
      if (!pending.value) {
        if (!draft.value.network || !draft.value.origin || !draft.value.destination) throw new Error('请选择路网版本、起点和终点。')
        const saved = await persist(false, operation)
        if (!saved || !currentView(operation.version, operation.scope)) return
        clearRun()
        pending.value = { kind: 'submit', key: crypto.randomUUID(), body: { scene_id: saved.id, network: copy(saved.network!),
          origin: saved.origin!, destination: saved.destination!, blocked_edges: [...new Set(saved.blocked_edges)].sort(), params: copy(saved.params), seed: saved.seed } }
      }
      const fixed = pending.value
      postAbort = new AbortController()
      const value = fixed.kind === 'rerun' ? await rerunRun(fixed.source_id, fixed.key, postAbort.signal)
        : await submitRun(copy(fixed.body), fixed.key, postAbort.signal)
      if (!currentView(operation.version, operation.scope)) return
      pending.value = null
      if (fixed.kind === 'rerun') { clearRun(); historical.value = true; draft.value.run_id = null }
      else { historical.value = false; draft.value.run_id = value.run_id }
      stopRunRead()
      runAbort = new AbortController()
      await acceptRun(value, runVersion, operation.scope, runAbort.signal)
    } catch (cause) {
      if (!currentView(operation.version, operation.scope)) return
      if (pending.value && (!(cause instanceof ApiError) || cause.status === 0 || cause.status >= 500))
        error.value = `提交结果尚未确认，请重试提交；将复用原幂等键和固定输入。${failure(cause)}`
      else { pending.value = null; error.value = failure(cause) }
    } finally {
      if (currentView(operation.version, operation.scope)) submitting.value = false
    }
  }
  async function rerun(identity: string) {
    if (!alive || busy.value || submitting.value || saving.value) return
    if (pending.value) { error.value = '提交结果尚未确认，请先重试原提交。'; return }
    if (loading.value) { error.value = '场景正在读取，请稍后重跑。'; return }
    pending.value = { kind: 'rerun', source_id: identity, key: crypto.randomUUID() }
    return submit()
  }
  async function cancel() {
    if (!alive || !busy.value || cancelling.value || submitting.value) return
    stopRunRead()
    const version = runVersion, scope = scopeVersion
    runAbort = new AbortController()
    cancelling.value = true
    error.value = ''
    try {
      const value = await cancelRun(run.value!.run_id, runAbort.signal)
      await acceptRun(value, version, scope, runAbort.signal)
    } catch (cause) { if (currentRun(version, scope)) error.value = failure(cause) }
    finally { if (currentRun(version, scope)) cancelling.value = false }
  }
  function toggleEdge(id: string) {
    if (!alive || rejectEdit()) return
    if (!network.value?.edges.some(edge => edge.id === id)) { error.value = '阻断边不属于当前路网版本。'; return }
    previewDraft()
    const blocked = new Set(draft.value.blocked_edges)
    if (blocked.has(id)) blocked.delete(id)
    else blocked.add(id)
    draft.value.blocked_edges = [...blocked].sort()
  }
  watch(configuration, value => {
    if (value === acceptedConfiguration) { acceptedConfiguration = undefined; return }
    if (run.value && !editingLocked.value) previewDraft()
  })
  onBeforeUnmount(() => {
    alive = false
    ++viewVersion
    ++scopeVersion
    viewAbort?.abort()
    ++catalogVersion; catalogAbort?.abort()
    postAbort?.abort()
    stopRunRead()
  })
  return { scenes, networks, draft, sceneId, sceneVersion, historical, network, run, result, snapshot, resultNetwork,
    loading, saving, submitting, cancelling, recovering, recoveryError, error, busy, submissionPending, editingLocked,
    initialize, refreshCatalogs, recover, chooseScene, chooseNetwork, newScene, previewDraft, save, submit, cancel, refreshRun, toggleEdge, openRun, rerun, cancelRestore }
}
