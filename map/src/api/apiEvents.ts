import type { ApiError } from './api'

export interface ApiEvent { reachable?: boolean; error?: ApiError }
const listeners = new Set<(event: ApiEvent) => void>()
export function subscribeApiEvents(listener: (event: ApiEvent) => void) {
  listeners.add(listener)
  return () => { listeners.delete(listener) }
}
export function publishApiEvent(event: ApiEvent) { for (const listener of listeners) listener(event) }
