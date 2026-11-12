export type PoiAnchor = 'right' | 'left' | 'top'
export interface PoiLayoutCandidate {
  id: string; x: number; y: number; text: string; weight: number; priority: number
  selected?: boolean; iconSize?: number
}
export interface PoiPlacement { id: string; visible: boolean; labelVisible: boolean; anchor: PoiAnchor }
type Box = { left: number; right: number; top: number; bottom: number }
const overlaps = (a: Box, b: Box) => a.left < b.right && a.right > b.left && a.top < b.bottom && a.bottom > b.top
const padded = (left: number, top: number, width: number, height: number): Box =>
  ({ left: left - 4, top: top - 4, right: left + width + 4, bottom: top + height + 4 })

/** Layout all enabled POI layers together; positions refer to icon centers. */
export function layoutPois(candidates: PoiLayoutCandidate[], previousAnchors: ReadonlyMap<string, PoiAnchor> = new Map(),
  measureText: (text: string) => number = text => [...text].length * 12): PoiPlacement[] {
  const occupied: Box[] = []
  const names: { text: string; x: number; y: number }[] = []
  const number = (value: number) => Number.isFinite(value) ? value : 0
  return [...candidates].sort((a, b) => Number(!!b.selected) - Number(!!a.selected) || number(b.weight) - number(a.weight)
    || number(b.priority) - number(a.priority) || a.id.localeCompare(b.id)).map(candidate => {
    const { id, x, y, text } = candidate
    const previous = previousAnchors.get(id) ?? 'right'
    const result: PoiPlacement = { id, visible: false, labelVisible: false, anchor: previous }
    if (!Number.isFinite(x) || !Number.isFinite(y)) return result
    const normalized = text.trim().toLocaleLowerCase()
    const duplicate = normalized && names.some(name => name.text === normalized && Math.hypot(x - name.x, y - name.y) < 80)
    const size = candidate.iconSize ?? 16
    const icon = padded(x - size / 2, y - size / 2, size, size)
    if (!candidate.selected && (duplicate || occupied.some(box => overlaps(icon, box)))) return result
    result.visible = true
    const width = measureText(text)
    const anchors: PoiAnchor[] = [previous, ...(['right', 'left', 'top'] as const).filter(anchor => anchor !== previous)]
    if (normalized) for (const anchor of anchors) {
      const label = anchor === 'top' ? padded(x - width / 2, y - 24, width, 12)
        : padded(anchor === 'right' ? x + 12 : x - 12 - width, y - 6, width, 12)
      if (occupied.some(box => overlaps(label, box))) continue
      result.labelVisible = true
      result.anchor = anchor
      occupied.push(label)
      break
    }
    occupied.push(icon)
    if (normalized) names.push({ text: normalized, x, y })
    return result
  })
}
