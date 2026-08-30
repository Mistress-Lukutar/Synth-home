<template>
  <div class="device-card" :class="{ offline: device.online === false }">
    <div class="device-info">
      <div class="editable-title">
        <span v-if="!editing" class="title-text" @click="startEdit">{{ displayName }}</span>
        <svg v-if="!editing" class="edit-icon" @click="startEdit" viewBox="0 0 24 24"><path d="M3 17.25V21h3.75L17.81 9.94l-3.75-3.75L3 17.25zM20.71 7.04c.39-.39.39-1.02 0-1.41l-2.34-2.34c-.39-.39-1.02-.39-1.41 0l-1.83 1.83 3.75 3.75 1.83-1.83z"/></svg>
        <input
          v-else
          ref="inputRef"
          v-model="editName"
          class="title-input"
          @keydown.enter="save"
          @keydown.esc="cancel"
          @blur="save"
        />
        <button class="btn-icon btn-danger" @click="remove" title="Delete device">
          <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="#ff4444" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <path d="M3 6h18"/>
            <path d="M19 6v14a2 2 0 01-2 2H7a2 2 0 01-2-2V6"/>
            <path d="M8 6V4a2 2 0 012-2h4a2 2 0 012 2v2"/>
            <path d="M10 11v6"/>
            <path d="M14 11v6"/>
          </svg>
        </button>
      </div>
      <div class="device-details">
        <span class="device-ieee">{{ device.ieee }}</span>
        <span :class="device.online !== false ? 'device-online' : 'device-offline'">{{ device.online !== false ? 'Online' : 'Offline' }}</span>
      </div>
    </div>
    <div class="device-endpoints">
      <div v-for="ep in device.endpoints || []" :key="ep.id" class="endpoint-row">
        <div class="ep-header">
          <span class="ep-label">EP{{ ep.id }}</span>
          <span class="ep-clusters">{{ (ep.clusters || []).join(', ') }}</span>
        </div>
        <div class="ep-controls">
          <!-- On/Off toggle (cluster 0x0006 = 6) -->
          <div
            v-if="hasCluster(ep, 6)"
            class="toggle-switch"
            :class="{ on: getState(ep.id, 'on') === true, pending: isPending(ep.id, 'on') || isPending(ep.id, 'off') || isPending(ep.id, 'toggle'), disabled: device.online === false }"
            @click="toggleOnOff(ep.id)"
            :title="device.online === false ? 'Device offline' : 'Toggle On/Off'"
          >
            <div class="knob"></div>
          </div>

          <!-- Brightness slider (cluster 0x0008 = 8) -->
          <div v-if="hasCluster(ep, 8)" class="level-control">
            <label class="level-label">Brightness</label>
            <input
              type="range"
              :min="getState(ep.id, 'level_min') ?? 0"
              :max="getState(ep.id, 'level_max') ?? 255"
              :value="getState(ep.id, 'level') ?? (getState(ep.id, 'level_max') ?? 255) / 2"
              @change="(e) => setLevel(ep.id, Number((e.target as HTMLInputElement).value))"
              :disabled="isPending(ep.id, 'level') || device.online === false"
            />
          </div>

          <!-- Color controls (cluster 0x0300 = 768) -->
          <template v-if="hasCluster(ep, 768)">
            <!-- Both RGB and CT supported: tabs pick which control is shown
                 and switch the lamp to that color mode on click -->
            <template v-if="hasBothColorModes(ep.id)">
              <div class="color-tabs">
                <button
                  class="color-tab"
                  :class="{ active: colorTabOf(ep.id) === 'color' }"
                  @click="switchColorTab(ep.id, 'color')"
                >Color</button>
                <button
                  class="color-tab"
                  :class="{ active: colorTabOf(ep.id) === 'temp' }"
                  @click="switchColorTab(ep.id, 'temp')"
                >Temperature</button>
              </div>

              <div v-if="colorTabOf(ep.id) === 'color'" class="color-wheel-row">
                <HueSatWheel
                  v-bind="wheelHueSat(ep.id)"
                  :disabled="device.online === false || isPending(ep.id, 'color')"
                  @commit="(v) => setColorHs(ep.id, v.hue, v.sat)"
                />
              </div>

              <div v-else class="ct-slider-row">
                <input
                  type="range"
                  :min="getState(ep.id, 'ct_min') ?? 153"
                  :max="getState(ep.id, 'ct_max') ?? 500"
                  class="ct-slider"
                  :value="getState(ep.id, 'ct') ?? 300"
                  @change="(e) => setCt(ep.id, Number((e.target as HTMLInputElement).value))"
                  :disabled="isPending(ep.id, 'color_ct') || device.online === false"
                />
              </div>
            </template>

            <!-- Single color mode: show the one supported control directly -->
            <template v-else>
              <!-- Hue/saturation wheel (brightness is the separate level slider) -->
              <div
                v-if="colorSupports(ep.id, 'hs') || colorSupports(ep.id, 'xy')"
                class="color-wheel-row"
              >
                <HueSatWheel
                  v-bind="wheelHueSat(ep.id)"
                  :disabled="device.online === false || isPending(ep.id, 'color')"
                  @commit="(v) => setColorHs(ep.id, v.hue, v.sat)"
                />
              </div>

              <!-- Color temperature: gradient slider -->
              <div
                v-if="colorSupports(ep.id, 'ct') || ctRangeKnown(ep.id)"
                class="ct-slider-row"
              >
                <input
                  type="range"
                  :min="getState(ep.id, 'ct_min') ?? 153"
                  :max="getState(ep.id, 'ct_max') ?? 500"
                  class="ct-slider"
                  :value="getState(ep.id, 'ct') ?? 300"
                  @change="(e) => setCt(ep.id, Number((e.target as HTMLInputElement).value))"
                  :disabled="isPending(ep.id, 'color_ct') || device.online === false"
                />
              </div>
            </template>
          </template>
        </div>
      </div>
      <div v-if="!(device.endpoints || []).length" class="endpoint-row">
        <span class="ep-clusters">No endpoints reported</span>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, watch, computed, nextTick } from 'vue'
import { useHubStore } from '../composables/useHubStore'
import * as api from '../api'
import HueSatWheel from './HueSatWheel.vue'

const props = defineProps<{ device: any }>()
const store = useHubStore()

const editing = ref(false)
const editName = ref('')
const inputRef = ref<HTMLInputElement | null>(null)

function zclHsToHex(hue: number, sat: number, level: number = 254): string {
  // ZCL hue 0-254, sat 0-254, level 0-254 → RGB hex
  const h = (hue / 254) * 360
  const s = sat / 254
  const v = level / 254
  const c = v * s
  const x = c * (1 - Math.abs(((h / 60) % 2) - 1))
  const m = v - c
  let r = 0, g = 0, b = 0
  if (h < 60)       { r = c; g = x; b = 0 }
  else if (h < 120) { r = x; g = c; b = 0 }
  else if (h < 180) { r = 0; g = c; b = x }
  else if (h < 240) { r = 0; g = x; b = c }
  else if (h < 300) { r = x; g = 0; b = c }
  else              { r = c; g = 0; b = x }
  r = Math.round((r + m) * 255)
  g = Math.round((g + m) * 255)
  b = Math.round((b + m) * 255)
  const toHex = (n: number) => n.toString(16).padStart(2, '0')
  return `#${toHex(r)}${toHex(g)}${toHex(b)}`
}

function zclXyToHex(x: number, y: number, level: number = 254): string {
  // ZCL x/y raw 0-65535, level 0-254 → RGB hex
  const xn = Math.max(0.0001, x / 65535)
  const yn = Math.max(0.0001, y / 65535)
  const Y = level / 254
  const X = (Y / yn) * xn
  const Z = (Y / yn) * (1 - xn - yn)
  let r = X * 3.2406 + Y * -1.5372 + Z * -0.4986
  let g = X * -0.9689 + Y * 1.8758 + Z * 0.0415
  let b = X * 0.0557 + Y * -0.2040 + Z * 1.0570
  r = r > 0.0031308 ? 1.055 * Math.pow(r, 1 / 2.4) - 0.055 : 12.92 * r
  g = g > 0.0031308 ? 1.055 * Math.pow(g, 1 / 2.4) - 0.055 : 12.92 * g
  b = b > 0.0031308 ? 1.055 * Math.pow(b, 1 / 2.4) - 0.055 : 12.92 * b
  r = Math.max(0, Math.min(1, r))
  g = Math.max(0, Math.min(1, g))
  b = Math.max(0, Math.min(1, b))
  const toHex = (n: number) => Math.round(n * 255).toString(16).padStart(2, '0')
  return `#${toHex(r)}${toHex(g)}${toHex(b)}`
}

function hexToZclHueSat(hex: string): { hue: number; sat: number } {
  const r = parseInt(hex.slice(1, 3), 16) / 255
  const g = parseInt(hex.slice(3, 5), 16) / 255
  const b = parseInt(hex.slice(5, 7), 16) / 255
  const max = Math.max(r, g, b)
  const min = Math.min(r, g, b)
  const d = max - min
  let h = 0
  if (d !== 0) {
    if (max === r) h = 60 * (((g - b) / d) % 6)
    else if (max === g) h = 60 * ((b - r) / d + 2)
    else h = 60 * ((r - g) / d + 4)
  }
  if (h < 0) h += 360
  const s = max === 0 ? 0 : d / max
  return { hue: Math.round((h / 360) * 254), sat: Math.round(s * 254) }
}

function wheelHueSat(epId: number): { hue: number; sat: number } {
  const hue = getState(epId, 'hue')
  const sat = getState(epId, 'sat')
  if (hue !== undefined && sat !== undefined) {
    return { hue: Number(hue), sat: Number(sat) }
  }
  const x = getState(epId, 'x')
  const y = getState(epId, 'y')
  if (x !== undefined && y !== undefined) {
    return hexToZclHueSat(zclXyToHex(Number(x), Number(y), 254))
  }
  return { hue: 0, sat: 0 }
}

const displayName = computed(() => props.device.name || 'Unknown Device')

function startEdit() {
  editing.value = true
  editName.value = displayName.value
  nextTick(() => inputRef.value?.focus())
}

function cancel() {
  editing.value = false
}

async function save() {
  editing.value = false
  const newName = editName.value.trim()
  if (!newName || newName === displayName.value) return
  try {
    await api.renameDevice(props.device.ieee, newName)
    await store.refreshDevices()
  } catch (e: any) {
    store.logEvent('Rename failed: ' + e.message)
  }
}

async function remove() {
  if (!confirm(`Delete device ${displayName.value}?`)) return
  try {
    await api.deleteDevice(props.device.ieee)
    store.logEvent(`Device ${displayName.value} deleted`)
    await store.refreshDevices()
  } catch (e: any) {
    store.logEvent('Delete failed: ' + e.message)
  }
}

function hasCluster(ep: any, clusterId: number): boolean {
  return (ep.clusters || []).includes(clusterId)
}

function getState(epId: number, key: string): any {
  const state = props.device.state || {}
  return state[String(epId)]?.[key]
}

function colorSupports(epId: number, cap: 'hs' | 'xy' | 'ct' | 'color_loop'): boolean {
  const caps = getState(epId, 'color_caps')
  if (!caps) return true
  // An all-false caps dict means "unknown", never "no color support at all"
  // (a device with cluster 0x0300 always supports at least one color mode).
  if (!caps.hs && !caps.xy && !caps.ct) return true
  return !!caps[cap]
}

function ctRangeKnown(epId: number): boolean {
  return getState(epId, 'ct_min') !== undefined || getState(epId, 'ct_max') !== undefined
}

// Color mode tabs: shown when an endpoint supports both RGB (hs/xy) and CT,
// so only one control occupies the card at a time.
type ColorTab = 'color' | 'temp'
const colorTabs = reactive<Record<number, ColorTab>>({})

function hasBothColorModes(epId: number): boolean {
  const rgb = colorSupports(epId, 'hs') || colorSupports(epId, 'xy')
  const ct = colorSupports(epId, 'ct') || ctRangeKnown(epId)
  return rgb && ct
}

function reportedColorTab(epId: number): ColorTab {
  return getState(epId, 'color_mode') === 'ct' ? 'temp' : 'color'
}

function colorTabOf(epId: number): ColorTab {
  return colorTabs[epId] ?? reportedColorTab(epId)
}

function isColorPending(epId: number): boolean {
  return isPending(epId, 'color') || isPending(epId, 'color_ct')
}

// Follow the reported ZCL ColorMode so tabs stay truthful when the mode is
// changed elsewhere (automation, another client). While a color switch is in
// flight the local tab wins; the stale pre-switch report must not yank it.
watch(
  () => (props.device.endpoints || [])
    .map((ep: any) => `${ep.id}=${getState(ep.id, 'color_mode') ?? ''}`)
    .join(','),
  () => {
    for (const ep of props.device.endpoints || []) {
      if (getState(ep.id, 'color_mode') === undefined) continue
      if (isColorPending(ep.id)) continue
      colorTabs[ep.id] = reportedColorTab(ep.id)
    }
  }
)

async function switchColorTab(epId: number, tab: ColorTab) {
  if (colorTabOf(epId) === tab) return
  colorTabs[epId] = tab
  // Switching tabs also switches the lamp: re-apply the current color/CT so
  // the bulb actually leaves the other color mode.
  if (props.device.online === false || !store.state.isConnected) return
  if (isColorPending(epId)) return
  if (tab === 'color') {
    const known = getState(epId, 'hue') !== undefined || getState(epId, 'sat') !== undefined ||
      getState(epId, 'x') !== undefined || getState(epId, 'y') !== undefined
    const v = wheelHueSat(epId)
    // Nothing known yet: fall back to the wheel's home angle as a visible RGB color.
    await setColorHs(epId, known ? v.hue : 0, known ? v.sat : 254)
  } else {
    await setCt(epId, Number(getState(epId, 'ct') ?? 300))
  }
}

function isPending(epId: number, action: string): boolean {
  for (const [_, pending] of store.state.pendingCommands) {
    if (pending.ieee === props.device.ieee && pending.endpoint === epId && pending.action === action) {
      return true
    }
  }
  return false
}

async function sendAndTrack(action: string, epId: number, params?: object) {
  if (!store.state.isConnected) return
  try {
    const result = await api.sendCommand(props.device.ieee, action, epId, params)
    store.addPendingCommand(result.correlation_id, {
      ieee: props.device.ieee,
      endpoint: epId,
      action,
    })
  } catch (e: any) {
    store.logEvent(`Command ${action} error: ` + e.message)
  }
}

async function toggleOnOff(epId: number) {
  if (isPending(epId, 'on') || isPending(epId, 'off') || isPending(epId, 'toggle')) return
  const current = getState(epId, 'on') === true
  const action = current ? 'off' : 'on'
  await sendAndTrack(action, epId)
}

async function setLevel(epId: number, level: number) {
  if (isPending(epId, 'level')) return
  await sendAndTrack('level', epId, { level })
}

async function setColorHs(epId: number, hue: number, sat: number) {
  if (isPending(epId, 'color')) return
  // V=254 keeps the hex a pure hue/saturation pair: the hub discards V and
  // brightness stays under the level slider.
  const hex = zclHsToHex(hue, sat, 254)
  const caps = getState(epId, 'color_caps')
  // Prefer HS when supported (1:1 wheel mapping), fallback to XY
  const mode = caps?.hs ? 'hs' : 'xy'
  try {
    const result = await api.sendColor(props.device.ieee, hex, mode, epId)
    store.addPendingCommand(result.correlation_id, {
      ieee: props.device.ieee,
      endpoint: epId,
      action: 'color',
    })
  } catch (e: any) {
    store.logEvent('color error: ' + e.message)
  }
}

async function setCt(epId: number, ct: number) {
  if (isPending(epId, 'color_ct')) return
  try {
    const result = await api.sendColorCt(props.device.ieee, ct, epId)
    store.addPendingCommand(result.correlation_id, {
      ieee: props.device.ieee,
      endpoint: epId,
      action: 'color_ct',
    })
  } catch (e: any) {
    store.logEvent('color_ct error: ' + e.message)
  }
}
</script>

<style scoped>
.device-card {
  background: rgba(0,0,0,0.2);
  border: 1px solid rgba(255,255,255,0.1);
  border-radius: 10px;
  padding: 12px 16px;
  display: flex;
  flex-direction: column;
  gap: 12px;
  transition: all 0.2s;
}
.device-card:hover { background: rgba(255,255,255,0.05); border-color: rgba(255,255,255,0.2); }
.device-card.offline { opacity: 0.6; background: rgba(0,0,0,0.15); border-color: rgba(255,255,255,0.05); }
.device-card.offline .title-text { color: #888; }
.device-card.offline .device-details { color: #555; }

.device-info { display: flex; flex-direction: column; gap: 4px; }
.editable-title { display: flex; align-items: center; gap: 8px; cursor: text; }
.title-text { border-bottom: 1px dashed transparent; transition: border-color 0.2s; font-weight: 600; font-size: 1rem; color: #fff; }
.editable-title:hover .title-text { border-bottom-color: rgba(255,255,255,0.3); }
.edit-icon { width: 14px; height: 14px; opacity: 0; transition: opacity 0.2s; cursor: pointer; fill: #888; }
.editable-title:hover .edit-icon { opacity: 1; }
.edit-icon:hover { fill: #00ff88; }
.title-input {
  background: rgba(255,255,255,0.1);
  border: none;
  border-radius: 4px;
  padding: 2px 6px;
  color: #fff;
  font-size: 1rem;
  font-weight: 600;
  font-family: inherit;
  outline: 2px solid rgba(0,255,136,0.4);
  min-width: 120px;
}
.device-details { font-size: 0.8rem; color: #888; display: flex; gap: 12px; flex-wrap: wrap; }
.device-ieee { font-family: 'SF Mono', Monaco, monospace; }
.device-online { color: #00ff88; }
.device-offline { color: #ff4444; }

.device-endpoints { display: flex; flex-direction: column; gap: 10px; }
.endpoint-row {
  background: rgba(255,255,255,0.03);
  border: 1px solid rgba(255,255,255,0.05);
  border-radius: 8px;
  padding: 10px 12px;
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.ep-header { display: flex; align-items: center; gap: 8px; }
.ep-label { font-size: 0.75rem; text-transform: uppercase; color: #888; letter-spacing: 0.5px; }
.ep-clusters { font-size: 0.8rem; color: #aaa; font-family: 'SF Mono', Monaco, monospace; }
.ep-controls { display: flex; flex-direction: column; gap: 8px; }

/* Toggle Switch */
.toggle-switch {
  width: 56px;
  height: 30px;
  border-radius: 15px;
  background: #666;
  position: relative;
  cursor: pointer;
  transition: background 0.3s;
  flex-shrink: 0;
}
.toggle-switch.pending { cursor: wait; }
.toggle-switch .knob {
  width: 24px;
  height: 24px;
  border-radius: 50%;
  background: #fff;
  position: absolute;
  top: 3px;
  left: 3px;
  transition: left 0.3s;
  box-shadow: 0 1px 3px rgba(0,0,0,0.3);
}
.toggle-switch.on { background: #00ff88; }
.toggle-switch.on .knob { left: 29px; }
.toggle-switch.pending { background: #ffaa00; }
.toggle-switch.pending .knob { left: 16px; }
.toggle-switch.disabled {
  opacity: 0.5;
  cursor: not-allowed;
  pointer-events: none;
}

/* Brightness slider */
.level-control {
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.level-label {
  font-size: 0.75rem;
  text-transform: uppercase;
  color: #888;
  letter-spacing: 0.5px;
}
.level-control input[type="range"] {
  width: 100%;
  accent-color: #00ff88;
}

/* Hue/saturation wheel */
.color-wheel-row {
  display: flex;
  justify-content: center;
  padding: 4px 0;
}

/* Color mode tabs (RGB / CT) */
.color-tabs {
  display: flex;
  justify-content: center;
  gap: 8px;
  border-bottom: 1px solid rgba(255,255,255,0.08);
}
.color-tab {
  background: none;
  border: none;
  padding: 2px 14px 8px;
  font-size: 0.85rem;
  font-family: inherit;
  color: #888;
  cursor: pointer;
  position: relative;
  transition: color 0.2s;
}
.color-tab:hover { color: #ccc; }
.color-tab.active { color: #fff; }
.color-tab.active::after {
  content: '';
  position: absolute;
  left: 50%;
  bottom: -1px;
  transform: translateX(-50%);
  width: 28px;
  height: 2px;
  border-radius: 1px;
  background: #00ff88;
}

/* CT slider */
.ct-slider-row {
  display: flex;
  align-items: center;
  gap: 10px;
}
.ct-slider {
  -webkit-appearance: none;
  appearance: none;
  flex: 1;
  height: 12px;
  border-radius: 6px;
  background: linear-gradient(to right, #a8d0ff, #ffffff, #ff8a00);
  outline: none;
}
.ct-slider::-webkit-slider-thumb {
  -webkit-appearance: none;
  appearance: none;
  width: 20px;
  height: 20px;
  border-radius: 50%;
  background: #fff;
  border: 2px solid #666;
  cursor: pointer;
}
.ct-slider::-moz-range-thumb {
  width: 20px;
  height: 20px;
  border-radius: 50%;
  background: #fff;
  border: 2px solid #666;
  cursor: pointer;
}
.ct-value {
  font-size: 0.8rem;
  color: #aaa;
  width: 70px;
  text-align: right;
  font-family: 'SF Mono', Monaco, monospace;
}

.btn-icon {
  background: rgba(255,255,255,0.05);
  border: 1px solid rgba(255,255,255,0.1);
  border-radius: 6px;
  padding: 4px;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: all 0.2s;
  margin-left: 4px;
}
.btn-icon:hover { background: rgba(255,255,255,0.15); }
.btn-icon.btn-danger { background: rgba(255,255,255,0.05); border: 1px solid rgba(255,68,68,0.3); }
.btn-icon.btn-danger:hover { background: rgba(255,68,68,0.1); border-color: rgba(255,68,68,0.5); }

@media (max-width: 768px) {
  .device-card { padding: 10px 12px; }
}
</style>
