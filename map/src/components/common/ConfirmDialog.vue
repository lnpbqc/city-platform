<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref } from 'vue'
import { LoaderCircle, X } from '@lucide/vue'

defineProps<{
  title: string
  confirmLabel: string
  busy: boolean
  error?: string
  blocked?: boolean
}>()
const emit = defineEmits<{ close: []; confirm: [] }>()
const dialog = ref<HTMLElement | null>(null)
const cancel = ref<HTMLButtonElement | null>(null)
let previousFocus: HTMLElement | null = null
function keydown(event: KeyboardEvent) {
  if (event.key === 'Escape') cancel.value?.click()
  if (event.key !== 'Tab' || !dialog.value) return
  const items = [
    ...dialog.value.querySelectorAll<HTMLElement>(
      'button:not(:disabled), a[href]',
    ),
  ]
  const first = items[0],
    last = items.at(-1)
  if (!items.length) {
    event.preventDefault()
    dialog.value.focus()
  } else if (
    !dialog.value.contains(document.activeElement) ||
    document.activeElement === dialog.value
  ) {
    event.preventDefault()
    ;(event.shiftKey ? last : first)?.focus()
  } else if (event.shiftKey && document.activeElement === first) {
    event.preventDefault()
    last?.focus()
  } else if (!event.shiftKey && document.activeElement === last) {
    event.preventDefault()
    first?.focus()
  }
}
onMounted(() => {
  previousFocus = document.activeElement as HTMLElement
  cancel.value?.focus()
  document.addEventListener('keydown', keydown)
})
onBeforeUnmount(() => {
  document.removeEventListener('keydown', keydown)
  if (previousFocus?.isConnected) previousFocus.focus()
})
</script>

<template>
  <div class="confirm-backdrop" @click.self="!busy && emit('close')">
    <section
      ref="dialog"
      class="confirm-dialog"
      role="alertdialog"
      aria-modal="true"
      aria-labelledby="confirm-title"
      aria-describedby="confirm-content"
      tabindex="-1"
    >
      <header>
        <h2 id="confirm-title">{{ title }}</h2>
        <button
          class="icon-button"
          aria-label="关闭确认"
          :disabled="busy"
          @click="emit('close')"
        >
          <X :size="19" />
        </button>
      </header>
      <div id="confirm-content" class="confirm-content"><slot /></div>
      <div v-if="error" class="confirm-error" role="alert">
        {{ error }}<slot name="error" />
      </div>
      <footer>
        <button
          ref="cancel"
          class="cancel-button"
          :disabled="busy"
          @click="emit('close')"
        >
          取消</button
        ><button
          class="danger-button"
          :disabled="busy || blocked"
          @click="emit('confirm')"
        >
          <LoaderCircle v-if="busy" :size="15" class="spin" />{{
            busy ? '正在删除…' : confirmLabel
          }}
        </button>
      </footer>
    </section>
  </div>
</template>

<style scoped>
.confirm-backdrop {
  position: fixed;
  inset: 0;
  z-index: 50;
  background: #14233566;
  display: grid;
  place-items: center;
  padding: 20px;
}
.confirm-dialog {
  background: white;
  border-radius: 12px;
  padding: 22px 24px;
  width: 460px;
  max-width: 100%;
  max-height: calc(100svh - 40px);
  overflow: auto;
  box-shadow: 0 20px 80px #15233435;
}
header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}
h2 {
  font-size: 18px;
  font-weight: 550;
}
.confirm-content {
  color: #65758b;
  font-size: 13px;
  line-height: 1.9;
  padding: 18px 0;
  overflow-wrap: anywhere;
}
.confirm-error {
  font-size: 12px;
  line-height: 1.8;
  color: #b9453f;
  background: #fff3f1;
  padding: 10px 12px;
  border-radius: 6px;
}
footer {
  display: flex;
  justify-content: flex-end;
  gap: 12px;
  margin-top: 20px;
  padding-top: 16px;
  border-top: 1px solid var(--line);
}
.cancel-button,
.danger-button {
  padding: 9px 15px;
  border-radius: 5px;
  font-size: 12px;
  gap: 7px;
}
.cancel-button {
  border: 1px solid #dce3ec;
}
.danger-button {
  background: #c84c45;
  color: white;
}
.danger-button:hover:not(:disabled) {
  background: #b13b35;
  color: white;
}
</style>
