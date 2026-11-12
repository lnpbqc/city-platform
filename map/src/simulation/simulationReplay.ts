import type { NetworkRecord, PathResult, RunResult } from './simulationTypes'

export interface ReplayRoute { coordinates: number[][]; times: number[]; duration: number }

export function replayTimeline(network: NetworkRecord, result: RunResult) {
  const nodes = new Map(network.nodes.map(node => [node.id, node.coordinates]))
  const pair = (left: string, right: string) => JSON.stringify([left, right].sort())
  const edges = new Map(network.edges.map(edge => [pair(edge.source, edge.target), edge]))
  function route(value: PathResult | undefined): ReplayRoute | null {
    if (!value?.reachable) return null
    const coordinates = value.path.map(id => {
      const point = nodes.get(id)
      if (!point) throw new Error(`回放节点不存在：${id}`)
      return point
    })
    const duration = value.duration_s ?? 0
    const times = [0]
    for (let index = 1; index < value.path.length; index++) {
      const edge = edges.get(pair(value.path[index - 1]!, value.path[index]!))
      if (!edge) throw new Error(`回放边不存在：${value.path[index - 1]}→${value.path[index]}`)
      times.push(times.at(-1)! + edge.length_m / edge.speed_mps)
    }
    const total = times.at(-1)!
    return { coordinates, duration, times: total ? times.map(time => time * duration / total) : times }
  }
  const baseline = route(result.baseline), blocked = route(result.blocked)
  return { baseline, blocked, duration: Math.max(baseline?.duration ?? 0, blocked?.duration ?? 0),
    ticks: [...new Set([0, ...baseline?.times ?? [], ...blocked?.times ?? []])].sort((left, right) => left - right) }
}

export function replayPosition(route: ReplayRoute | null, seconds: number): number[] | null {
  if (!route?.coordinates.length) return null
  if (seconds <= 0) return route.coordinates[0]!
  if (seconds >= route.duration || route.coordinates.length === 1) return route.coordinates.at(-1)!
  let low = 0, high = route.times.length - 2
  while (low < high) {
    const middle = Math.floor((low + high) / 2)
    if (seconds > route.times[middle + 1]!) low = middle + 1
    else high = middle
  }
  const start = route.coordinates[low]!, end = route.coordinates[low + 1]!
  const ratio = (seconds - route.times[low]!) / (route.times[low + 1]! - route.times[low]!)
  let delta = end[0]! - start[0]!
  if (delta > 180) delta -= 360
  if (delta < -180) delta += 360
  let longitude = start[0]! + delta * ratio
  if (longitude >= 180) longitude -= 360
  if (longitude < -180) longitude += 360
  const position = [longitude, start[1]! + (end[1]! - start[1]!) * ratio]
  if (start.length > 2 || end.length > 2) position.push((start[2] ?? 0) + ((end[2] ?? 0) - (start[2] ?? 0)) * ratio)
  return position
}

export function replayStep(ticks: number[], seconds: number, direction: number) {
  if (direction > 0) return ticks.find(time => time > seconds + 1e-7) ?? ticks.at(-1) ?? 0
  for (let index = ticks.length - 1; index >= 0; index--)
    if (ticks[index]! < seconds - 1e-7) return ticks[index]!
  return ticks[0] ?? 0
}
