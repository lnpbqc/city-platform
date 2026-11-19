<script setup lang="ts">
import { nextTick, onBeforeUnmount, onMounted, onUpdated, ref, shallowRef, useId, watch } from 'vue'

const props = defineProps<{ text: string }>()
defineOptions({ inheritAttrs: false })
const id = `tooltip-${useId()}`
const wrapper = shallowRef<HTMLElement>()
const bubble = shallowRef<HTMLElement>()
const visible = ref(false)
const disabled = ref(false)
const label = ref('')
const position = ref({ left: '0px', top: '0px' })
let trigger: HTMLElement | undefined
let timer: ReturnType<typeof setTimeout> | undefined
let hovered = false
let focused = false

function describe(element: HTMLElement | undefined, show: boolean) {
  if (!element) return
  const ids = (element.getAttribute('aria-describedby') ?? '').split(/\s+/).filter(value => value && value !== id)
  if (show) ids.push(id)
  if (ids.length) element.setAttribute('aria-describedby', ids.join(' '))
  else element.removeAttribute('aria-describedby')
}

function syncTrigger() {
  const child = wrapper.value?.firstElementChild as HTMLElement | undefined
  if (trigger !== child) describe(trigger, false)
  trigger = child
  disabled.value = Boolean(trigger?.hasAttribute('disabled'))
  label.value = trigger?.getAttribute('aria-label') ?? trigger?.textContent?.trim() ?? ''
  describe(trigger, visible.value)
}

function clearTimer() {
  clearTimeout(timer)
  timer = undefined
}

function close() {
  clearTimer()
  visible.value = false
  describe(trigger, false)
}

function place() {
  if (!visible.value || !wrapper.value || !bubble.value) return
  const rect = wrapper.value.getBoundingClientRect()
  const size = bubble.value.getBoundingClientRect()
  const left = Math.max(8, Math.min(rect.left + rect.width / 2 - size.width / 2, window.innerWidth - size.width - 8))
  const preferredTop = rect.top - size.height - 8
  const top = Math.max(8, Math.min(preferredTop >= 8 ? preferredTop : rect.bottom + 8, window.innerHeight - size.height - 8))
  position.value = { left: `${left}px`, top: `${top}px` }
}

function open() {
  clearTimer()
  if (!props.text) return
  visible.value = true
  syncTrigger()
}

function pointerEnter() {
  hovered = true
  clearTimer()
  timer = setTimeout(open, 300)
}

function pointerLeave() {
  hovered = false
  clearTimer()
  if (!focused) close()
}

function focusIn() {
  focused = true
  open()
}

function focusOut(event: FocusEvent) {
  if (event.relatedTarget && wrapper.value?.contains(event.relatedTarget as Node)) return
  focused = false
  if (!hovered) close()
}

function keyDown(event: KeyboardEvent) {
  if (event.key === 'Escape') close()
}

watch([visible, () => props.text], async () => {
  if (!props.text) close()
  await nextTick()
  place()
})
onMounted(() => {
  syncTrigger()
  window.addEventListener('keydown', keyDown)
  window.addEventListener('resize', place)
  window.addEventListener('scroll', place, true)
})
onUpdated(syncTrigger)
onBeforeUnmount(() => {
  close()
  window.removeEventListener('keydown', keyDown)
  window.removeEventListener('resize', place)
  window.removeEventListener('scroll', place, true)
})
</script>

<template>
  <span v-bind="$attrs" ref="wrapper" class="ui-tooltip-trigger" :tabindex="disabled ? 0 : undefined"
    :aria-label="disabled ? label : undefined" :aria-disabled="disabled || undefined"
    :aria-describedby="disabled && visible ? id : undefined"
    @pointerenter="pointerEnter" @pointerleave="pointerLeave" @focusin="focusIn" @focusout="focusOut">
    <slot />
  </span>
  <Teleport to="body">
    <div v-if="visible" :id="id" ref="bubble" role="tooltip" class="ui-tooltip" :style="position">{{ text }}</div>
  </Teleport>
</template>

<style scoped>
.ui-tooltip-trigger { display: inline-flex; min-width: 0; }
.ui-tooltip-trigger:focus-visible { outline: 2px solid var(--blue, #1d4ed8); outline-offset: 3px; border-radius: 4px; }
.ui-tooltip { position: fixed; z-index: 10000; max-width: min(280px, calc(100vw - 16px)); max-height: calc(100vh - 16px); overflow: hidden; box-sizing: border-box; padding: 7px 10px; border: 1px solid #3c5360; border-radius: 6px; background: #14232e; color: #f3f7fa; box-shadow: 0 4px 16px #0004; font-size: 12px; line-height: 1.5; overflow-wrap: anywhere; pointer-events: none; }
</style>
