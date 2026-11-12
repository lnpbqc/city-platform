<script setup lang="ts">
import { X, ArrowUpRight } from '@lucide/vue'
defineProps<{ open: boolean }>()
const emit = defineEmits<{ close: [] }>()
</script>

<template>
  <aside v-if="open" class="help-panel panel">
    <header>
      <h2>浏览与数据</h2>
      <button class="icon-button" aria-label="关闭帮助" @click="emit('close')">
        <X :size="17" />
      </button>
    </header>
    <p>
      左键拖动平移，滚轮缩放；按住中键拖动可调整视角。点击点、线、面或模型查看属性。
    </p>
    <p>
      默认打开广州大学大学城校区；地区面板提供大学城、黄埔校区小样快捷切换，以及全国省、市、区县定位。复位返回所选地区。
    </p>
    <p>自定义图层的加入状态、显隐和透明度会保存到服务器，刷新或重启后自动恢复。旧图层首次加入一次即可。</p>
    <p>地区旁的“收藏位置”可保存当前地区或在地图上点击选点，支持重命名和删除。点击收藏跳转；选点时按 Esc 可取消。</p>
    <p>
      校园白模采用 OSM 公开建筑轮廓，无真实立面；高度优先采用 OSM
      标注，其次按楼层×3米估计，缺测时统一9米。可点击建筑查看高度依据，不保证覆盖全部建筑。
    </p>
    <p>积水、道路及六栋三维瓦片仍为合成演示。切换校区不移动用户数据。</p>
    <p>
      在左侧对应图层卡片点击下载按钮：GeoJSON
      下载单文件，三维小样及本地三维资产下载完整
      ZIP。外部三维服务仅提供“打开数据源”。
    </p>
    <a
      href="https://www.openstreetmap.org/copyright"
      target="_blank"
      rel="noopener"
      >© OpenStreetMap contributors · ODbL<ArrowUpRight :size="14"
    /></a>
  </aside>
</template>

<style scoped>
.help-panel {
  position: absolute;
  right: 20px;
  top: 80px;
  z-index: 6;
  width: 310px;
  padding: 18px 20px;
  animation: panel-in 0.2s;
}
.help-panel header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 15px;
}
.help-panel h2 {
  font-size: 14px;
  font-weight: 550;
}
.help-panel p {
  font-size: 11px;
  line-height: 1.9;
  color: #8491a3;
  margin-bottom: 12px;
}
.help-panel a {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 11px;
  color: var(--blue);
  padding: 10px 0;
  border-top: 1px solid var(--line);
}
.help-panel a svg:last-child {
  margin-left: auto;
}
@media (max-width: 600px) {
  .help-panel {
    right: 12px;
    top: 70px;
    width: min(310px, calc(100% - 24px));
  }
}
</style>
