export type WeatherEffect = 'none' | 'clear' | 'rain' | 'snow'
export type WeatherMode = 'auto' | Exclude<WeatherEffect, 'none'>
export type WeatherStatus = 'hidden' | 'loading' | 'ready' | 'unavailable'

export interface WeatherPoint { latitude: number; longitude: number }
export interface WeatherReading extends WeatherPoint {
  code: number
  is_day: boolean
  valid_at: string
}
export type WeatherSnapshot =
  | { source: 'open-meteo'; effect: WeatherEffect; reading: WeatherReading }
  | { source: 'manual'; effect: Exclude<WeatherEffect, 'none'> }
  | { source: 'none'; effect: 'none' }

export const noWeather: WeatherSnapshot = { source: 'none', effect: 'none' }
export const manualWeatherLabels = { clear: '晴', rain: '雨', snow: '雪' }

const conditions: Record<number, [string, WeatherEffect]> = {
  0: ['晴朗', 'clear'], 1: ['大致晴朗', 'clear'], 2: ['局部多云', 'none'], 3: ['阴', 'none'],
  45: ['雾', 'none'], 48: ['冻雾', 'none'],
  51: ['毛毛雨', 'rain'], 53: ['毛毛雨', 'rain'], 55: ['毛毛雨', 'rain'],
  56: ['冻毛毛雨', 'rain'], 57: ['冻毛毛雨', 'rain'],
  61: ['小雨', 'rain'], 63: ['中雨', 'rain'], 65: ['大雨', 'rain'],
  66: ['冻雨', 'rain'], 67: ['冻雨', 'rain'],
  71: ['小雪', 'snow'], 73: ['中雪', 'snow'], 75: ['大雪', 'snow'], 77: ['霰', 'snow'],
  80: ['阵雨', 'rain'], 81: ['阵雨', 'rain'], 82: ['强阵雨', 'rain'],
  85: ['阵雪', 'snow'], 86: ['强阵雪', 'snow'],
  95: ['雷雨', 'rain'], 96: ['雷雨伴冰雹', 'rain'], 97: ['强雷雨', 'rain'], 99: ['雷雨伴冰雹', 'rain'],
}

export function weatherLabel(code: number) {
  return conditions[code]?.[0] ?? '未知天气'
}

export function automaticWeather(reading: WeatherReading): WeatherSnapshot {
  const effect = conditions[reading.code]?.[1] ?? 'none'
  return { source: 'open-meteo', effect: effect === 'clear' && !reading.is_day ? 'none' : effect, reading }
}
