<script setup lang="ts">
import { Layers, Map as MapIcon, Database, CircleHelp, Route } from '@lucide/vue'
import type { WorkspacePage } from '../../router/workspaceRoute'
defineProps<{ page: WorkspacePage; count: number }>()
const emit = defineEmits<{
  navigate: [page: WorkspacePage]
  home: []
  help: []
}>()
</script>

<template>
  <header class="topbar">
    <a class="brand" href="#" aria-label="城市韧性" @click.prevent="emit('home')">
      <span class="brand-mark"><Layers :size="23" :stroke-width="1.8" /></span>
      <span class="brand-name">城市韧性<span class="brand-en">CITY RESILIENCE</span></span>
      <span class="prototype-label">地图原型</span>
    </a>
    <nav class="top-nav" aria-label="工作台导航">
      <button
        :class="{ 'nav-current': page === 'map' }"
        :aria-pressed="page === 'map'"
        @click="emit('navigate', 'map')"
      >
        <MapIcon :size="16" />地图工作台
      </button>
      <button
        :class="{ 'nav-current': page === 'simulation' }"
        :aria-pressed="page === 'simulation'"
        @click="emit('navigate', 'simulation')"
      >
        <Route :size="16" />仿真推演
      </button>
      <button
        :class="{ 'nav-current': page === 'data' }"
        :aria-pressed="page === 'data'"
        @click="emit('navigate', 'data')"
      >
        <Database :size="15" />我的数据<span class="nav-count">{{
          count
        }}</span>
      </button>
    </nav>
    <div class="topbar-right">
      <slot name="tools" />
      <span class="local-label"><i></i>本地工作空间</span>
      <button class="icon-button" aria-label="操作帮助" @click="emit('help')">
        <CircleHelp :size="19" />
      </button>
      <span class="avatar">研</span>
    </div>
  </header>
</template>

<style scoped>
.topbar {
  height: 64px;
  position: absolute;
  inset: 0 0 auto;
  z-index: 5;
  background: #fff;
  color: #334155;
  display: flex;
  align-items: center;
  padding: 0 24px;
  border-bottom: 1px solid var(--line);
  gap: 30px;
}
.brand {
  display: flex;
  align-items: center;
  gap: 11px;
  color: #1c2e43;
  min-height: 44px;
  font-size: 18px;
  font-weight: 650;
  letter-spacing: 1px;
  white-space: nowrap;
}
.brand-mark {
  height: 36px;
  width: 36px;
  display: grid;
  place-items: center;
  background: var(--blue);
  border-radius: 9px;
  color: white;
}
.brand-en {
  display: block;
  font-size: 10px;
  font-weight: 550;
  letter-spacing: 1.8px;
  margin-top: 2px;
  color: #475569;
}
.prototype-label {
  font-size: 12px;
  letter-spacing: 0;
  font-weight: 400;
  color: #475569;
  border-left: 1px solid #dce2eb;
  padding-left: 12px;
  margin-left: 3px;
}
.top-nav {
  align-self: stretch;
  display: flex;
  gap: 28px;
  align-items: stretch;
}
.top-nav > span,
.top-nav > button {
  display: flex;
  align-items: center;
  gap: 7px;
  min-height: 44px;
  padding: 0;
  font-size: 16px;
  font-weight: 500;
  white-space: nowrap;
}
.nav-current {
  color: var(--blue);
  position: relative;
  font-weight: 600;
}
.nav-current:after {
  content: '';
  position: absolute;
  bottom: 0;
  left: 0;
  right: 0;
  height: 3px;
  background: var(--blue);
  border-radius: 2px 2px 0 0;
}
.nav-count {
  font-size: 12px;
  background: #f1f4f8;
  color: #475569;
  padding: 1px 5px;
  border-radius: 4px;
}
.topbar-right {
  margin-left: auto;
  display: flex;
  align-items: center;
  gap: 20px;
}
.local-label {
  white-space: nowrap;
  font-size: 14px;
  color: #475569;
  display: flex;
  align-items: center;
  gap: 7px;
}
@media (max-width: 1100px) { .local-label { display: none; } }
.local-label i {
  width: 5px;
  height: 5px;
  border-radius: 50%;
  background: #4d9e85;
}
.avatar {
  width: 30px;
  height: 30px;
  display: grid;
  place-items: center;
  border: 1px solid #dfe7f3;
  background: #f2f6fc;
  color: #5f7caa;
  border-radius: 50%;
  font-size: 12px;
}
.topbar-right > .icon-button { width: 44px; height: 44px; }
@media (max-width: 900px) {
  .topbar {
    gap: 25px;
    padding: 0 16px;
  }
  .topbar-right {
    gap: 10px;
  }
  .local-label {
    display: none;
  }
  .prototype-label {
    display: none;
  }
  .top-nav {
    gap: 20px;
  }
}
@media (max-width: 767px) {
  .topbar {
    padding: 0 12px;
    gap: 8px;
  }
  .brand {
    font-size: 16px;
    gap: 7px;
  }
  .brand-mark {
    width: 31px;
    height: 31px;
  }
  .brand-en {
    display: none;
  }
  .top-nav {
    gap: 8px;
  }
  .top-nav > button {
    font-size: 14px;
    gap: 4px;
  }
  .topbar-right {
    display: flex;
    margin-left: auto;
  }
  .topbar-right > .icon-button { display: none; }
  .top-nav > button > svg,
  .nav-count {
    display: none;
  }
  .avatar {
    display: none;
  }
}
@media (max-width: 600px) {
  .topbar { height: 58px; }
}
@media (max-width: 480px) {
  .topbar { padding: 0 8px; }
  .brand { min-width: 44px; justify-content: center; }
  .brand-name { display: none; }
}
</style>
