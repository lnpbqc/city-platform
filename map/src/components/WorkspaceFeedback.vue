<script setup lang="ts">
import { X, Info } from '@lucide/vue'
defineProps<{ notice: string; fatal: string; toast: string }>()
const emit = defineEmits<{ dismiss: [] }>()
function reload() {
  window.location.reload()
}
</script>

<template>
  <div v-if="notice" class="map-notice panel" role="status">
    <Info :size="17" /><span>{{ notice }}</span
    ><button
      class="icon-button"
      aria-label="关闭地图提示"
      @click="emit('dismiss')"
    >
      <X :size="15" />
    </button>
  </div>
  <div v-if="fatal" class="fatal-panel panel">
    <Info :size="28" />
    <h2>地图暂时无法启动</h2>
    <p>{{ fatal }}</p>
    <p>请使用支持 WebGL2 的浏览器，并确认硬件加速已开启。</p>
    <button class="primary-button" @click="reload">重新加载</button>
  </div>
  <div v-if="toast" class="toast" role="status">
    <span class="toast-dot"></span>{{ toast }}
  </div>
</template>

<style scoped>
.map-notice {
  position: absolute;
  bottom: 62px;
  left: 50%;
  transform: translateX(-50%);
  padding: 10px 12px;
  display: flex;
  align-items: center;
  gap: 10px;
  font-size: 11px;
  max-width: 560px;
  color: #90734c;
  z-index: 4;
  background: #fffcf6;
}
.map-notice > svg {
  color: #bc985e;
}
.map-notice span {
  line-height: 1.7;
}
.map-notice .icon-button {
  height: 22px;
  width: 22px;
  flex-shrink: 0;
}
.fatal-panel {
  position: absolute;
  top: 45%;
  left: 50%;
  transform: translate(-50%, -50%);
  z-index: 4;
  padding: 32px;
  max-width: 420px;
  text-align: center;
  display: flex;
  align-items: center;
  flex-direction: column;
  gap: 15px;
}
.fatal-panel h2 {
  font-size: 17px;
}
.fatal-panel p {
  font-size: 12px;
  line-height: 1.7;
  color: #8794a7;
}
.toast {
  position: absolute;
  top: 82px;
  left: 50%;
  transform: translateX(-50%);
  z-index: 20;
  border-radius: 7px;
  background: #263b50f5;
  box-shadow: 0 4px 20px #20344f22;
  color: white;
  font-size: 12px;
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 13px 20px;
  animation: toast-in 0.2s ease-out;
}
.toast-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: #7ec6b1;
}
@media (max-width: 900px) {
  .map-notice {
    max-width: calc(100% - 48px);
    bottom: 100px;
  }
}
@media (max-width: 600px) {
  .toast {
    top: 75px;
    font-size: 11px;
    max-width: calc(100% - 30px);
    width: max-content;
  }
  .map-notice {
    width: calc(100% - 24px);
    font-size: 10px;
    bottom: 100px;
  }
}
</style>
