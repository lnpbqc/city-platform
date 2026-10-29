import {
  Viewer,
  Ion,
  Math as CesiumMath,
  Cartesian2,
  Cartesian3,
  Cartographic,
  Color,
  GeoJsonDataSource,
  Cesium3DTileset,
  Cesium3DTileStyle,
  ColorMaterialProperty,
  ConstantProperty,
  ConstantPositionProperty,
  VerticalOrigin,
  HeightReference,
  ScreenSpaceEventHandler,
  ScreenSpaceEventType,
  Entity,
  SceneMode,
  createWorldImageryAsync,
  createWorldTerrainAsync,
  TileMapServiceImageryProvider,
  buildModuleUrl,
  HeadingPitchRange,
  BoundingSphere,
  ClassificationType,
  Credit,
  EllipsoidGeodesic,
} from 'cesium'
import type { MapLayer, Selection, GeometryDocument, ObjectRecord } from './types'
import type { PolygonGraphics } from 'cesium'
import type { RegionTarget } from './regions'
import { fetchRegionBoundary, type BoundaryState } from './regionBoundary.ts'
import { sampleBuildingTerrain } from './buildingTerrain.ts'
import { ApiError, getAssetVersion } from './api.ts'
import { fetchMapGeoJSON, mapLoadError, planarGeoJSON } from './mapResource.ts'
import { validCamera, scaleForDistance, type CameraState, type NavigationReading } from './mapNavigation.ts'
import { objectIdentity, identifyFeatures } from './objectIdentity.ts'
import { simulationGeometry } from './simulationGeometry.ts'
import type { NetworkRecord, RunResult } from './simulationTypes'
import type { TimeSeriesRecord } from './temporalTypes'
import { temporalColor } from './temporal.ts'

type Resource = GeoJsonDataSource | Cesium3DTileset
type Entry = { version: number; resource?: Resource; abort: AbortController; cleanup: (() => void)[]; objectIds?: string[]; temporal?: TimeSeriesRecord | null }

export interface MapPoint {
  longitude: number
  latitude: number
}

export function createMapController(
  container: HTMLElement,
  onPick: (selection: Selection | null) => void,
  onNotice: (message: string) => void,
  onBoundaryState: (state: BoundaryState) => void = () => {},
  onNavigation: (state: NavigationReading, settled: boolean) => void = () => {},
) {
  const viewer = new Viewer(container, {
    baseLayer: false,
    baseLayerPicker: false,
    geocoder: false,
    homeButton: false,
    sceneModePicker: false,
    navigationHelpButton: false,
    animation: false,
    timeline: false,
    fullscreenButton: false,
    infoBox: false,
    selectionIndicator: false,
    requestRenderMode: true,
    maximumRenderTimeChange: Infinity,
    contextOptions: { webgl: { alpha: false } },
  })
  viewer.scene.globe.baseColor = Color.fromCssColorString('#d4e0e4')
  viewer.scene.backgroundColor = Color.fromCssColorString('#0b1728')
  viewer.scene.globe.depthTestAgainstTerrain = true
  viewer.scene.screenSpaceCameraController.minimumZoomDistance = 30
  const entries = new Map<MapLayer, Entry>()
  let alive = true
  let boundaryVersion = 0
  let boundaryAbort: AbortController | undefined
  let boundary: GeoJsonDataSource | undefined
  let pointMarker: Entity | undefined
  let pointPicking: ((point: MapPoint) => void) | undefined
  let pointer: NavigationReading['pointer'] = null
  let pointerPosition: Cartesian2 | undefined
  let homeRegion: RegionTarget | undefined
  let homeResource: Resource | undefined
  let autoFrame = true
  let areaMode: 'box' | 'polygon' | null = null
  let areaPoints: MapPoint[] = []
  let areaCallback: ((geometry: GeometryDocument) => void) | undefined
  let areaCancelled: (() => void) | undefined
  let boxStart: Cartesian2 | undefined
  let previousInputs = true
  let areaSurface: HTMLDivElement | undefined
  let areaHandler: ScreenSpaceEventHandler | undefined
  const draftEntities: Entity[] = []
  let highlightLayerId: string | null = null
  let highlightIds = new Set<string>()
  let activeObjectId: string | undefined
  const highlightRestorers: (() => void)[] = []
  const simulationEntities: Entity[] = []
  const simulationEdges = new Map<Entity, string>()
  const replayEntities = new Map<string, { entity: Entity; position: ConstantPositionProperty; elevated: boolean }>()
  let simulationPick: ((identity: string) => void) | undefined

  function showReplay(positions: { baseline: number[] | null; blocked: number[] | null }) {
    if (!alive) return
    for (const role of ['baseline', 'blocked'] as const) {
      const coordinates = positions[role]
      const current = replayEntities.get(role)
      if (!coordinates) {
        if (current) { viewer.entities.remove(current.entity); replayEntities.delete(role) }
        continue
      }
      const value = Cartesian3.fromDegrees(coordinates[0]!, coordinates[1]!, coordinates[2] ?? 0)
      const elevated = coordinates.length > 2
      const reference = elevated ? HeightReference.NONE : HeightReference.CLAMP_TO_TERRAIN
      if (current) {
        current.position.setValue(value)
        if (current.elevated !== elevated) {
          current.entity.point!.heightReference = new ConstantProperty(reference)
          current.entity.label!.heightReference = new ConstantProperty(reference)
          current.elevated = elevated
        }
      } else {
        const position = new ConstantPositionProperty(value)
        const entity = viewer.entities.add({ position, properties: { simulation_role: `replay_${role}` },
          point: { pixelSize: role === 'baseline' ? 17 : 10, color: Color.fromCssColorString(role === 'baseline' ? '#2563eb' : '#f59e0b'),
            outlineColor: Color.WHITE, outlineWidth: 2, heightReference: reference },
          label: { text: role === 'baseline' ? '基准' : '阻断后', font: '12px sans-serif', heightReference: reference,
            fillColor: Color.WHITE, showBackground: true, backgroundColor: Color.fromCssColorString('#29405a').withAlpha(0.85),
            pixelOffset: new Cartesian2(role === 'baseline' ? -28 : 30, 18) } })
        replayEntities.set(role, { entity, position, elevated })
      }
    }
    viewer.scene.requestRender()
  }

  function showSimulation(network: NetworkRecord | null, blocked: string[] = [], result: RunResult | null = null,
                          onEdge?: (identity: string) => void) {
    for (const entity of simulationEntities) viewer.entities.remove(entity)
    simulationEntities.length = 0
    simulationEdges.clear()
    simulationPick = onEdge
    if (!network || !alive) { viewer.scene.requestRender(); return }
    const geometry = simulationGeometry(network, blocked, result)
    const point = (coordinates: number[]) => Cartesian3.fromDegrees(coordinates[0]!, coordinates[1]!, coordinates[2] ?? 0)
    const add = (options: NonNullable<ConstructorParameters<typeof Entity>[0]>, edgeId?: string) => {
      const entity = viewer.entities.add(options)
      simulationEntities.push(entity)
      if (edgeId) simulationEdges.set(entity, edgeId)
    }
    const line = (coordinates: number[][], color: string, width: number, role: string, edgeId: string) => add({
      polyline: { positions: coordinates.map(point), width, material: Color.fromCssColorString(color),
        clampToGround: coordinates.every(position => position.length === 2) },
      properties: { simulation_role: role, edge_id: edgeId },
    }, edgeId)
    for (const edge of geometry.edges)
      line(edge.coordinates, edge.blocked ? '#dc2626' : '#64748b', edge.blocked ? 5 : 3, 'network', edge.id)
    for (const path of geometry.paths) {
      for (let index = 0; index < path.edgeIds.length; index++)
        line(path.coordinates.slice(index, index + 2), path.color, path.role === 'baseline' ? 9 : 4, path.role, path.edgeIds[index]!)
      if (path.coordinates.length === 1) add({ position: point(path.coordinates[0]!),
        point: { pixelSize: path.role === 'baseline' ? 22 : 12, color: Color.fromCssColorString(path.color), heightReference: HeightReference.CLAMP_TO_TERRAIN } })
    }
    for (const node of network.nodes) add({ position: point(node.coordinates),
      point: { pixelSize: 7, color: Color.WHITE, outlineColor: Color.fromCssColorString('#334155'), outlineWidth: 2, heightReference: HeightReference.CLAMP_TO_TERRAIN },
      label: { text: node.id, font: '14px sans-serif', fillColor: Color.fromCssColorString('#0f172a'),
        showBackground: true, backgroundColor: Color.WHITE.withAlpha(0.9), pixelOffset: new Cartesian2(0, -20), heightReference: HeightReference.CLAMP_TO_TERRAIN } })
    for (const edge of geometry.edges.filter(edge => edge.blocked)) add({ position: point(edge.midpoint),
      label: { text: '×', font: 'bold 32px sans-serif', fillColor: Color.fromCssColorString('#dc2626'),
        showBackground: true, backgroundColor: Color.WHITE.withAlpha(0.9), heightReference: HeightReference.CLAMP_TO_TERRAIN },
      properties: { simulation_role: 'blocked_edge', edge_id: edge.id },
    }, edge.id)
    viewer.scene.requestRender()
  }

  function restoreHighlights() {
    for (const restore of highlightRestorers) restore()
    highlightRestorers.length = 0
  }
  function changeHighlight(target: object, key: string, value: unknown) {
    const properties = target as Record<string, unknown>
    const previous = properties[key]
    highlightRestorers.push(() => { properties[key] = previous })
    properties[key] = value
  }
  function entityObjectId(entry: Entry | undefined, entity: Entity) {
    if (!entry?.objectIds) return undefined
    const id = entity.id.split('_')[0]!
    return entry?.objectIds?.includes(id) ? id : undefined
  }
  function paintEntity(entity: Entity, colorText: string, opacity: number, remember = true) {
    const set = remember ? changeHighlight : (target: object, key: string, value: unknown) => { (target as Record<string, unknown>)[key] = value }
    const color = Color.fromCssColorString(colorText)
    if (entity.polygon) set(entity.polygon, 'material', new ColorMaterialProperty(color.withAlpha(opacity * (entity.polygon.extrudedHeight ? 1 : 0.7))))
    if (entity.polyline) {
      set(entity.polyline, 'material', new ColorMaterialProperty(color.withAlpha(opacity)))
      set(entity.polyline, 'width', new ConstantProperty(remember ? 6 : 4))
    }
    if (entity.point) set(entity.point, 'color', new ConstantProperty(color.withAlpha(opacity)))
    if (entity.billboard) {
      set(entity.billboard, 'image', new ConstantProperty(`data:image/svg+xml,${encodeURIComponent(`<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24"><circle cx="12" cy="12" r="9" fill="${colorText}" stroke="white" stroke-width="3"/></svg>`)}`))
      set(entity.billboard, 'color', new ConstantProperty(Color.WHITE.withAlpha(opacity)))
    }
  }
  function applyTemporal(layer: MapLayer, entry: Entry) {
    if (!(entry.resource instanceof GeoJsonDataSource) || entry.temporal === undefined) return
    const values = new Map(entry.temporal?.items.map(item => [item.object_id, item]) ?? [])
    for (const entity of entry.resource.entities.values) {
      const item = values.get(entityObjectId(entry, entity) ?? '')
      entity.show = !!item && !item.missing
      if (item && !item.missing && item.value !== null) paintEntity(entity, temporalColor(item.value, entry.temporal!.unit), layer.opacity, false)
    }
  }
  function showTemporal(layer: MapLayer, value: TimeSeriesRecord | null) {
    const entry = entries.get(layer)
    if (!entry || !alive || layer.static !== false) return
    restoreHighlights()
    entry.temporal = value
    applyTemporal(layer, entry)
    paintHighlights()
    viewer.scene.requestRender()
  }
  function paintHighlights() {
    restoreHighlights()
    if (!alive || !highlightLayerId) return
    const match = [...entries].find(([layer]) => layer.id === highlightLayerId)
    if (!match) return
    const [layer, entry] = match
    const resource = entry.resource
    if (resource instanceof GeoJsonDataSource) {
      for (const entity of resource.entities.values) {
        const id = entity.id.split('_')[0]!
        if (highlightIds.has(id)) paintEntity(entity, id === activeObjectId ? '#f59e0b' : '#22c3ee', layer.opacity)
      }
    } else if (resource && entry.objectIds?.some(id => highlightIds.has(id))) {
      changeHighlight(resource, 'style', new Cesium3DTileStyle({ color: `color('${activeObjectId ? '#f59e0b' : '#22c3ee'}', ${layer.opacity})` }))
    }
    viewer.scene.requestRender()
  }
  function highlightObjects(layerId: string | null, ids: string[], activeId?: string) {
    highlightLayerId = layerId
    highlightIds = new Set(ids)
    activeObjectId = activeId
    paintHighlights()
  }
  function objectPage(id: string, layerId: string, pageSize = 20) {
    const entry = [...entries].find(([layer]) => layer.id === layerId)?.[1]
    const index = entry?.objectIds?.indexOf(id) ?? -1
    return index < 0 ? undefined : Math.floor(index / pageSize) + 1
  }
  async function focusObject(layerId: string, object: ObjectRecord) {
    autoFrame = false
    const match = [...entries].find(([layer]) => layer.id === layerId)
    if (!alive || !match?.[1].resource) { onNotice('所选图层尚未加载，暂时无法定位对象。'); return }
    const [layer, entry] = match
    if (entry.resource instanceof Cesium3DTileset) { await locate(layer); return }
    const entities = entry.resource!.entities.values.filter(entity => entityObjectId(entry, entity) === object.object_id)
    if (!entities.length || !object.geometry) { onNotice('对象未提供可定位的几何。'); return }
    try {
      const located = await viewer.flyTo(entities, { duration: 0.8, offset: new HeadingPitchRange(0, CesiumMath.toRadians(-55), object.type === 'point' ? 400 : 0) })
      if (!located && alive) onNotice('对象未提供可定位的几何。')
      navigation(true)
    } catch { if (alive) onNotice('对象定位失败，请重试或定位所属图层。') }
  }

  function clearDraft() {
    for (const entity of draftEntities) viewer.entities.remove(entity)
    draftEntities.length = 0
  }
  function drawDraft(points: MapPoint[]) {
    clearDraft()
    const positions = points.map(point => Cartesian3.fromDegrees(point.longitude, point.latitude))
    if (positions.length > 1) draftEntities.push(viewer.entities.add({ polyline: {
      positions, width: 3, clampToGround: true, material: Color.fromCssColorString('#f5a400'),
    } }))
    for (const position of positions) draftEntities.push(viewer.entities.add({ position,
      point: { pixelSize: 6, color: Color.fromCssColorString('#f5a400'), heightReference: HeightReference.CLAMP_TO_TERRAIN, disableDepthTestDistance: 0 } }))
    viewer.scene.requestRender()
  }
  function groundPoint(position: Cartesian2): MapPoint | null {
    const target = groundAt(position)
    if (!target) return null
    const coordinates = Cartographic.fromCartesian(target)
    return { longitude: CesiumMath.toDegrees(coordinates.longitude), latitude: CesiumMath.toDegrees(coordinates.latitude) }
  }
  function cancelAreaSelection() {
    if (!areaMode) return
    areaMode = null
    areaPoints = []
    boxStart = undefined
    areaCallback = undefined
    areaHandler?.destroy()
    areaHandler = undefined
    areaSurface?.remove()
    areaSurface = undefined
    viewer.scene.screenSpaceCameraController.enableInputs = previousInputs
    clearDraft()
    const cancelled = areaCancelled
    areaCancelled = undefined
    cancelled?.()
    if (alive) viewer.scene.requestRender()
  }
  function beginAreaSelection(mode: 'box' | 'polygon', callback: (geometry: GeometryDocument) => void, cancelled?: () => void) {
    if (!alive) return
    cancelAreaSelection()
    cancelPointPicking()
    autoFrame = false
    areaMode = mode
    areaCallback = callback
    areaCancelled = cancelled
    previousInputs = viewer.scene.screenSpaceCameraController.enableInputs
    viewer.scene.screenSpaceCameraController.enableInputs = false
    // Keep drawing events off the camera canvas, including the final mouse-up.
    areaSurface = container.ownerDocument.createElement('div')
    Object.assign(areaSurface.style, { position: 'absolute', inset: '0', zIndex: '1', cursor: 'crosshair', touchAction: 'none' })
    areaSurface.setAttribute('aria-label', '地面范围绘制')
    container.appendChild(areaSurface)
    areaHandler = new ScreenSpaceEventHandler(areaSurface)
    for (const type of [ScreenSpaceEventType.LEFT_CLICK, ScreenSpaceEventType.LEFT_DOWN, ScreenSpaceEventType.LEFT_UP, ScreenSpaceEventType.MOUSE_MOVE])
      areaHandler.setInputAction(handler.getInputAction(type), type)
  }
  function finishAreaSelection() {
    if (!alive || !areaMode) return false
    if (new Set(areaPoints.map(point => `${point.longitude},${point.latitude}`)).size < 3) {
      onNotice('选择范围至少需要三个不同的地面点。')
      return false
    }
    const coordinates = areaPoints.map(point => [point.longitude, point.latitude])
    coordinates.push([...coordinates[0]!])
    const callback = areaCallback
    cancelAreaSelection()
    callback?.({ type: 'Polygon', coordinates: [coordinates] })
    return true
  }
  function boxPoints(end: Cartesian2) {
    if (!boxStart || boxStart.x === end.x || boxStart.y === end.y) return null
    const left = Math.min(boxStart.x, end.x), right = Math.max(boxStart.x, end.x)
    const top = Math.min(boxStart.y, end.y), bottom = Math.max(boxStart.y, end.y)
    const points = [new Cartesian2(left, top), new Cartesian2(right, top), new Cartesian2(right, bottom), new Cartesian2(left, bottom)].map(groundPoint)
    return points.every(point => point !== null) ? points as MapPoint[] : null
  }

  function getCamera(): CameraState {
    const position = viewer.camera.positionCartographic
    return { longitude: CesiumMath.toDegrees(position.longitude), latitude: CesiumMath.toDegrees(position.latitude),
      height: position.height, heading: viewer.camera.heading, pitch: viewer.camera.pitch, roll: viewer.camera.roll,
      scene_mode: viewer.scene.mode === SceneMode.SCENE2D ? '2d' : '3d' }
  }
  function groundAt(position: Cartesian2) {
    const ray = viewer.camera.getPickRay(position)
    return (ray && viewer.scene.globe.pick(ray, viewer.scene))
      ?? viewer.camera.pickEllipsoid(position, viewer.scene.globe.ellipsoid)
  }
  function navigation(settled = false) {
    if (!alive || viewer.scene.mode === SceneMode.MORPHING) return
    const target = pointerPosition ? (viewer.scene.pickPositionSupported ? viewer.scene.pickPosition(pointerPosition) : undefined) ?? groundAt(pointerPosition) : undefined
    const position = target ? Cartographic.fromCartesian(target) : undefined
    pointer = position ? { longitude: CesiumMath.toDegrees(position.longitude), latitude: CesiumMath.toDegrees(position.latitude), height: position.height } : null
    const canvas = viewer.scene.canvas
    const y = canvas.clientHeight - 40
    const first = groundAt(new Cartesian2(canvas.clientWidth / 2 - 50, y))
    const second = groundAt(new Cartesian2(canvas.clientWidth / 2 + 50, y))
    let scale = null
    if (first && second) {
      const start = Cartographic.fromCartesian(first), end = Cartographic.fromCartesian(second)
      scale = scaleForDistance(new EllipsoidGeodesic(start, end, viewer.scene.globe.ellipsoid).surfaceDistance)
    }
    onNavigation({ camera: getCamera(), pointer, scale }, settled)
  }
  const navigationCleanup = [viewer.camera.changed.addEventListener(() => navigation()),
    viewer.camera.moveEnd.addEventListener(() => navigation(true)),
    viewer.scene.morphComplete.addEventListener(() => navigation(true))]
  function setCamera(camera: CameraState) {
    if (!alive || !validCamera(camera)) return false
    autoFrame = false
    if (camera.scene_mode === '2d') viewer.scene.morphTo2D(0)
    else if (viewer.scene.mode !== SceneMode.SCENE3D) viewer.scene.morphTo3D(0)
    viewer.camera.setView({ destination: Cartesian3.fromDegrees(camera.longitude, camera.latitude, camera.height),
      orientation: { heading: camera.heading, pitch: camera.pitch, roll: camera.roll } })
    viewer.scene.requestRender()
    navigation(true)
    return true
  }
  function north() { setCamera({ ...getCamera(), heading: 0, roll: 0 }) }
  function stopAutoFrame() { autoFrame = false }
  function clearPointer() { pointerPosition = undefined; navigation() }
  viewer.scene.canvas.addEventListener?.('pointerdown', stopAutoFrame)
  viewer.scene.canvas.addEventListener?.('wheel', stopAutoFrame)
  viewer.scene.canvas.addEventListener?.('mouseleave', clearPointer)

  function cancelPointPicking() {
    pointPicking = undefined
    if (!alive) return
    if (pointMarker) viewer.entities.remove(pointMarker)
    pointMarker = undefined
    viewer.scene.requestRender()
  }

  function showPoint(point: MapPoint) {
    if (pointMarker) viewer.entities.remove(pointMarker)
    pointMarker = viewer.entities.add({
      position: Cartesian3.fromDegrees(point.longitude, point.latitude, 0),
      point: {
        pixelSize: 16,
        color: Color.fromCssColorString('#f59e0b'),
        outlineColor: Color.WHITE,
        outlineWidth: 3,
        heightReference: HeightReference.CLAMP_TO_TERRAIN,
      },
    })
    viewer.scene.requestRender()
  }

  function beginPointPicking(callback: (point: MapPoint) => void) {
    if (!alive) return
    cancelAreaSelection()
    cancelPointPicking()
    pointPicking = callback
    onPick(null)
  }

  function goToPoint(point: MapPoint) {
    if (!alive) return
    autoFrame = false
    cancelAreaSelection()
    pointPicking = undefined
    showPoint(point)
    if (viewer.scene.mode !== SceneMode.SCENE3D) viewer.scene.morphTo3D(0)
    viewer.camera.flyToBoundingSphere(
      new BoundingSphere(
        Cartesian3.fromDegrees(point.longitude, point.latitude, 0),
        1,
      ),
      {
        offset: new HeadingPitchRange(0, CesiumMath.toRadians(-60), 1000),
        duration: 1.2,
        complete: () => navigation(true),
      },
    )
  }

  async function setRegionBoundary(id: string | null, frame = false) {
    if (!alive) return
    const version = ++boundaryVersion
    boundaryAbort?.abort()
    if (boundary) viewer.dataSources.remove(boundary, true)
    boundary = undefined
    viewer.scene.requestRender()
    if (!id || id === 'demo' || id.startsWith('demo-')) {
      onBoundaryState({ status: 'idle' })
      return
    }
    const abort = new AbortController()
    boundaryAbort = abort
    const current = () => alive && version === boundaryVersion
    onBoundaryState({ status: 'loading' })
    let pending: GeoJsonDataSource | undefined
    try {
      const data = await fetchRegionBoundary(
        id,
        AbortSignal.any([abort.signal, AbortSignal.timeout(20_000)]),
      )
      if (!current()) return
      pending = await GeoJsonDataSource.load(data, {
        clampToGround: true,
        stroke: Color.fromCssColorString('#38bdff'),
        strokeWidth: 3,
      })
      if (!current()) return
      for (const entity of pending.entities.values) {
        if (entity.polyline)
          entity.polyline.classificationType = new ConstantProperty(
            ClassificationType.TERRAIN,
          )
      }
      await viewer.dataSources.add(pending)
      if (!current()) {
        if (alive) viewer.dataSources.remove(pending, true)
        return
      }
      boundary = pending
      onBoundaryState({ status: 'ready' })
      viewer.scene.requestRender()
      if (frame)
        void viewer
          .flyTo(pending, {
            duration: 1.1,
            offset: new HeadingPitchRange(0, CesiumMath.toRadians(-90), 0),
          })
          .catch(() => {
            if (current()) onNotice('边界已显示，可使用缩放控件调整视野。')
          })
    } catch (error) {
      if (!current()) return
      if (pending) viewer.dataSources.remove(pending, true)
      onBoundaryState({
        status: 'error',
        error: error instanceof Error ? error.message : '未知错误',
      })
    }
  }
  let renderNoticeShown = false
  viewer.scene.renderError.addEventListener((_scene, error) => {
    if (!renderNoticeShown) {
      renderNoticeShown = true
      onNotice(`地图渲染异常：${error.message}`)
    }
  })

  function goToRegion(region: RegionTarget) {
    if (!alive) return
    cancelAreaSelection()
    autoFrame = false
    homeRegion = region
    homeResource = undefined
    cancelPointPicking()
    if (viewer.scene.mode !== SceneMode.SCENE3D) viewer.scene.morphTo3D(0)
    viewer.camera.flyToBoundingSphere(
      new BoundingSphere(
        Cartesian3.fromDegrees(region.longitude, region.latitude, 0),
        1,
      ),
      {
        offset: new HeadingPitchRange(
          0,
          CesiumMath.toRadians(region.pitch),
          region.range,
        ),
        duration: 1.2,
        complete: () => navigation(true),
      },
    )
  }

  async function setBasemap() {
    const token = import.meta.env?.VITE_CESIUM_ION_TOKEN
    if (token) Ion.defaultAccessToken = token
    try {
      const imagery = token
        ? await createWorldImageryAsync()
        : await TileMapServiceImageryProvider.fromUrl(
            buildModuleUrl('Assets/Textures/NaturalEarthII'),
          )
      if (!alive) return
      imagery.errorEvent.addEventListener(() =>
        onNotice('影像瓦片加载失败，请检查网络或 ion 权限；专题图层仍可操作。'),
      )
      viewer.imageryLayers.addImageryProvider(imagery)
      viewer.scene.requestRender()
      if (!token)
        onNotice('尚未配置 ion Token，当前使用内置低分辨率地球影像与椭球地表。')
    } catch {
      if (alive)
        onNotice(
          'ion 影像不可用，请检查 Token、网络和资源权限；当前保留椭球地表。',
        )
    }
    if (token && alive) {
      try {
        const terrain = await createWorldTerrainAsync()
        if (!alive) return
        terrain.errorEvent.addEventListener(() =>
          onNotice('地形瓦片加载失败，请检查网络和 ion 权限。'),
        )
        viewer.terrainProvider = terrain
        viewer.scene.requestRender()
      } catch {
        if (alive)
          onNotice('ion 地形不可用，当前使用椭球地表；请检查网络和资源权限。')
      }
    }
  }
  const basemapReady = setBasemap()

  function disposeResource(resource: Resource) {
    if (resource instanceof GeoJsonDataSource)
      viewer.dataSources.remove(resource, true)
    else if (
      !resource.isDestroyed() &&
      !viewer.scene.primitives.remove(resource)
    )
      resource.destroy()
  }

  function appearance(layer: MapLayer) {
    restoreHighlights()
    if (layer.id === 'basemap') {
      for (let index = 0; index < viewer.imageryLayers.length; index++) {
        const imagery = viewer.imageryLayers.get(index)
        imagery.show = layer.attached && layer.visible
        imagery.alpha = layer.opacity
      }
      if (alive) viewer.scene.requestRender()
      paintHighlights()
      return
    }
    const resource = entries.get(layer)?.resource
    if (!resource || !alive) { paintHighlights(); return }
    resource.show = layer.visible
    if (resource instanceof Cesium3DTileset)
      resource.style = new Cesium3DTileStyle({
        color: `color('white', ${layer.opacity})`,
      })
    else {
      const color = Color.fromCssColorString(layer.color)
      for (const entity of resource.entities.values) {
        if (entity.point) {
          entity.point.color = new ConstantProperty(
            color.withAlpha(layer.opacity),
          )
          entity.point.outlineColor = new ConstantProperty(
            Color.WHITE.withAlpha(layer.opacity),
          )
        }
        if (entity.billboard)
          entity.billboard.color = new ConstantProperty(
            Color.WHITE.withAlpha(layer.opacity),
          )
        if (entity.polyline)
          entity.polyline.material = new ColorMaterialProperty(
            color.withAlpha(layer.opacity),
          )
        if (entity.polygon) {
          entity.polygon.material = new ColorMaterialProperty(
            color.withAlpha(
              layer.opacity * (entity.polygon.extrudedHeight ? 1 : 0.36),
            ),
          )
        }
      }
    }
    const entry = entries.get(layer)
    if (entry) applyTemporal(layer, entry)
    viewer.scene.requestRender()
    paintHighlights()
  }
  function syncOrder(layers: MapLayer[]) {
    if (!alive) return
    for (const layer of [...layers].sort((left, right) => (right.order ?? 0) - (left.order ?? 0))) {
      const resource = entries.get(layer)?.resource
      if (!layer.orderable || !(resource instanceof GeoJsonDataSource)) continue
      for (const entity of resource.entities.values) {
        if (entity.polyline) entity.polyline.zIndex = new ConstantProperty(-(layer.order ?? 0))
        if (entity.polygon && !entity.polygon.height && !entity.polygon.extrudedHeight
          && !entity.polygon.perPositionHeight?.getValue(viewer.clock.currentTime))
          entity.polygon.zIndex = new ConstantProperty(-(layer.order ?? 0))
      }
      viewer.dataSources.raiseToTop(resource)
    }
    viewer.scene.requestRender()
  }

  function remove(layer: MapLayer) {
    if (highlightLayerId === layer.id) { highlightObjects(null, []); onPick(null) }
    const entry = entries.get(layer)
    if (entry) {
      entry.version++
      entry.abort.abort()
      for (const cleanup of entry.cleanup) cleanup()
      if (entry.resource) disposeResource(entry.resource)
      entries.delete(layer)
    }
    layer.attached = false
    layer.status = 'idle'
    layer.error = ''
    layer.progress = null
    layer.loadPhase = ''
    layer.traceId = ''
    layer.errorCode = ''
    if (layer.id === 'basemap') appearance(layer)
    if (alive) viewer.scene.requestRender()
  }

  async function load(layer: MapLayer) {
    remove(layer)
    layer.attached = true
    layer.status = 'loading'
    layer.visible = true
    layer.progress = null
    layer.loadPhase = '正在解析资产版本'
    const entry: Entry = { version: 0, abort: new AbortController(), cleanup: [], temporal: layer.static === false ? null : undefined }
    entries.set(layer, entry)
    const current = () =>
      alive && entries.get(layer) === entry && entry.version === 0
    let pending: Resource | undefined
    try {
      if (layer.id === 'basemap') {
        await basemapReady
        if (current()) { layer.status = 'ready'; layer.progress = 100; layer.loadPhase = '底图已就绪'; appearance(layer) }
        return
      }
      let url = layer.url
      if (layer.asset_id && layer.asset_version) {
        const version = await getAssetVersion(layer.asset_id, layer.asset_version, entry.abort.signal)
        if (!current()) return
        if (version.status !== 'ready' || !version.entry_url)
          throw new ApiError('资产版本不可用', 409, { status: version.status }, 'ASSET_UNAVAILABLE', `client-${crypto.randomUUID()}`)
        url = version.entry_url
      }
      layer.loadPhase = '正在下载入口'
      if (layer.type === 'geojson') {
        let data = await fetchMapGeoJSON(url, entry.abort.signal, (loaded, total) => {
          if (!current()) return
          layer.progress = total > 0 ? Math.min(100, loaded / total * 100) : null
          layer.loadPhase = `已传输 ${loaded.toLocaleString()} 字节${total > 0 ? ` / ${total.toLocaleString()}` : ''}`
        })
        if (!current()) return
        if (layer.orderable === undefined && (layer.asset_source_kind === 'upload' || layer.asset_source_kind === 'default'))
          layer.orderable = planarGeoJSON(data)
        if (layer.asset_id && layer.asset_version && layer.object_count != null) {
          const identified = await identifyFeatures(data, layer.asset_id, layer.asset_version)
          data = identified.data
          entry.objectIds = identified.ids
          if (!current()) return
        }
        layer.loadPhase = '正在解析与贴地'
        pending = await GeoJsonDataSource.load(data, {
          clampToGround: true,
          stroke: Color.fromCssColorString(layer.color),
          strokeWidth: 4,
          fill: Color.fromCssColorString(layer.color).withAlpha(0.36),
          credit: /OSM|OpenStreetMap/.test(layer.source)
            ? new Credit(
                '© <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noopener">OpenStreetMap contributors · ODbL</a>',
                true,
              )
            : undefined,
        })
        if (!current()) return
        const buildings: { polygon: PolygonGraphics; height: number }[] = []
        for (const entity of pending.entities.values) {
          if (entity.billboard) {
            entity.billboard.image = new ConstantProperty(
              `data:image/svg+xml,${encodeURIComponent(`<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24"><circle cx="12" cy="12" r="8" fill="${layer.color}" stroke="white" stroke-width="3"/></svg>`)}`,
            )
            entity.billboard.width = new ConstantProperty(20)
            entity.billboard.height = new ConstantProperty(20)
            entity.billboard.verticalOrigin = new ConstantProperty(VerticalOrigin.BOTTOM)
            entity.billboard.heightReference = new ConstantProperty(HeightReference.CLAMP_TO_TERRAIN)
            entity.billboard.disableDepthTestDistance = new ConstantProperty(0)
          }
          if (entity.polyline) {
            entity.polyline.clampToGround = new ConstantProperty(true)
            entity.polyline.classificationType = new ConstantProperty(
              ClassificationType.TERRAIN,
            )
          }
          if (entity.polygon) {
            entity.polygon.outline = new ConstantProperty(false)
            entity.polygon.classificationType = new ConstantProperty(
              ClassificationType.TERRAIN,
            )
            const height = entity.properties?.map_extrude_height_m?.getValue(
              viewer.clock.currentTime,
            )
            if (
              typeof height === 'number' &&
              Number.isFinite(height) &&
              height > 0 &&
              height <= 1000
            ) {
              buildings.push({ polygon: entity.polygon, height })
            }
          }
        }
        if (buildings.length) {
          await basemapReady
          if (!current()) return
          const bounds = await sampleBuildingTerrain(
            buildings.map((building) => building.polygon),
            viewer.terrainProvider,
            viewer.clock.currentTime,
          )
          if (!current()) return
          for (const [index, { polygon, height }] of buildings.entries()) {
            // Explicit ellipsoid elevations avoid live single-point ground offsets.
            polygon.height = new ConstantProperty(
              bounds[index]!.maximum + height,
            )
            polygon.extrudedHeight = new ConstantProperty(
              bounds[index]!.minimum - 0.1,
            )
            polygon.heightReference = new ConstantProperty(HeightReference.NONE)
            polygon.extrudedHeightReference = new ConstantProperty(
              HeightReference.NONE,
            )
            polygon.perPositionHeight = new ConstantProperty(false)
            polygon.closeTop = new ConstantProperty(true)
            polygon.closeBottom = new ConstantProperty(true)
          }
        }
        await viewer.dataSources.add(pending)
        if (!current()) {
          if (alive) viewer.dataSources.remove(pending, true)
          return
        }
      } else {
        if (layer.asset_id && layer.asset_version && layer.object_count != null)
          entry.objectIds = [await objectIdentity(layer.asset_id, layer.asset_version, -1)]
        if (!current()) return
        pending = await Cesium3DTileset.fromUrl(url, {
          maximumScreenSpaceError: 16,
        })
        if (!current()) {
          pending.destroy()
          return
        }
        viewer.scene.primitives.add(pending)
        entry.cleanup.push(pending.tileFailed.addEventListener((error) => {
          if (current()) {
            const cause = mapLoadError(error)
            layer.status = 'error'
            layer.error = `三维内容加载失败：${cause.message}`
            layer.traceId = cause.traceId
            layer.errorCode = cause.code
          }
        }), pending.loadProgress.addEventListener((requests, processing) => {
          if (!current() || layer.status === 'error') return
          layer.progress = null
          layer.loadPhase = requests || processing ? `待下载 ${requests}，处理中 ${processing}` : '当前视野内容已就绪'
        }), pending.initialTilesLoaded.addEventListener(() => {
          if (!current() || layer.status === 'error') return
          layer.status = 'ready'; layer.progress = 100; layer.loadPhase = '当前视野内容已就绪'
        }))
        entry.cleanup.push(pending.tileUnload.addEventListener(() => {
          if (current() && highlightLayerId === layer.id && !entry.objectIds?.length) {
            highlightObjects(null, [])
            onPick(null)
          }
        }))
        layer.loadPhase = '正在加载当前视野瓦片'
      }
      entry.resource = pending
      syncOrder([...entries.keys()])
      if (pending instanceof GeoJsonDataSource) { layer.status = 'ready'; layer.progress = 100; layer.loadPhase = '已加载' }
      appearance(layer)
      if (layer.id === 'campus-buildings' && layer.builtin && homeRegion?.sampleKey
        && (!layer.campus || layer.campus === homeRegion.sampleKey)) homeResource = pending
      if (autoFrame && (!layer.builtin || layer.id === 'campus-buildings')) {
        autoFrame = false
        homeResource = pending
        void locate(layer)
      }
    } catch (error) {
      if (current()) {
        if (pending) disposeResource(pending)
        const cause = mapLoadError(error)
        layer.status = 'error'
        layer.error = `数据加载失败：${cause.message}`
        layer.traceId = cause.traceId
        layer.errorCode = cause.code
      }
    }
  }

  async function locate(layer: MapLayer) {
    const resource = entries.get(layer)?.resource
    if (!resource || !alive) return
    try {
      if (resource instanceof Cesium3DTileset) {
        viewer.camera.flyToBoundingSphere(resource.boundingSphere, {
          duration: 1.1, offset: new HeadingPitchRange(0, CesiumMath.toRadians(-48), Math.max(resource.boundingSphere.radius * 2.5, 50)),
          complete: () => navigation(true),
        })
        return
      }
      await viewer.flyTo(resource, {
        duration: 1.1,
        offset: new HeadingPitchRange(0, CesiumMath.toRadians(-48), 0),
      })
      navigation(true)
    } catch {
      if (alive) onNotice('该图层没有可定位的有效空间范围。')
    }
  }

  const handler = new ScreenSpaceEventHandler(viewer.scene.canvas)
  handler.setInputAction((event: { endPosition: Cartesian2 }) => {
    if (!alive) return
    if (areaMode === 'box' && boxStart) {
      const points = boxPoints(event.endPosition)
      if (points) drawDraft([...points, points[0]!])
    } else if (areaMode === 'polygon' && areaPoints.length) {
      const point = groundPoint(event.endPosition)
      if (point) drawDraft([...areaPoints, point])
    }
    pointerPosition = event.endPosition
    navigation()
  }, ScreenSpaceEventType.MOUSE_MOVE)
  handler.setInputAction((event: { position: Cartesian2 }) => {
    if (!alive) return
    if (areaMode) {
      if (areaMode === 'polygon') {
        const point = groundPoint(event.position)
        if (point) { areaPoints.push(point); drawDraft(areaPoints) }
        else onNotice('此处没有可选择的地面，请在地面添加顶点。')
      }
      return
    }
    if (pointPicking) {
      const ray = viewer.camera.getPickRay(event.position)
      const target =
        (ray && viewer.scene.globe.pick(ray, viewer.scene)) ??
        viewer.camera.pickEllipsoid(event.position, viewer.scene.globe.ellipsoid)
      if (!target) {
        onNotice('此处没有可选择的地面，请点击地面重新选择。')
        return
      }
      const coordinates = Cartographic.fromCartesian(target)
      const point = {
        longitude: CesiumMath.toDegrees(coordinates.longitude),
        latitude: CesiumMath.toDegrees(coordinates.latitude),
      }
      const callback = pointPicking
      pointPicking = undefined
      showPoint(point)
      callback(point)
      return
    }
    const picked = viewer.scene.pick(event.position)
    if (picked?.id && [...replayEntities.values()].some(item => item.entity === picked.id)) return
    if (picked?.id && simulationEntities.includes(picked.id)) {
      const identity = simulationEdges.get(picked.id)
      if (identity) simulationPick?.(identity)
      return
    }
    if (!picked || (pointMarker && picked.id === pointMarker)) {
      highlightObjects(null, [])
      onPick(null)
      return
    }
    if (picked.id instanceof Entity) {
      const entity = picked.id as Entity
      if (boundary?.entities.contains(entity)) {
        highlightObjects(null, [])
        onPick(null)
        return
      }
      const layer = [...entries].find(
        ([, entry]) =>
          entry.resource instanceof GeoJsonDataSource &&
          entry.resource.entities.contains(entity),
      )?.[0]
      const properties =
        entity.properties?.getValue(viewer.clock.currentTime) ?? {}
      delete properties.map_extrude_height_m
      const objectId = entityObjectId(layer ? entries.get(layer) : undefined, entity)
      if (layer && objectId) highlightObjects(layer.id, [objectId], objectId)
      else {
        highlightObjects(layer?.id ?? null, [])
        paintEntity(entity, '#f59e0b', layer?.opacity ?? 1)
      }
      onPick({
        title: String(properties['名称'] ?? properties.name ?? entity.name ?? '矢量对象'),
        layerName: layer?.name ?? '矢量图层',
        properties,
        ...(objectId ? { objectId } : {}),
        ...(layer ? { layerId: layer.id, resourceType: layer.type } : {}),
        ...(layer?.asset_id && layer.asset_version ? { asset: { asset_id: layer.asset_id, version: layer.asset_version } } : {}),
      })
    } else {
      const layer = [...entries].find(
        ([, entry]) =>
          entry.resource instanceof Cesium3DTileset && (entry.resource === picked.tileset ||
          entry.resource === picked.primitive ||
          entry.resource === picked.content?.tileset),
      )?.[0]
      const properties: Record<string, unknown> = {}
      if (typeof picked.getPropertyIds === 'function')
        for (const id of picked.getPropertyIds())
          properties[id] = picked.getProperty(id)
      const objectId = layer ? entries.get(layer)?.objectIds?.[0] : undefined
      if (layer && objectId) highlightObjects(layer.id, [objectId], objectId)
      else {
        highlightObjects(layer?.id ?? null, [])
        if ('color' in picked) changeHighlight(picked, 'color', Color.fromCssColorString('#f59e0b'))
      }
      onPick({
        title: '三维对象',
        layerName: layer?.name ?? '3D Tiles',
        properties,
        ...(objectId ? { objectId } : {}),
        ...(layer ? { layerId: layer.id, resourceType: layer.type } : {}),
        ...(layer?.asset_id && layer.asset_version ? { asset: { asset_id: layer.asset_id, version: layer.asset_version } } : {}),
      })
    }
  }, ScreenSpaceEventType.LEFT_CLICK)
  handler.setInputAction((event: { position: Cartesian2 }) => {
    if (alive && areaMode === 'box') boxStart = event.position
  }, ScreenSpaceEventType.LEFT_DOWN)
  handler.setInputAction((event: { position: Cartesian2 }) => {
    if (!alive || areaMode !== 'box') return
    const points = boxPoints(event.position)
    if (!points) { onNotice('框选范围需要覆盖有效地面，请重新拖动。'); return }
    areaPoints = points
    finishAreaSelection()
  }, ScreenSpaceEventType.LEFT_UP)

  function zoom(direction: number) {
    autoFrame = false
    const distance = Math.max(
      viewer.camera.positionCartographic.height * 0.4,
      30,
    )
    if (direction > 0) viewer.camera.zoomIn(distance)
    else viewer.camera.zoomOut(distance)
    viewer.scene.requestRender()
  }
  function setMode(twoD: boolean) {
    autoFrame = false
    if (twoD) viewer.scene.morphTo2D(0.6)
    else viewer.scene.morphTo3D(0.6)
  }
  function tilt() {
    autoFrame = false
    if (viewer.scene.mode !== SceneMode.SCENE3D) return
    const center = new Cartesian2(
      viewer.scene.canvas.clientWidth / 2,
      viewer.scene.canvas.clientHeight / 2,
    )
    const ray = viewer.camera.getPickRay(center)
    const target =
      (ray && viewer.scene.globe.pick(ray, viewer.scene)) ??
      viewer.camera.pickEllipsoid(center, viewer.scene.globe.ellipsoid)
    if (!target) {
      onNotice('画面中心没有可定位的地面，请先将目标移到画面中心。')
      return
    }
    viewer.camera.flyToBoundingSphere(new BoundingSphere(target, 1), {
      offset: new HeadingPitchRange(
        viewer.camera.heading,
        CesiumMath.toRadians(
          viewer.camera.pitch < CesiumMath.toRadians(-45) ? -30 : -65,
        ),
        Math.max(Cartesian3.distance(viewer.camera.positionWC, target), 30),
      ),
      duration: 0.6,
    })
    viewer.scene.requestRender()
  }
  function destroy() {
    if (!alive) return
    cancelAreaSelection()
    highlightObjects(null, [])
    cancelPointPicking()
    showSimulation(null)
    showReplay({ baseline: null, blocked: null })
    alive = false
    boundaryVersion++
    boundaryAbort?.abort()
    for (const entry of entries.values()) { entry.version++; entry.abort.abort(); for (const cleanup of entry.cleanup) cleanup() }
    for (const cleanup of navigationCleanup) cleanup()
    viewer.scene.canvas.removeEventListener?.('pointerdown', stopAutoFrame)
    viewer.scene.canvas.removeEventListener?.('wheel', stopAutoFrame)
    viewer.scene.canvas.removeEventListener?.('mouseleave', clearPointer)
    entries.clear()
    handler.destroy()
    viewer.destroy()
  }
  return {
    resume() {
      if (alive) {
        viewer.resize()
        viewer.scene.requestRender()
      }
    },
    load,
    remove,
    appearance,
    highlightObjects,
    objectPage,
    focusObject,
    showSimulation,
    showReplay,
    showTemporal,
    syncOrder,
    locate,
    goToRegion,
    initialize(region: RegionTarget, camera?: CameraState) {
      homeRegion = region
      if (camera && setCamera(camera)) return
      goToRegion(region)
      autoFrame = true
    },
    home() {
      if (!alive) return
      if (homeResource && [...entries.values()].some(entry => entry.resource === homeResource)) {
        if (viewer.scene.mode !== SceneMode.SCENE3D) viewer.scene.morphTo3D(0)
        const layer = [...entries].find(([, entry]) => entry.resource === homeResource)?.[0]
        if (layer) void locate(layer)
      } else if (homeRegion) goToRegion(homeRegion)
    },
    getCamera,
    setCamera,
    north,
    beginPointPicking,
    beginAreaSelection,
    finishAreaSelection,
    cancelAreaSelection,
    cancelPointPicking,
    goToPoint,
    clearPoint: cancelPointPicking,
    setRegionBoundary,
    zoom,
    setMode,
    tilt,
    destroy,
  }
}
export type MapController = ReturnType<typeof createMapController>
