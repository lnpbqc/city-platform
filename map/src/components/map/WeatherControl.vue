<script setup lang="ts">
import { computed, ref, useId, watch } from 'vue'
import { ChevronDown, Cloud, CloudFog, CloudLightning, CloudRain, CloudSnow, CloudSun, Moon, Sun, X } from '@lucide/vue'
import { automaticWeather, manualWeatherLabels, weatherLabel, type WeatherMode, type WeatherReading, type WeatherSnapshot, type WeatherStatus } from '../../map/weather'

const props = defineProps<{ mode: WeatherMode; weather: WeatherSnapshot; status: WeatherStatus; region?: string;
  reference?: WeatherReading | null; fixed?: boolean; compact?: boolean }>()
const emit = defineEmits<{ 'update:mode': [mode: WeatherMode] }>()
const open = ref(false)
const root = ref<HTMLElement>()
const toggle = ref<HTMLButtonElement>()
const contentId = `weather-${useId()}`
const condition = computed(() => {
  if (props.weather.source === 'open-meteo') return weatherLabel(props.weather.reading.code)
  if (props.weather.source === 'manual') return manualWeatherLabels[props.weather.effect]
  if (props.fixed) return '未显示天气'
  return { hidden: '天气', outside: '未进入展示区域', loading: '正在查询天气…', ready: '暂无天气', limited: '天气服务限流', unavailable: '天气暂不可用' }[props.status]
})
const place = computed(() => props.fixed ? '运行天气' : props.weather.source === 'manual' ? '' : props.region)
const modeLabel = computed(() => props.fixed ? props.weather.source === 'manual' ? '手动' : props.weather.source === 'open-meteo' ? '自动' : '历史'
  : props.mode === 'auto' ? '自动' : '手动')
const icon = computed(() => {
  const weather = props.weather
  if (weather.source === 'open-meteo' && !weather.reading.is_day && weather.reading.code <= 1) return Moon
  const effect = weather.source === 'open-meteo' ? automaticWeather(weather.reading).effect : weather.effect
  return { none: Cloud, clear: Sun, cloudy: CloudSun, overcast: Cloud, fog: CloudFog, rain: CloudRain, snow: CloudSnow, thunderstorm: CloudLightning }[effect]
})
function close(restoreFocus = false) {
  if (!open.value) return
  open.value = false
  if (restoreFocus) toggle.value?.focus()
}
watch(open, (value, _previous, onCleanup) => {
  if (!value || !root.value) return
  const document = root.value.ownerDocument
  const outside = (event: PointerEvent) => { if (!root.value?.contains(event.target as Node)) close() }
  document.addEventListener('pointerdown', outside)
  onCleanup(() => document.removeEventListener('pointerdown', outside))
}, { flush: 'post' })
const formatTime = new Intl.DateTimeFormat('zh-CN', {
  timeZone: 'Asia/Shanghai', month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit', hourCycle: 'h23',
})
</script>

<template>
  <div ref="root" class="weather-control panel" :class="{ compact, 'weather-open': open }" aria-label="地图天气" @keydown.esc.stop.prevent="close(true)">
    <button v-if="compact" ref="toggle" class="weather-toggle" type="button" aria-label="天气设置" :aria-expanded="open" :aria-controls="contentId" @click="open = !open">
      <component :is="icon" :size="18" aria-hidden="true" />
      <span class="weather-summary"><span v-if="place" class="weather-place">{{ place }} ·</span><span class="weather-condition">{{ condition }}</span></span>
      <span class="weather-mode">{{ modeLabel }}</span><ChevronDown :size="14" aria-hidden="true" />
    </button>
    <div :id="contentId" v-show="!compact || open" class="weather-content" role="group" aria-label="天气设置内容">
      <header v-if="compact"><strong>天气设置</strong><button type="button" aria-label="关闭天气设置" @click="close(true)"><X :size="16" aria-hidden="true" /></button></header>
      <label v-if="!fixed" class="weather-choice">天气模式
        <select :value="mode" aria-label="天气模式" @change="emit('update:mode', ($event.target as HTMLSelectElement).value as WeatherMode)">
          <option value="auto">自动</option>
          <option v-for="(label, value) in manualWeatherLabels" :key="value" :value="value">{{ label }}</option>
        </select>
      </label>
      <div v-if="weather.source === 'open-meteo'" class="weather-reading">
        <strong>{{ fixed ? '运行天气' : region }} · {{ weatherLabel(weather.reading.code) }}</strong>
        <div class="weather-meta">
          <span>数据时间（北京时间）</span>
          <time :datetime="weather.reading.valid_at" title="数据时间（北京时间）">{{ formatTime.format(new Date(weather.reading.valid_at)) }}</time>
          <a href="https://open-meteo.com/" target="_blank" rel="noopener noreferrer">Open-Meteo</a>
        </div>
      </div>
      <span v-else-if="fixed">{{ weather.source === 'manual' ? `运行天气 · 手动${manualWeatherLabels[weather.effect]}` : '运行未显示天气' }}</span>
      <span v-else-if="weather.source === 'manual'">手动天气 · {{ manualWeatherLabels[weather.effect] }}</span>
      <span v-else-if="mode === 'auto' && status === 'outside'" role="status">未进入展示区域</span>
      <span v-else-if="mode === 'auto' && status === 'loading'" role="status">{{ region }} · 正在查询天气…</span>
      <div v-else-if="mode === 'auto' && (status === 'limited' || status === 'unavailable')" class="weather-reading" role="status">
        {{ region }} · {{ status === 'limited' ? '天气服务限流' : '天气暂不可用' }}
        <div v-if="reference" class="weather-meta">
          <span>上次更新 · {{ weatherLabel(reference.code) }}</span>
          <time :datetime="reference.valid_at" title="数据时间（北京时间）">{{ formatTime.format(new Date(reference.valid_at)) }}</time>
          <a href="https://open-meteo.com/" target="_blank" rel="noopener noreferrer">Open-Meteo</a>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.weather-control { position: relative; width: fit-content; max-width: min(100%, 280px); padding: 10px 12px; color: #334155; font-size: 12px; line-height: 1.5; overflow-wrap: anywhere; }
.compact { padding: 0; }
.weather-open { z-index: 7; }
.weather-choice, .weather-meta { display: flex; align-items: center; gap: 7px; }
.weather-choice { justify-content: space-between; margin-bottom: 10px; }
select { min-height: 36px; padding: 4px 8px; border: 1px solid var(--line); border-radius: 4px; color: #29405a; background: white; font: inherit; }
select:focus-visible, a:focus-visible, button:focus-visible { outline: 2px solid var(--blue); outline-offset: 2px; }
.weather-reading, .weather-content > span { display: block; margin-top: 3px; }
.weather-reading strong { display: block; font-weight: 600; font-size: 14px; }
.weather-meta a { color: var(--blue); }
.weather-meta { flex-wrap: wrap; margin-top: 6px; color: #64748b; }
.weather-toggle { display: flex; align-items: center; gap: 7px; height: 44px; max-width: 100%; padding: 0 10px; color: #334155; font-size: 12px; }
.weather-toggle > svg { flex-shrink: 0; }
.weather-summary { display: flex; align-items: center; gap: 4px; min-width: 0; overflow: hidden; }
.weather-place, .weather-condition { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.weather-place { flex: 1 1 auto; min-width: 0; }
.weather-condition { flex: 0 1 auto; }
.weather-mode { flex-shrink: 0; padding: 1px 5px; border-radius: 4px; background: #eff6ff; color: #1d4ed8; }
.compact .weather-content { position: absolute; top: calc(100% + 8px); right: 0; width: 280px; max-width: calc(100vw - 24px); max-height: calc(100svh - 180px); overflow-y: auto; box-sizing: border-box; padding: 12px; border: 1px solid var(--line); border-radius: 8px; background: white; box-shadow: 0 4px 16px #29405a26; }
.weather-content > header { display: flex; align-items: center; justify-content: space-between; gap: 8px; margin-bottom: 8px; }
.weather-content > header button { width: 36px; height: 36px; border-radius: 5px; }
@media (max-width: 767px) {
  .compact .weather-content { right: auto; left: 0; }
  .weather-content > header button, select { min-height: 44px; }
  .weather-content > header button { width: 44px; }
}
</style>
