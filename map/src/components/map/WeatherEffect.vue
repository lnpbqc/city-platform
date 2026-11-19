<script setup lang="ts">
import { onBeforeUnmount, ref, watch } from 'vue'
import type { WeatherEffect } from '../../map/weather'

const props = defineProps<{ effect: WeatherEffect }>()
const canvas = ref<HTMLCanvasElement>()
let frame = 0
function stop() { if (frame) cancelAnimationFrame(frame); frame = 0 }

watch([canvas, () => props.effect], ([element, effect]) => {
  stop()
  if (!element || (effect !== 'rain' && effect !== 'snow' && effect !== 'thunderstorm')) return
  const context = element.getContext('2d')
  if (!context) return
  const reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)')
  const snow = effect === 'snow'
  const storm = effect === 'thunderstorm'
  let previous = -Infinity
  function draw(time: number) {
    frame = requestAnimationFrame(draw)
    if (!element || !context || reducedMotion.matches || document.hidden || time - previous < 32) return
    previous = time
    const width = element.clientWidth, height = element.clientHeight
    if (!width || !height) return
    if (element.width !== width) element.width = width
    if (element.height !== height) element.height = height
    context.clearRect(0, 0, width, height)
    context.fillStyle = 'rgba(255, 255, 255, .74)'
    context.strokeStyle = 'rgba(213, 231, 246, .49)'
    context.beginPath()
    const count = Math.min(storm ? 200 : 140, Math.ceil(width * height / (storm ? 4500 : 7500)))
    for (let index = 0; index < count; index++) {
      const speed = snow ? 22 + index % 19 : 520 + (index % 7) * 48
      const seconds = time / 1000
      const x = ((index * 0.61803399 * width + seconds * (snow ? 9 : 108)) % width)
      const y = ((index * 0.38196601 * height + seconds * speed) % (height + 20)) - 20
      if (snow) {
        const radius = 1 + (index % 4) * .35
        context.moveTo(x + radius, y)
        context.arc(x, y, radius, 0, Math.PI * 2)
      } else {
        const length = 9 + index % 8
        context.moveTo(x, y)
        context.lineTo(x - length * .21, y - length)
      }
    }
    if (snow) context.fill()
    else context.stroke()
  }
  frame = requestAnimationFrame(draw)
}, { flush: 'post' })
onBeforeUnmount(stop)
</script>

<template>
  <div v-if="effect !== 'none'" class="weather-effect" :class="effect" aria-hidden="true">
    <canvas v-if="effect === 'rain' || effect === 'snow' || effect === 'thunderstorm'" ref="canvas" />
  </div>
</template>

<style scoped>
.weather-effect { position: absolute; inset: 0; z-index: 1; pointer-events: none; }
.weather-effect.clear { background: linear-gradient(145deg, #fff0c416, transparent 58%); }
.weather-effect.cloudy { overflow: hidden; }
.weather-effect.cloudy::before { content: ''; position: absolute; inset: -20%; background: radial-gradient(ellipse at 20% 30%, #52698520, transparent 45%), radial-gradient(ellipse at 75% 60%, #52698518, transparent 40%); animation: cloud-drift 45s ease-in-out infinite alternate; }
.weather-effect.overcast { background: #53657925; }
.weather-effect.fog { background: linear-gradient(180deg, #e5edf54d, #edf2f51a 60%, #e5edf533); }
.weather-effect.rain { background: #253c591b; }
.weather-effect.snow { background: #e6f4ff14; }
.weather-effect.thunderstorm { background: #1c2c4340; }
canvas { display: block; width: 100%; height: 100%; }
@keyframes cloud-drift { from { transform: translateX(-4%); } to { transform: translateX(4%); } }
@media (prefers-reduced-motion: reduce) { canvas { visibility: hidden; } .weather-effect.cloudy::before { animation: none; } }
</style>
