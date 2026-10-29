<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { X, Plus, Search, Layers } from '@lucide/vue'
import type { MapLayer } from '../types'
defineEmits<{ close: []; join: [layer: MapLayer]; manage: [] }>()
const props = defineProps<{ layers: MapLayer[] }>()
const tab = ref<'samples' | 'registered'>('registered')
const search = ref('')
const dialog = ref<HTMLElement>()
const filtered = computed(() =>
  props.layers.filter(
    (layer) =>
      (tab.value === 'samples' ? layer.builtin : !layer.builtin) &&
      `${layer.name} ${layer.category}`
        .toLowerCase()
        .includes(search.value.toLowerCase()),
  ),
)
onMounted(() => dialog.value?.focus())
function trapFocus(event: KeyboardEvent) {
  if (event.key !== 'Tab' || !dialog.value) return
  const elements = [
    ...dialog.value.querySelectorAll<HTMLElement>(
      'button:not(:disabled), input',
    ),
  ]
  const first = elements[0],
    last = elements.at(-1)
  if (
    document.activeElement === dialog.value ||
    (event.shiftKey && document.activeElement === first)
  ) {
    event.preventDefault()
    ;(event.shiftKey ? last : first)?.focus()
  } else if (!event.shiftKey && document.activeElement === last) {
    event.preventDefault()
    first?.focus()
  }
}
</script>

<template>
  <div
    class="backdrop"
    @click.self="$emit('close')"
    @keydown.esc="$emit('close')"
  >
    <section
      ref="dialog"
      class="chooser"
      role="dialog"
      aria-modal="true"
      aria-labelledby="chooser-title"
      tabindex="-1"
      @keydown="trapFocus"
    >
      <header>
        <div>
          <span class="eyebrow">MAP LAYERS</span>
          <h2 id="chooser-title">添加到当前地图</h2>
        </div>
        <button
          class="icon-button"
          aria-label="关闭图层选择"
          @click="$emit('close')"
        >
          <X :size="20" />
        </button>
      </header>
      <p class="description">
        选择已有数据。上传、登记与文件管理请前往“我的数据”。
      </p>
      <div class="tabs">
        <button
          :class="{ active: tab === 'registered' }"
          @click="tab = 'registered'"
        >
          已登记数据</button
        ><button
          :class="{ active: tab === 'samples' }"
          @click="tab = 'samples'"
        >
          内置示例
        </button>
      </div>
      <label class="search"
        ><Search :size="15" /><input
          v-model="search"
          aria-label="搜索可添加图层"
          placeholder="搜索名称或分类"
      /></label>
      <div class="choices">
        <p v-if="!filtered.length" class="empty">
          <Layers :size="24" />暂无匹配数据，可先到管理页上传或登记。
        </p>
        <article v-for="layer in filtered" :key="layer.id">
          <div>
            <strong>{{ layer.name }}</strong
            ><small
              >{{ layer.type === '3dtiles' ? '3D Tiles' : 'GeoJSON' }} ·
              {{ layer.category
              }}{{
                layer.builtin
                  ? layer.id === 'campus-buildings'
                    ? ' · 公开轮廓，高度含估计'
                    : ' · 合成演示'
                  : ''
              }}</small
            >
          </div>
          <button
            :disabled="layer.attached"
            :aria-label="`加入地图${layer.name}`"
            @click="$emit('join', layer)"
          >
            {{ layer.attached ? '已在地图' : '加入地图' }}
          </button>
        </article>
      </div>
      <footer>
        <span>移除地图图层不会删除登记或文件。</span
        ><button class="primary-button" @click="$emit('manage')">
          <Plus :size="15" />新增数据
        </button>
      </footer>
    </section>
  </div>
</template>

<style scoped>
.backdrop {
  position: fixed;
  inset: 0;
  z-index: 30;
  background: #14233555;
  backdrop-filter: blur(3px);
  display: grid;
  place-items: center;
  padding: 20px;
}
.chooser {
  width: 580px;
  max-width: 100%;
  max-height: calc(100svh - 40px);
  overflow: auto;
  background: white;
  border-radius: 12px;
  padding: 24px;
}
header {
  display: flex;
  justify-content: space-between;
  align-items: start;
}
h2 {
  font-size: 20px;
  font-weight: 550;
  margin: 7px 0 12px;
}
.description,
footer > span {
  color: #8190a5;
  font-size: 11px;
  line-height: 1.7;
}
.tabs {
  display: flex;
  gap: 24px;
  border-bottom: 1px solid var(--line);
  margin: 15px 0;
}
.tabs button {
  padding: 12px 0;
  color: #8a95a5;
}
.tabs .active {
  color: var(--blue);
  box-shadow: 0 2px var(--blue);
}
.search {
  display: flex;
  gap: 8px;
  align-items: center;
  background: #f5f7fb;
  padding: 10px;
  border-radius: 5px;
  color: #8b9bb0;
}
input {
  border: 0;
  background: transparent;
  outline: none;
  width: 100%;
  min-width: 0;
}
.choices {
  margin: 10px 0 20px;
  max-height: 330px;
  overflow: auto;
}
article {
  display: flex;
  align-items: center;
  gap: 16px;
  padding: 16px 0;
  border-bottom: 1px solid var(--line);
}
article > div {
  flex: 1;
  min-width: 0;
}
strong {
  display: block;
  font-weight: 550;
  overflow-wrap: anywhere;
}
small {
  display: block;
  color: #91a0b2;
  font-size: 10px;
  margin-top: 6px;
}
article > button {
  color: var(--blue);
  font-size: 12px;
  flex-shrink: 0;
}
footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 20px;
}
.empty {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 30px 0;
  color: #8a98aa;
  font-size: 12px;
  line-height: 1.7;
}
</style>
