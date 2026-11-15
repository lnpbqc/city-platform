<script setup lang="ts">
import { ref } from 'vue'
import { manualWeatherLabels, weatherLabel, type WeatherMode, type WeatherSnapshot, type WeatherStatus } from '../../map/weather'

defineProps<{ mode: WeatherMode; weather: WeatherSnapshot; status: WeatherStatus; fixed?: boolean; compact?: boolean }>()
const emit = defineEmits<{ 'update:mode': [mode: WeatherMode] }>()
const open = ref(false)
const toggle = ref<HTMLButtonElement>()
function close() {
  if (!open.value) return
  open.value = false
  toggle.value?.focus()
}
const formatTime = new Intl.DateTimeFormat('zh-CN', {
  timeZone: 'Asia/Shanghai', month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit', hourCycle: 'h23',
})
</script>

<template>
  <div class="weather-control panel" :class="{ compact, 'weather-open': open }" aria-label="地图天气" @keydown.esc="close">
    <button v-if="compact" ref="toggle" class="weather-toggle" type="button" aria-label="天气设置" :aria-expanded="open" @click="open = !open">
      {{ weather.effect === 'none' ? '天气' : manualWeatherLabels[weather.effect] }}
    </button>
    <div class="weather-content">
      <label v-if="!fixed" class="weather-choice">天气
        <select :value="mode" aria-label="天气模式" @change="emit('update:mode', ($event.target as HTMLSelectElement).value as WeatherMode)">
          <option value="auto">自动</option>
          <option v-for="(label, value) in manualWeatherLabels" :key="value" :value="value">{{ label }}</option>
        </select>
      </label>
      <div v-if="weather.source === 'open-meteo'" class="weather-reading">
        <strong>{{ fixed ? '运行天气' : '镜头中心天气' }} · {{ weatherLabel(weather.reading.code) }}</strong>
        <div class="weather-meta">
          <time :datetime="weather.reading.valid_at" title="数据时间（北京时间）">{{ formatTime.format(new Date(weather.reading.valid_at)) }}</time>
          <a href="https://open-meteo.com/" target="_blank" rel="noopener noreferrer">Open-Meteo</a>
        </div>
      </div>
      <span v-else-if="fixed">{{ weather.source === 'manual' ? `运行天气 · 手动${manualWeatherLabels[weather.effect]}` : '运行未显示天气' }}</span>
      <span v-else-if="mode === 'auto' && status === 'loading'" role="status">正在查询天气…</span>
      <span v-else-if="mode === 'auto' && status === 'unavailable'" role="status">当前天气暂不可用</span>
    </div>
  </div>
</template>

<style scoped>
.weather-control { width: fit-content; max-width: 100%; padding: 6px 9px; color: #465d76; font-size: 11px; line-height: 1.5; }
.weather-choice, .weather-meta { display: flex; align-items: center; gap: 7px; }
select { padding: 2px 4px; border: 1px solid var(--line); border-radius: 4px; color: #29405a; background: white; font: inherit; }
select:focus-visible, a:focus-visible, button:focus-visible { outline: 2px solid var(--blue); outline-offset: 2px; }
.weather-reading, .weather-content > span { display: block; margin-top: 3px; }
.weather-reading strong { font-weight: 500; }
.weather-meta a { color: var(--blue); }
.weather-toggle { display: none; }
@media (max-width: 760px) {
  .compact { padding: 0; }
  .compact .weather-toggle { display: block; width: 44px; height: 40px; font-size: 11px; color: var(--blue); }
  .compact .weather-content {
    display: none; position: absolute; top: 0; right: calc(100% + 6px); width: max-content; max-width: 180px;
    padding: 8px 10px; border: 1px solid var(--line); border-radius: 6px; background: white; box-shadow: 0 4px 16px #29405a26;
  }
  .compact.comparing .weather-content { right: auto; left: calc(100% + 6px); }
  .compact.weather-open .weather-content { display: block; }
}
</style>
