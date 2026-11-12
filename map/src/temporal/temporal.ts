import type { TimeResolution } from './temporalTypes'

const calendar = new Intl.DateTimeFormat('en-CA', { timeZone: 'Asia/Shanghai', year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', second: '2-digit', hourCycle: 'h23' })
function parts(time: string | number) {
  return Object.fromEntries(calendar.formatToParts(new Date(time)).filter(part => part.type !== 'literal').map(part => [part.type, Number(part.value)])) as Record<'year' | 'month' | 'day' | 'hour' | 'minute' | 'second', number>
}
export function localDay(time: string | number) {
  const date = parts(time)
  return Date.UTC(date.year, date.month - 1, date.day)
}
export function dayTime(day: number) {
  let instant = day - 8 * 3600000
  for (let attempt = 0; attempt < 3; attempt++) {
    const date = parts(instant)
    const local = Date.UTC(date.year, date.month - 1, date.day, date.hour, date.minute, date.second)
    const next = day - (local - instant)
    if (next === instant) break
    instant = next
  }
  return new Date(instant).toISOString()
}
export const normalizedTime = (time: string, resolution: TimeResolution) => resolution === 'day' ? dayTime(localDay(time)) : new Date(time).toISOString()
export function localTime(value: string) {
  const values = value.match(/^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})(?::(\d{2}))?$/)
  return values ? dayTime(Date.UTC(Number(values[1]), Number(values[2]) - 1, Number(values[3]), Number(values[4]), Number(values[5]), Number(values[6] ?? 0))) : ''
}
export function timeLabel(time: string, resolution: TimeResolution = 'hour') {
  if (!time) return '时间未选择'
  const date = parts(time)
  const pad = (value: number) => String(value).padStart(2, '0')
  const day = `${date.year}-${pad(date.month)}-${pad(date.day)}`
  return resolution === 'day' ? day : `${day} ${pad(date.hour)}:${pad(date.minute)}:${pad(date.second)}`
}
export function temporalColor(value: number, unit: string) {
  if (value === 0) return '#dbeafe'
  const [low, high] = unit === '辆/小时' ? [100, 300] : [10, 30]
  return value <= low! ? '#93c5fd' : value <= high! ? '#3b82f6' : '#1d4ed8'
}
