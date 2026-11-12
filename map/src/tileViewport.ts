import type { MapViewportResult, RenderDescriptor } from './types'

export interface TileView {
  bbox: [number, number, number, number]
  meters_per_pixel: number
  road_max_level?: number
  asset_id: string
  version: string
}

export type TileRender = Pick<RenderDescriptor, 'status' | 'url' | 'profile'> & { contains_roads: boolean }

export class TileViewport {
  private worker: Worker
  private sequence = 0
  private error?: Error
  private pending = new Map<number, { resolve: (data: MapViewportResult) => void; reject: (error: Error) => void }>()

  constructor() {
    this.worker = new Worker(new URL('./tileViewport.worker.ts', import.meta.url), { type: 'module' })
    this.worker.onmessage = event => {
      const { id, data, error } = event.data
      const pending = this.pending.get(id)
      if (!pending) return
      this.pending.delete(id)
      if (error) pending.reject(new Error(error))
      else pending.resolve(data)
    }
    this.worker.onerror = () => {
      this.error = new Error('瓦片解码进程异常')
      for (const item of this.pending.values()) item.reject(this.error)
      this.pending.clear()
    }
  }

  load(render: RenderDescriptor, view: TileView, signal: AbortSignal): Promise<MapViewportResult> {
    if (this.error) return Promise.reject(this.error)
    const id = ++this.sequence
    return new Promise((resolve, reject) => {
      const abort = () => {
        this.worker.postMessage({ cancel: id })
        this.pending.delete(id)
        reject(new DOMException('视野请求已取消', 'AbortError'))
      }
      if (signal.aborted) { abort(); return }
      signal.addEventListener('abort', abort, { once: true })
      const complete = (callback: () => void) => { signal.removeEventListener('abort', abort); callback() }
      this.pending.set(id, { resolve: data => complete(() => resolve(data)), reject: error => complete(() => reject(error)) })
      // Vue's reactive descriptors are proxies, which cannot cross a Worker boundary.
      const descriptor: TileRender = { status: render.status, url: render.url, profile: render.profile,
        contains_roads: render.profile === 'roads' || render.manifest?.contains_roads === true }
      const viewport = { bbox: [...view.bbox], asset_id: view.asset_id, version: view.version,
        meters_per_pixel: view.meters_per_pixel, road_max_level: view.road_max_level }
      try { this.worker.postMessage({ id, render: descriptor, view: viewport }) }
      catch (error) {
        this.pending.delete(id)
        complete(() => reject(error))
      }
    })
  }

  destroy() {
    this.error = new DOMException('图层已移除', 'AbortError')
    this.worker.terminate()
    for (const item of this.pending.values()) item.reject(this.error)
    this.pending.clear()
  }
}
