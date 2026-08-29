<template>
  <div
    class="hue-sat-wheel"
    :class="{ disabled }"
    :style="{ width: size + 'px', height: size + 'px' }"
    @pointerdown="onPointerDown"
    @pointermove="onPointerMove"
    @pointerup="onPointerUp"
    @pointercancel="onPointerUp"
  >
    <div class="wheel-disc"></div>
    <div class="wheel-marker" :style="markerStyle"></div>
  </div>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'

// Hue/saturation wheel: hue is the angle (red at 12 o'clock, clockwise),
// saturation is the radius (white at the center). Values use the ZCL
// CurrentHue/CurrentSaturation 0-254 scale; brightness is controlled by the
// separate level slider, so no value axis exists here by design.
const props = withDefaults(
  defineProps<{
    hue: number
    sat: number
    size?: number
    disabled?: boolean
  }>(),
  { size: 176, disabled: false }
)

const emit = defineEmits<{ (e: 'commit', value: { hue: number; sat: number }): void }>()

const ZCL_MAX = 254

const dragging = ref(false)
const dragHue = ref(0)
const dragSat = ref(0)

const activeHue = computed(() => (dragging.value ? dragHue.value : props.hue))
const activeSat = computed(() => (dragging.value ? dragSat.value : props.sat))

const markerStyle = computed(() => {
  const angle = (activeHue.value / ZCL_MAX) * 2 * Math.PI
  const radius = (activeSat.value / ZCL_MAX) * 50
  const x = 50 + Math.sin(angle) * radius
  const y = 50 - Math.cos(angle) * radius
  return { left: x + '%', top: y + '%' }
})

function pointerToHueSat(event: PointerEvent): { hue: number; sat: number } {
  const rect = (event.currentTarget as HTMLElement).getBoundingClientRect()
  const dx = event.clientX - (rect.left + rect.width / 2)
  const dy = event.clientY - (rect.top + rect.height / 2)
  const dist = Math.min(1, Math.hypot(dx, dy) / (rect.width / 2))
  let angle = Math.atan2(dx, -dy)
  if (angle < 0) angle += 2 * Math.PI
  return {
    hue: Math.round((angle / (2 * Math.PI)) * ZCL_MAX) % ZCL_MAX,
    sat: Math.round(dist * ZCL_MAX),
  }
}

function onPointerDown(event: PointerEvent) {
  if (props.disabled) return
  ;(event.currentTarget as HTMLElement).setPointerCapture(event.pointerId)
  dragging.value = true
  const picked = pointerToHueSat(event)
  dragHue.value = picked.hue
  dragSat.value = picked.sat
}

function onPointerMove(event: PointerEvent) {
  if (!dragging.value || props.disabled) return
  const picked = pointerToHueSat(event)
  dragHue.value = picked.hue
  dragSat.value = picked.sat
}

function onPointerUp() {
  if (!dragging.value) return
  dragging.value = false
  emit('commit', { hue: dragHue.value, sat: dragSat.value })
}
</script>

<style scoped>
.hue-sat-wheel {
  position: relative;
  border-radius: 50%;
  touch-action: none;
  cursor: crosshair;
  user-select: none;
}
.hue-sat-wheel.disabled {
  opacity: 0.5;
  cursor: not-allowed;
}
.wheel-disc {
  position: absolute;
  inset: 0;
  border-radius: 50%;
  background:
    radial-gradient(closest-side, #fff 0%, rgba(255, 255, 255, 0) 72%),
    conic-gradient(#f00, #ff0, #0f0, #0ff, #00f, #f0f, #f00);
  box-shadow:
    inset 0 0 0 1px rgba(0, 0, 0, 0.25),
    0 2px 8px rgba(0, 0, 0, 0.4);
}
.wheel-marker {
  position: absolute;
  width: 16px;
  height: 16px;
  border-radius: 50%;
  background: transparent;
  border: 2px solid #fff;
  box-shadow:
    0 0 0 1px rgba(0, 0, 0, 0.6),
    0 1px 3px rgba(0, 0, 0, 0.5);
  transform: translate(-50%, -50%);
  pointer-events: none;
}
</style>
