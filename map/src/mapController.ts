import {
  Viewer,
  Math as CesiumMath,
  Cartesian2,
  Cartesian3,
  Cartographic,
  Color,
  GeoJsonDataSource,
  Cesium3DTileset,
  Cesium3DTileStyle,
  ColorMaterialProperty,
  PolylineOutlineMaterialProperty,
  ConstantProperty,
  ConstantPositionProperty,
  VerticalOrigin,
  HorizontalOrigin,
  LabelStyle,
  HeightReference,
  ScreenSpaceEventHandler,
  ScreenSpaceEventType,
  Entity,
  SceneMode,
  HeadingPitchRange,
  BoundingSphere,
  ClassificationType,
  Credit,
  EllipsoidGeodesic,
  LabelGraphics,
} from 'cesium'
import type { MapLayer, Selection, GeometryDocument, ObjectRecord, MapViewportFeature } from './types'
import type { PolygonGraphics, TerrainProvider } from 'cesium'
import type { RegionTarget } from './regions'
import { fetchRegionBoundary, type BoundaryState } from './regionBoundary.ts'
import { initializeBasemap } from './basemap.ts'
import { sampleBuildingTerrain, type TerrainBounds } from './buildingTerrain.ts'
import { ApiError, getAssetVersion, getMapViewport, pickMapRoad } from './api.ts'
import { fetchMapGeoJSON, mapLoadError, planarGeoJSON } from './mapResource.ts'
import { validCamera, scaleForDistance, type CameraState, type NavigationReading } from './mapNavigation.ts'
import { objectIdentity, identifyFeatures } from './objectIdentity.ts'
import { simulationGeometry } from './simulationGeometry.ts'
import type { NetworkRecord, RunResult } from './simulationTypes'
import type { TimeSeriesRecord } from './temporalTypes'
import { temporalColor } from './temporal.ts'
import { poiCategory, poiIcon, poiName, propertyText, roadLevel } from './poi.ts'
import { layoutPois, type PoiAnchor } from './poiLayout.ts'

type Resource = GeoJsonDataSource | Cesium3DTileset
type Building = { polygon: PolygonGraphics; height: number }
type BuildingPlacement = {
  items: Building[]
  // Terrain samples per provider, so switching back and forth does not request them again.
  bounds: Map<TerrainProvider, Promise<TerrainBounds[]>>
  placed?: TerrainProvider
}
type Entry = { version: number; resource?: Resource; abort: AbortController; cleanup: (() => void)[]; objectIds?: string[]; temporal?: TimeSeriesRecord | null; buildings?: BuildingPlacement
  viewport?: boolean; viewAbort?: AbortController; viewVersion?: number; weights?: Map<string, number>
  bounds?: { west: number; south: number; east: number; north: number } | null
  viewportVisible?: boolean
  viewportKey?: string
  styles?: Map<string, MapViewportFeature['__display']>; sources?: Map<string, string[]>
}

export interface MapPoint {
  longitude: number
  latitude: number
}

export interface MapControllerOptions {
  /** Show ion world terrain when it is available; defaults to true. */
  terrain?: boolean
  onGroundClick?: (point: MapPoint) => void
}

export function createMapController(
  container: HTMLElement,
  onPick: (selection: Selection | null) => void,
  onNotice: (message: string) => void,
  onBoundaryState: (state: BoundaryState) => void = () => {},
  onNavigation: (state: NavigationReading, settled: boolean) => void = () => {},
  options: MapControllerOptions = {},
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
  // A viewer created without terrain starts on the flat WGS84 ellipsoid.
  const flatTerrain = viewer.terrainProvider
  let worldTerrain: TerrainProvider | undefined
  let terrainEnabled = options.terrain ?? true
  const entries = new Map<MapLayer, Entry>()
  let alive = true
  let boundaryVersion = 0
  let boundaryAbort: AbortController | undefined
  let boundary: GeoJsonDataSource | undefined
  let pointMarker: Entity | undefined
  let pointPicking: ((point: MapPoint) => void) | undefined
  let selectedOverlay: Entity | undefined
  let selectedOverlayLayer: string | undefined
  let selectedOverlayObject: ObjectRecord | undefined
  let pickVersion = 0
  let roadPickAbort: AbortController | undefined
  const poiAnchors = new Map<string, PoiAnchor>()
  const labelCanvas = container.ownerDocument?.createElement('canvas')
  const labelContext = labelCanvas?.getContext?.('2d')
  if (labelContext) labelContext.font = '12px sans-serif'
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
  const simulationPaths = new Map<Entity, { coordinates: number[][]; edgeIds: string[] }>()
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
                          onEdge?: (identity: string) => void, endpoints: { origin?: string; destination?: string; selectedNode?: string } = {}) {
    for (const entity of simulationEntities) viewer.entities.remove(entity)
    simulationEntities.length = 0
    simulationEdges.clear()
    simulationPaths.clear()
    simulationPick = onEdge
    if (!network || !alive) { viewer.scene.requestRender(); return }
    const geometry = simulationGeometry(network, blocked, result)
    const point = (coordinates: number[]) => Cartesian3.fromDegrees(coordinates[0]!, coordinates[1]!, coordinates[2] ?? 0)
    const add = (options: NonNullable<ConstructorParameters<typeof Entity>[0]>, edgeId?: string) => {
      const entity = viewer.entities.add(options)
      simulationEntities.push(entity)
      if (edgeId) simulationEdges.set(entity, edgeId)
      return entity
    }
    const line = (coordinates: number[][], color: string, width: number, role: string, edgeId: string) => add({
      polyline: { positions: coordinates.map(point), width, material: Color.fromCssColorString(color),
        clampToGround: coordinates.every(position => position.length === 2) },
      properties: { simulation_role: role, edge_id: edgeId },
    }, edgeId)
    for (const edge of geometry.edges)
      line(edge.coordinates, edge.blocked ? '#dc2626' : '#64748b', edge.blocked ? 5 : 3, 'network', edge.id)
    for (const path of geometry.paths) {
      if (path.coordinates.length > 1) {
        const entity = add({ polyline: { positions: path.coordinates.map(point), width: path.role === 'baseline' ? 9 : 4,
          material: Color.fromCssColorString(path.color), clampToGround: path.coordinates.every(position => position.length === 2) },
          properties: { simulation_role: path.role } })
        simulationPaths.set(entity, { coordinates: path.coordinates, edgeIds: path.edgeIds })
      }
      if (path.coordinates.length === 1) add({ position: point(path.coordinates[0]!),
        point: { pixelSize: path.role === 'baseline' ? 22 : 12, color: Color.fromCssColorString(path.color), heightReference: HeightReference.CLAMP_TO_TERRAIN } })
    }
    const important = new Set([endpoints.origin ?? geometry.paths[0]?.path[0] ?? network.nodes[0]?.id,
      endpoints.destination ?? geometry.paths[0]?.path.at(-1) ?? network.nodes.at(-1)?.id, endpoints.selectedNode])
    for (const edge of network.edges) if (blocked.includes(edge.id)) { important.add(edge.source); important.add(edge.target) }
    for (const node of network.nodes) add({ position: point(node.coordinates),
      point: { pixelSize: 7, color: Color.WHITE, outlineColor: Color.fromCssColorString('#334155'), outlineWidth: 2, heightReference: HeightReference.CLAMP_TO_TERRAIN },
      ...(important.has(node.id) ? { label: { text: node.id, font: '14px sans-serif', fillColor: Color.fromCssColorString('#0f172a'),
        showBackground: true, backgroundColor: Color.WHITE.withAlpha(0.9), pixelOffset: new Cartesian2(0, -20), heightReference: HeightReference.CLAMP_TO_TERRAIN } } : {}) })
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
        const sources = entry.sources?.get(id) ?? [id]
        if (sources.some(source => highlightIds.has(source))) paintEntity(entity, activeObjectId && sources.includes(activeObjectId) ? '#f59e0b' : '#22c3ee', layer.opacity)
      }
    } else if (resource && entry.objectIds?.some(id => highlightIds.has(id))) {
      changeHighlight(resource, 'style', new Cesium3DTileStyle({ color: `color('${activeObjectId ? '#f59e0b' : '#22c3ee'}', ${layer.opacity})` }))
    }
    viewer.scene.requestRender()
  }
  function highlightObjects(layerId: string | null, ids: string[], activeId?: string) {
    if (!layerId) { pickVersion++; roadPickAbort?.abort() }
    if (selectedOverlay && (selectedOverlayLayer !== layerId || selectedOverlayObject?.object_id !== activeId)) clearSelectedOverlay()
    highlightLayerId = layerId
    highlightIds = new Set(ids)
    activeObjectId = activeId
    paintHighlights()
    declutterPois()
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
    if (layer.category === 'POI' && object.coordinates?.length) {
      showSelectedPoi(layerId, object)
      if (!selectedOverlay) return
      await viewer.flyTo(selectedOverlay, { duration: 0.8, offset: new HeadingPitchRange(0, CesiumMath.toRadians(-55), 400) })
      viewer.scene.requestRender()
      return
    }
    const entities = entry.resource!.entities.values.filter(entity => entityObjectId(entry, entity) === object.object_id
      || entry.sources?.get(entity.id.split('_')[0]!)?.includes(object.object_id))
    if (!entities.length || !object.geometry) { onNotice('对象未提供可定位的几何。'); return }
    try {
      const located = await viewer.flyTo(entities, { duration: 0.8, offset: new HeadingPitchRange(0, CesiumMath.toRadians(-55), object.type === 'point' ? 400 : 0) })
      if (!located && alive) onNotice('对象未提供可定位的几何。')
      navigation(true)
    } catch { if (alive) onNotice('对象定位失败，请重试或定位所属图层。') }
  }

  function clearSelectedOverlay() {
    if (selectedOverlay) viewer.entities.remove(selectedOverlay)
    selectedOverlay = undefined
    selectedOverlayLayer = undefined
    selectedOverlayObject = undefined
  }

  function showSelectedPoi(layerId: string | null, object: ObjectRecord | null) {
    clearSelectedOverlay()
    const layer = [...entries.keys()].find(item => item.id === layerId)
    if (!alive || !layer?.attached || !layer.visible || layer.category !== 'POI' || !object?.coordinates?.length
      || layer.asset_id !== object.asset.asset_id || layer.asset_version !== object.asset.version) return
    selectedOverlayLayer = layerId!
    selectedOverlayObject = object
    selectedOverlay = viewer.entities.add({
      id: `selected-poi-${object.object_id}`,
      position: Cartesian3.fromDegrees(object.coordinates[0]!, object.coordinates[1]!, 0),
      point: { pixelSize: 15, color: Color.fromCssColorString('#f59e0b'), outlineColor: Color.WHITE, outlineWidth: 3,
        heightReference: HeightReference.CLAMP_TO_TERRAIN, disableDepthTestDistance: 0 },
    })
    viewer.scene.requestRender()
  }

  function declutterPois() {
    const candidates: Parameters<typeof layoutPois>[0] = []
    const entities = new Map<string, Entity>()
    for (const [layer, entry] of entries) {
      if (layer.category !== 'POI' || !(entry.resource instanceof GeoJsonDataSource)) continue
      const temporalIds = entry.temporal === undefined ? null : new Set(entry.temporal?.items.filter(item => !item.missing).map(item => item.object_id) ?? [])
      for (const entity of entry.resource.entities.values) {
        const objectId = entityObjectId(entry, entity) ?? entity.id
        if (!layer.attached || !layer.visible || temporalIds && !temporalIds.has(objectId)) { entity.show = false; continue }
        const position = entity.position?.getValue(viewer.clock.currentTime)
        const screen = position && viewer.scene.cartesianToCanvasCoordinates?.(position)
        if (!screen) { entity.show = false; continue }
        const id = `${layer.id}:${entity.id}`
        const text = entry.styles?.get(objectId)?.name ?? String(entity.label?.text?.getValue(viewer.clock.currentTime) ?? '')
        candidates.push({ id, x: screen.x, y: screen.y, text, weight: entry.weights?.get(objectId) ?? 0,
          priority: entry.styles?.get(objectId)?.priority ?? 0, selected: objectId === activeObjectId && layer.id === highlightLayerId, iconSize: 16 })
        entities.set(id, entity)
      }
    }
    const layout = layoutPois(candidates, poiAnchors, text => labelContext?.measureText(text).width ?? text.length * 12)
    poiAnchors.clear()
    for (const item of layout) {
      const entity = entities.get(item.id)!
      entity.show = item.visible
      if (entity.label) {
        entity.label.show = new ConstantProperty(item.visible && item.labelVisible)
        entity.label.pixelOffset = new ConstantProperty(new Cartesian2(item.anchor === 'right' ? 12 : item.anchor === 'left' ? -12 : 0, item.anchor === 'top' ? -12 : 0))
        entity.label.horizontalOrigin = new ConstantProperty(item.anchor === 'right' ? HorizontalOrigin.LEFT : item.anchor === 'left' ? HorizontalOrigin.RIGHT : HorizontalOrigin.CENTER)
        entity.label.verticalOrigin = new ConstantProperty(item.anchor === 'top' ? VerticalOrigin.BOTTOM : VerticalOrigin.CENTER)
      }
      if (item.visible && item.labelVisible) poiAnchors.set(item.id, item.anchor)
    }
    viewer.scene.requestRender()
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
    viewer.camera.moveEnd.addEventListener(() => { navigation(true); refreshViewports() }),
    viewer.scene.morphComplete.addEventListener(() => { navigation(true); refreshViewports() })]
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

  function applyTerrain() {
    const target = terrainEnabled && worldTerrain ? worldTerrain : flatTerrain
    if (!alive || viewer.terrainProvider === target) return false
    viewer.terrainProvider = target
    viewer.scene.requestRender()
    return true
  }
  const basemapReady = initializeBasemap(viewer, {
    VITE_BASEMAP_PROVIDER: import.meta.env?.VITE_BASEMAP_PROVIDER,
    VITE_TIANDITU_KEY: import.meta.env?.VITE_TIANDITU_KEY,
    VITE_CESIUM_ION_TOKEN: import.meta.env?.VITE_CESIUM_ION_TOKEN,
  }, () => alive, onNotice).then((terrain) => {
    worldTerrain = terrain
    applyTerrain()
  })

  function entryCurrent(layer: MapLayer, entry: Entry) {
    return alive && entries.get(layer) === entry && entry.version === 0
  }
  /** Places white models on the active terrain, sampling again if terrain changes meanwhile. */
  async function placeBuildings(buildings: BuildingPlacement, current: () => boolean) {
    while (current()) {
      const terrain = viewer.terrainProvider
      if (buildings.placed === terrain) return false
      let sampling = buildings.bounds.get(terrain)
      if (!sampling) {
        sampling = sampleBuildingTerrain(
          buildings.items.map((building) => building.polygon),
          terrain,
          viewer.clock.currentTime,
        )
        buildings.bounds.set(terrain, sampling)
        // Failed samples are not cached; the next switch or reload samples again.
        sampling.catch(() => { if (buildings.bounds.get(terrain) === sampling) buildings.bounds.delete(terrain) })
      }
      const bounds = await sampling
      if (!current()) return false
      if (viewer.terrainProvider !== terrain) continue
      for (const [index, { polygon, height }] of buildings.items.entries()) {
        // Explicit ellipsoid elevations avoid live single-point ground offsets.
        polygon.height = new ConstantProperty(bounds[index]!.maximum + height)
        polygon.extrudedHeight = new ConstantProperty(bounds[index]!.minimum - 0.1)
        polygon.heightReference = new ConstantProperty(HeightReference.NONE)
        polygon.extrudedHeightReference = new ConstantProperty(HeightReference.NONE)
        polygon.perPositionHeight = new ConstantProperty(false)
        polygon.closeTop = new ConstantProperty(true)
        polygon.closeBottom = new ConstantProperty(true)
      }
      buildings.placed = terrain
      return true
    }
    return false
  }
  /** Re-places an attached white model layer after a terrain switch; keeps the model on failure. */
  async function refreshEntryBuildings(layer: MapLayer, entry: Entry) {
    const buildings = entry.buildings
    if (!entry.resource || !buildings) return
    const current = () => entryCurrent(layer, entry)
    try {
      if (await placeBuildings(buildings, current)) viewer.scene.requestRender()
    } catch (error) {
      if (!current()) return
      const cause = mapLoadError(error)
      layer.status = 'error'
      layer.error = `地形切换后白模高度更新失败：${cause.message}`
      layer.traceId = cause.traceId
      layer.errorCode = cause.code
    }
  }
  async function refreshBuildingHeights() {
    await Promise.all([...entries].map(([layer, entry]) => refreshEntryBuildings(layer, entry)))
  }
  async function setTerrain(enabled: boolean) {
    terrainEnabled = enabled
    await basemapReady
    if (!alive || terrainEnabled !== enabled) return
    if (applyTerrain()) await refreshBuildingHeights()
  }

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
    const viewportEntry = entries.get(layer)
    if (viewportEntry?.viewport && viewportEntry.viewportVisible !== layer.visible) {
      const wasVisible = viewportEntry.viewportVisible
      viewportEntry.viewportVisible = layer.visible
      if (wasVisible === false && layer.visible) void refreshViewport(layer, viewportEntry)
      if (!layer.visible) { viewportEntry.viewAbort?.abort(); if (selectedOverlayLayer === layer.id) clearSelectedOverlay() }
    }
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
        if (layer.category === 'POI' && entity.label) {
          entity.label.fillColor = new ConstantProperty(Color.fromCssColorString('#304459').withAlpha(layer.opacity))
          entity.label.outlineColor = new ConstantProperty(Color.WHITE.withAlpha(layer.opacity))
        }
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
        if (entity.polyline) {
          const properties = entity.properties?.getValue?.(viewer.clock.currentTime) ?? {}
          if (layer.category === '道路' || propertyText(properties, 'highway'))
            styleRoad(entity, layer, entries.get(layer)?.styles?.get(entity.id.split('_')[0]!)?.road_rank)
          else entity.polyline.material = new ColorMaterialProperty(color.withAlpha(layer.opacity))
        }
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
    if (selectedOverlayLayer === layer.id && selectedOverlay && !layer.visible) clearSelectedOverlay()
    declutterPois()
  }

  function styleRoad(entity: Entity, layer: MapLayer, rank?: number) {
    if (!entity.polyline) return
    const level = roadLevel(entity.properties?.getValue?.(viewer.clock.currentTime) ?? {})
    const resolved = rank ?? (/^(motorway|trunk|primary)/.test(level) ? 0 : /^(secondary|tertiary)/.test(level) ? 1 : /^(residential|unclassified|living_street)$/.test(level) ? 2 : 3)
    entity.polyline.width = new ConstantProperty([6, 4, 2.5, 1.5][resolved] ?? 2.5)
    entity.polyline.material = new PolylineOutlineMaterialProperty({
      color: Color.fromCssColorString(resolved === 0 ? '#efce80' : resolved === 1 ? '#fff5d7' : '#f7fafc').withAlpha(layer.opacity),
      outlineColor: Color.fromCssColorString('#718096').withAlpha(layer.opacity * 0.75), outlineWidth: 1,
    })
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
    if (selectedOverlayLayer === layer.id) clearSelectedOverlay()
    if (highlightLayerId === layer.id) { highlightObjects(null, []); onPick(null) }
    const entry = entries.get(layer)
    if (entry) {
      entry.version++
      entry.abort.abort()
      entry.viewAbort?.abort()
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

  async function createGeoResource(layer: MapLayer, entry: Entry, data: unknown, current: () => boolean) {
    const styles = new Map((data as { features?: MapViewportFeature[] })?.features?.map(feature => [feature.id, feature.__display]) ?? [])
    const pending = await GeoJsonDataSource.load(data, {
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
    const buildings: Building[] = []
    for (const entity of pending.entities.values) {
      const properties = entity.properties?.getValue?.(viewer.clock.currentTime) ?? {}
      if (entity.billboard) {
        const isPoi = layer.category === 'POI'
        const style = styles.get(entity.id.split('_')[0]!)
        entity.billboard.image = new ConstantProperty(
          isPoi ? poiIcon(style?.poi_category ?? poiCategory(properties)) : `data:image/svg+xml,${encodeURIComponent(`<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24"><circle cx="12" cy="12" r="8" fill="${layer.color}" stroke="white" stroke-width="3"/></svg>`)}`,
        )
        entity.billboard.width = new ConstantProperty(isPoi ? 16 : 20)
        entity.billboard.height = new ConstantProperty(isPoi ? 16 : 20)
        entity.billboard.verticalOrigin = new ConstantProperty(isPoi ? VerticalOrigin.CENTER : VerticalOrigin.BOTTOM)
        entity.billboard.heightReference = new ConstantProperty(HeightReference.CLAMP_TO_TERRAIN)
        entity.billboard.disableDepthTestDistance = new ConstantProperty(0)
        const name = isPoi && (style?.name ?? poiName(properties))
        if (name) entity.label = new LabelGraphics({
          text: name, font: '12px sans-serif', showBackground: false,
          fillColor: Color.fromCssColorString('#304459'), outlineColor: Color.WHITE, outlineWidth: 2, style: LabelStyle.FILL_AND_OUTLINE,
          heightReference: HeightReference.CLAMP_TO_TERRAIN,
          pixelOffset: new Cartesian2(12, 0), horizontalOrigin: HorizontalOrigin.LEFT, verticalOrigin: VerticalOrigin.CENTER,
        })
      }
      if (entity.polyline) {
        if (layer.category === '道路' || layer.id === 'demo-roads' || propertyText(properties, 'highway'))
          styleRoad(entity, layer, styles.get(entity.id.split('_')[0]!)?.road_rank)
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
    entry.buildings = undefined
    if (buildings.length) {
      entry.buildings = { items: buildings, bounds: new Map() }
      await basemapReady
      if (!current()) return
      await placeBuildings(entry.buildings, current)
      if (!current()) return
    }
    await viewer.dataSources.add(pending)
    if (!current()) {
      if (alive) viewer.dataSources.remove(pending, true)
      return
    }
    return pending
  }

  function viewportBounds(): [number, number, number, number] {
    const rectangle = viewer.camera.computeViewRectangle?.(viewer.scene.globe.ellipsoid)
    return rectangle ? [CesiumMath.toDegrees(rectangle.west), CesiumMath.toDegrees(rectangle.south),
      CesiumMath.toDegrees(rectangle.east), CesiumMath.toDegrees(rectangle.north)] : [-180, -90, 180, 90]
  }

  function metersPerPixel() {
    const canvas = viewer.scene.canvas
    const y = canvas.clientHeight * 0.6
    const first = groundAt(new Cartesian2(canvas.clientWidth / 2 - 50, y))
    const second = groundAt(new Cartesian2(canvas.clientWidth / 2 + 50, y))
    if (first && second) {
      const distance = new EllipsoidGeodesic(Cartographic.fromCartesian(first), Cartographic.fromCartesian(second), viewer.scene.globe.ellipsoid).surfaceDistance
      if (Number.isFinite(distance) && distance > 0) return distance / 100
    }
    const fovy = (viewer.camera.frustum as { fovy?: number } | undefined)?.fovy ?? Math.PI / 3
    return Math.max(0.01, 2 * viewer.camera.positionCartographic.height * Math.tan(fovy / 2) / Math.max(canvas.clientHeight, 1))
  }

  async function refreshViewport(layer: MapLayer, entry: Entry) {
    const request = { layer_id: layer.id, asset_id: layer.asset_id!, version: layer.asset_version!,
      ...(layer.campus ? { campus: layer.campus } : {}), bbox: viewportBounds(), meters_per_pixel: metersPerPixel(),
      width: Math.max(1, viewer.scene.canvas.clientWidth), height: Math.max(1, viewer.scene.canvas.clientHeight) }
    const key = JSON.stringify(request)
    if (entry.viewportKey === key && !entry.viewAbort?.signal.aborted) return
    entry.viewportKey = key
    entry.viewAbort?.abort()
    const abort = new AbortController()
    entry.viewAbort = abort
    const version = (entry.viewVersion ?? 0) + 1
    entry.viewVersion = version
    const current = () => entryCurrent(layer, entry) && entry.viewVersion === version && !abort.signal.aborted
    let pending: GeoJsonDataSource | undefined
    try {
      layer.loadPhase = '正在读取当前视野'
      const data = await getMapViewport(request, abort.signal)
      if (!current()) return
      pending = await createGeoResource(layer, entry, data, current)
      if (!current() || !pending) return
      restoreHighlights()
      const previous = entry.resource
      entry.resource = pending
      entry.objectIds = data.features.map(feature => feature.__object.object_id)
      entry.weights = new Map(data.features.map(feature => [feature.__object.object_id, feature.__object.weight]))
      entry.styles = new Map(data.features.map(feature => [feature.id, feature.__display]))
      entry.sources = new Map(data.features.filter(feature => feature.__object.source_object_ids?.length)
        .map(feature => [feature.id, feature.__object.source_object_ids!]))
      if (previous) disposeResource(previous)
      layer.status = 'ready'; layer.progress = 100; layer.error = ''
      layer.loadPhase = data.truncated ? '当前视野较密，请放大地图查看更多' : '当前视野已就绪'
      syncOrder([...entries.keys()])
      appearance(layer)
    } catch (error) {
      if (!current()) return
      entry.viewportKey = undefined
      const cause = mapLoadError(error)
      layer.status = 'error'; layer.error = `视野数据加载失败：${cause.message}`
      layer.traceId = cause.traceId; layer.errorCode = cause.code
    } finally {
      if (pending && pending !== entry.resource) disposeResource(pending)
    }
  }

  function refreshViewports() {
    for (const [layer, entry] of entries) if (entry.viewport && layer.attached && layer.visible) void refreshViewport(layer, entry)
    declutterPois()
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
    const current = () => entryCurrent(layer, entry)
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
        entry.bounds = version.bounds
      }
      if (layer.type === 'geojson' && layer.asset_id && layer.asset_version && layer.object_count != null
        && (url.startsWith('/data-files/') || url.startsWith('/samples/'))) {
        entry.viewport = true
        await refreshViewport(layer, entry)
        if (current() && autoFrame && (!layer.builtin || layer.id === 'campus-buildings')) {
          autoFrame = false
          if (entry.resource) homeResource = entry.resource
          void locate(layer)
        }
        return
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
        pending = await createGeoResource(layer, entry, data, current)
        if (!current() || !pending) return
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
      // Terrain may have switched while the data source was being inserted.
      if (entry.buildings && entry.buildings.placed !== viewer.terrainProvider) void refreshEntryBuildings(layer, entry)
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
    const entry = entries.get(layer)
    const resource = entry?.resource
    if (!resource || !alive) return
    try {
      if (entry.viewport && entry.bounds) {
        const bounds = entry.bounds
        const longitude = (bounds.west + bounds.east) / 2, latitude = (bounds.south + bounds.north) / 2
        const radius = Math.max(100, 111320 * Math.hypot((bounds.east - bounds.west) * Math.cos(latitude * Math.PI / 180), bounds.north - bounds.south) / 2)
        viewer.camera.flyToBoundingSphere(new BoundingSphere(Cartesian3.fromDegrees(longitude, latitude, 0), radius), {
          duration: 1.1, offset: new HeadingPitchRange(0, CesiumMath.toRadians(-48), radius * 2.5), complete: () => { navigation(true); refreshViewports() },
        })
        return
      }
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
    const requestVersion = ++pickVersion
    roadPickAbort?.abort()
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
      let identity = simulationEdges.get(picked.id)
      const path = simulationPaths.get(picked.id)
      if (path) {
        let nearest = Infinity
        for (let index = 0; index < path.edgeIds.length; index++) {
          const start = viewer.scene.cartesianToCanvasCoordinates?.(Cartesian3.fromDegrees(...path.coordinates[index] as [number, number, number?]))
          const end = viewer.scene.cartesianToCanvasCoordinates?.(Cartesian3.fromDegrees(...path.coordinates[index + 1] as [number, number, number?]))
          if (!start || !end) continue
          const dx = end.x - start.x, dy = end.y - start.y
          const ratio = Math.max(0, Math.min(1, ((event.position.x - start.x) * dx + (event.position.y - start.y) * dy) / (dx * dx + dy * dy || 1)))
          const distance = (event.position.x - start.x - ratio * dx) ** 2 + (event.position.y - start.y - ratio * dy) ** 2
          if (distance < nearest) { nearest = distance; identity = path.edgeIds[index] }
        }
        identity ??= path.edgeIds[0]
      }
      if (identity) simulationPick?.(identity)
      return
    }
    if (!picked || (pointMarker && picked.id === pointMarker)) {
      highlightObjects(null, [])
      onPick(null)
      const point = groundPoint(event.position)
      if (point) options.onGroundClick?.(point)
      return
    }
    if (selectedOverlay && picked.id === selectedOverlay && selectedOverlayObject) {
      const layer = [...entries.keys()].find(item => item.id === selectedOverlayLayer)
      if (layer) onPick({ title: selectedOverlayObject.name ?? 'POI', layerName: layer.name,
        layerId: layer.id, objectId: selectedOverlayObject.object_id, object: selectedOverlayObject,
        asset: selectedOverlayObject.asset, properties: selectedOverlayObject.properties, resourceType: layer.type })
      return
    }
    if (picked.id instanceof Entity) {
      const entity = picked.id as Entity
      if (boundary?.entities.contains(entity)) {
        highlightObjects(null, [])
        onPick(null)
        const point = groundPoint(event.position)
        if (point) options.onGroundClick?.(point)
        return
      }
      const layer = [...entries].find(
        ([, entry]) =>
          entry.resource instanceof GeoJsonDataSource &&
          entry.resource.entities.contains(entity),
      )?.[0]
      const entry = layer ? entries.get(layer) : undefined
      const sourceIds = entry?.sources?.get(entity.id.split('_')[0]!)
      if (layer && entry && sourceIds && sourceIds.length > 1) {
        const point = groundPoint(event.position)
        if (!point) { onNotice('此处没有可确定的地面位置，请重新点击道路。'); return }
        roadPickAbort = new AbortController()
        void pickMapRoad({ layer_id: layer.id, asset_id: layer.asset_id!, version: layer.asset_version!,
          ...(layer.campus ? { campus: layer.campus } : {}), object_ids: sourceIds, ...point }, roadPickAbort.signal).then(object => {
          if (!alive || requestVersion !== pickVersion || !entryCurrent(layer, entry)) return
          highlightObjects(layer.id, [object.object_id], object.object_id)
          onPick({ title: object.name ?? '道路', layerName: layer.name, layerId: layer.id, resourceType: layer.type,
            objectId: object.object_id, asset: object.asset, properties: object.properties, object })
        }).catch(cause => {
          if (alive && requestVersion === pickVersion && cause?.name !== 'AbortError') onNotice(`道路拾取失败：${mapLoadError(cause).message}`)
        })
        return
      }
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
    pickVersion++
    roadPickAbort?.abort()
    boundaryVersion++
    boundaryAbort?.abort()
    for (const entry of entries.values()) { entry.version++; entry.abort.abort(); entry.viewAbort?.abort(); for (const cleanup of entry.cleanup) cleanup() }
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
    showSelectedPoi,
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
    setTerrain,
    zoom,
    setMode,
    tilt,
    destroy,
  }
}
export type MapController = ReturnType<typeof createMapController>
