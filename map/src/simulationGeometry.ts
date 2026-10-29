import type { NetworkRecord, RunResult } from './simulationTypes'

export function simulationGeometry(network: NetworkRecord, blocked: string[], result: RunResult | null) {
  const nodes = new Map(network.nodes.map(node => [node.id, node.coordinates]))
  const pair = (left: string, right: string) => JSON.stringify([left, right].sort())
  const pairs = new Map(network.edges.map(edge => [pair(edge.source, edge.target), edge.id]))
  const coordinates = (id: string) => {
    const position = nodes.get(id)
    if (!position) throw new Error(`路线节点不存在：${id}`)
    return position
  }
  const blockedIds = new Set(blocked)
  const edges = network.edges.map(edge => {
    const start = coordinates(edge.source), end = coordinates(edge.target)
    const longitude = start[0]! + ((end[0]! - start[0]! + 540) % 360 - 180) / 2
    return { ...edge, coordinates: [start, end], blocked: blockedIds.has(edge.id),
      midpoint: [((longitude + 540) % 360) - 180, (start[1]! + end[1]!) / 2] }
  })
  const paths = (['baseline', 'blocked'] as const).flatMap(role => {
    const route = result?.[role]
    if (!route?.reachable) return []
    return [{ role, color: role === 'baseline' ? '#2563eb' : '#f59e0b', path: route.path,
      coordinates: route.path.map(coordinates), edgeIds: route.path.slice(1).map((node, index) => {
        const edge = pairs.get(pair(route.path[index]!, node))
        if (!edge) throw new Error(`路线边不存在：${route.path[index]}→${node}`)
        return edge
      }) }]
  })
  return { edges, paths }
}
