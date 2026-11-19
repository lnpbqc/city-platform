import assert from 'node:assert/strict'
import { test } from 'node:test'
import { effectScope, nextTick, ref } from 'vue'
import { useWeatherView } from '../src/composables/useWeatherView.ts'
import { matchDisplayRegion } from '../src/map/displayRegions.ts'
import { automaticWeather, manualWeatherLabels, weatherLabel } from '../src/map/weather.ts'

const west = { id: 'west', name: '西区', latitude: 23.04, longitude: 113.36, radius_m: 2200 }
const east = { id: 'east', name: '东区', latitude: 23.06, longitude: 113.38, radius_m: 2200 }
const regions = () => [west, east]

test('automatic weather preserves detailed labels and maps seven categories without losing night or unknown states', () => {
  const cases = [[0, 'clear'], [1, 'clear'], [2, 'cloudy'], [3, 'overcast'], [45, 'fog'], [48, 'fog'],
    [51, 'rain'], [65, 'rain'], [67, 'rain'], [71, 'snow'], [86, 'snow'], [95, 'thunderstorm'], [99, 'thunderstorm']]
  for (const [code, effect] of cases) {
    const reading = { ...west, code, is_day: true, valid_at: '2026-11-19T07:00:00Z' }
    assert.deepEqual(automaticWeather(reading), { source: 'open-meteo', effect, reading })
  }
  assert.equal(weatherLabel(65), '大雨')
  assert.equal(weatherLabel(86), '强阵雪')
  assert.equal(weatherLabel(99), '雷雨伴冰雹')
  assert.equal(automaticWeather({ code: 0, is_day: false }).effect, 'none')
  assert.equal(automaticWeather({ code: 4, is_day: true }).effect, 'none')
  assert.equal(weatherLabel(4), '未知天气')
})

test('all seven manual weather categories follow between views without querying the weather service', t => {
  const request = t.mock.method(globalThis, 'fetch', () => { throw new Error('manual weather must not query') })
  const scope = effectScope()
  const weather = scope.run(() => useWeatherView(() => null, () => true, regions))
  t.after(() => { weather.mode.value = 'auto'; scope.stop() })
  assert.deepEqual(Object.keys(manualWeatherLabels), ['clear', 'cloudy', 'overcast', 'fog', 'rain', 'snow', 'thunderstorm'])
  const other = scope.run(() => useWeatherView(() => null, () => true, regions))
  for (const effect of Object.keys(manualWeatherLabels)) {
    weather.mode.value = effect
    assert.deepEqual(weather.display.value, { source: 'manual', effect })
    assert.deepEqual(other.display.value, weather.display.value)
  }
  assert.equal(request.mock.callCount(), 0)
})

test('display regions match by ground distance, with nearest winning in overlaps', () => {
  assert.equal(matchDisplayRegion({ latitude: 23.045, longitude: 113.365 }, regions()), west)
  assert.equal(matchDisplayRegion({ latitude: 23.055, longitude: 113.375 }, regions()), east)
  assert.equal(matchDisplayRegion({ latitude: 24, longitude: 113.37 }, regions()), null)
  assert.equal(matchDisplayRegion(null, regions()), null)
})

test('weather waits for the latest settled view, spaces misses, caches cells and refreshes', async t => {
  t.mock.timers.enable({ apis: ['setTimeout', 'Date'], now: 1_800_000_000_000 })
  const calls = []
  t.mock.method(globalThis, 'fetch', (url, { signal }) => new Promise(resolve => {
    const query = new URL(url, 'http://local').searchParams
    calls.push({ signal, resolve, latitude: +query.get('lat'), longitude: +query.get('lon') })
  }))
  const tick = async ms => { t.mock.timers.tick(ms); await nextTick() }
  const answer = async (index, code) => {
    const { resolve, latitude, longitude } = calls[index]
    resolve({ ok: true, json: async () => ({ latitude, longitude, code, is_day: true, valid_at: new Date().toISOString() }) })
    await Promise.resolve()
    await Promise.resolve()
    await nextTick()
  }
  const scope = effectScope()
  t.after(() => scope.stop())
  const enabled = ref(true)
  let point = null
  const weather = scope.run(() => useWeatherView(() => point, () => enabled.value, regions))
  await tick(600)
  assert.equal(calls.length, 0)
  assert.equal(weather.status.value, 'hidden')
  point = { latitude: 23.031, longitude: 113.362 }
  weather.settled()
  await tick(599)
  assert.equal(calls.length, 0)
  weather.moving()
  point = { latitude: 23.038, longitude: 113.363 }
  weather.settled()
  await tick(600)
  assert.deepEqual([calls[0].latitude, calls[0].longitude], [23.04, 113.36])
  weather.moving()
  point = { latitude: 23.056, longitude: 113.38 }
  weather.settled()
  assert.equal(calls[0].signal.aborted, true)
  await answer(0, 71)
  assert.equal(weather.display.value.effect, 'none', 'late response cannot display snow')
  await tick(4_999)
  assert.equal(calls.length, 1)
  await tick(1)
  assert.equal(calls.length, 2)
  await answer(1, 61)
  assert.equal(weather.display.value.effect, 'rain')
  weather.moving()
  assert.equal(weather.display.value.effect, 'none', 'weather from the previous center cannot be captured while moving')
  enabled.value = false
  enabled.value = true
  point = { latitude: 25, longitude: 115 }
  weather.resized()
  await tick(5_000)
  assert.equal(calls.length, 2, 'reactivating the view does not treat an unfinished camera move as settled')
  weather.settled()
  assert.equal(weather.status.value, 'outside')
  weather.moving()
  point = { latitude: 23.059, longitude: 113.38 }
  weather.settled()
  await tick(600)
  assert.equal(calls.length, 2)
  assert.equal(weather.display.value.effect, 'rain')
  await tick(594_400)
  assert.equal(calls.length, 3)
  calls[2].resolve({ ok: false, status: 503, headers: new Headers({ 'Retry-After': '60' }) })
  await nextTick()
  assert.equal(weather.status.value, 'unavailable')
  assert.equal(weather.reference.value.code, 61)
  assert.equal(weather.display.value.effect, 'none')
  weather.mode.value = 'snow'
  await nextTick()
  assert.deepEqual(weather.display.value, { source: 'manual', effect: 'snow' })
  const other = scope.run(() => useWeatherView(() => null, () => true, regions))
  assert.deepEqual(other.display.value, weather.display.value, 'the same manual mode follows between views')
  weather.mode.value = 'auto'
  await nextTick()
  enabled.value = false
  await tick(610_000)
  assert.equal(calls.length, 3, 'inactive views do not refresh')
})

test('a move inside a region shares the pending sample, and rate limiting delays every new sample', async t => {
  t.mock.timers.enable({ apis: ['setTimeout', 'Date'], now: 1_900_000_000_000 })
  const calls = []
  t.mock.method(globalThis, 'fetch', (url, { signal }) => new Promise(resolve => calls.push({ url, signal, resolve })))
  const tick = async ms => { t.mock.timers.tick(ms); await nextTick() }
  const scope = effectScope()
  t.after(() => scope.stop())
  let point = west
  const weather = scope.run(() => useWeatherView(() => point, () => true, regions))
  await tick(600)
  assert.equal(calls[0].url, '/api/weather/current?lat=23.04&lon=113.36')
  weather.moving()
  point = { latitude: 23.047, longitude: 113.366 }
  weather.settled()
  assert.equal(calls[0].signal.aborted, false)
  calls[0].resolve({ ok: false, status: 429, headers: new Headers({ 'Retry-After': '90' }) })
  await nextTick()
  assert.equal(weather.status.value, 'limited')
  weather.moving()
  point = east
  weather.settled()
  await tick(89_999)
  assert.equal(calls.length, 1)
  await tick(1)
  assert.equal(calls[1].url, '/api/weather/current?lat=23.06&lon=113.38')
  calls[1].resolve({ ok: true, json: async () => ({ ...east, code: 71, is_day: true, valid_at: new Date().toISOString() }) })
  await new Promise(setImmediate)
  assert.equal(weather.display.value.effect, 'snow')
})
