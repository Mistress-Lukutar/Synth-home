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
            :class="{ on: getState(ep.id, 'on') === true, pending: isPending(ep.id, 'on') || isPending(ep.id, 'off') || isPending(ep.id, 'toggle') }"
            @click="toggleOnOff(ep.id)"
            title="Toggle On/Off"
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
              :disabled="isPending(ep.id, 'level')"
            />
          </div>

          <!-- Color controls (cluster 0x0300 = 768) -->
          <template v-if="hasCluster(ep, 768)">
            <div class="color-mode-row">
              <label class="color-mode-label">Color</label>
              <select
                class="color-mode-select"
                v-model="uiColorModes[ep.id]"
                @change="onColorModeChange(ep.id, uiColorModes[ep.id])"
              >
                <option v-if="colorSupports(ep.id, 'hs') || colorSupports(ep.id, 'xy')" value="rgb">RGB</option>
                <option v-if="colorSupports(ep.id, 'ct')" value="ct">CT</option>
              </select>
            </div>

            <!-- RGB: Color wheel (hub converts hex → HS or XY) -->
            <template v-if="uiColorModes[ep.id] === 'rgb'">
              <div class="color-picker-row">
                <input
                  type="color"
                  class="color-picker-native"
                  :value="lastHex[ep.id] || '#ffffff'"
                  @change="(e) => setColorRgb(ep.id, (e.target as HTMLInputElement).value)"
                />
              </div>
            </template>

            <!-- CT: Gradient slider -->
            <template v-if="uiColorModes[ep.id] === 'ct'">
              <div class="ct-slider-row">
                <input
                  type="range"
                  :min="getState(ep.id, 'ct_min') ?? 153"
                  :max="getState(ep.id, 'ct_max') ?? 500"
                  class="ct-slider"
                  :value="getState(ep.id, 'ct') ?? 300"
                  @change="(e) => setCt(ep.id, Number((e.target as HTMLInputElement).value))"
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
import { ref, computed, nextTick, reactive, watch, onMounted } from 'vue'
import { useHubStore } from '../composables/useHubStore'
import * as api from '../api'

const props = defineProps<{ device: any }>()
const store = useHubStore()

const editing = ref(false)
const editName = ref('')
const inputRef = ref<HTMLInputElement | null>(null)
const uiColorModes = reactive<Record<number, string>>({})
const lastHex = reactive<Record<number, string>>({})

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

function syncColorModesFromState() {
  for (const ep of props.device.endpoints || []) {
    const mode = getState(ep.id, 'color_mode')
    if (mode === 'hs' || mode === 'xy') {
      uiColorModes[ep.id] = 'rgb'
      // Reconstruct hex from cached state for color picker (using CurrentLevel as brightness)
      const level = getState(ep.id, 'level') ?? 254
      const hue = getState(ep.id, 'hue')
      const sat = getState(ep.id, 'sat')
      const xv = getState(ep.id, 'x')
      const yv = getState(ep.id, 'y')
      if (hue !== undefined && sat !== undefined) {
        lastHex[ep.id] = zclHsToHex(hue, sat, level)
      } else if (xv !== undefined && yv !== undefined) {
        lastHex[ep.id] = zclXyToHex(xv, yv, level)
      }
    } else if (mode === 'ct') {
      uiColorModes[ep.id] = 'ct'
    }
  }
}

onMounted(syncColorModesFromState)
watch(() => props.device.state, syncColorModesFromState, { deep: true })

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
  return !!caps[cap]
}

function onColorModeChange(epId: number, mode: string) {
  if (mode === 'rgb') {
    api.readAttr(props.device.ieee, epId, '0x0300', '0x0000').catch(() => {})
    api.readAttr(props.device.ieee, epId, '0x0300', '0x0001').catch(() => {})
    api.readAttr(props.device.ieee, epId, '0x0300', '0x0003').catch(() => {})
    api.readAttr(props.device.ieee, epId, '0x0300', '0x0004').catch(() => {})
  } else if (mode === 'ct') {
    api.readAttr(props.device.ieee, epId, '0x0300', '0x0007').catch(() => {})
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
    store.state.pendingCommands.set(result.correlation_id, {
      ieee: props.device.ieee,
      endpoint: epId,
      action,
    })
  } catch (e: any) {
    store.logEvent(`Command ${action} error: ` + e.message)
  }
}

async function toggleOnOff(epId: number) {
  const current = getState(epId, 'on') === true
  const action = current ? 'off' : 'on'
  await sendAndTrack(action, epId)
}

async function setLevel(epId: number, level: number) {
  await sendAndTrack('level', epId, { level })
}

async function setColorRgb(epId: number, hex: string) {
  lastHex[epId] = hex
  const caps = getState(epId, 'color_caps') || { hs: true, xy: true }
  // Prefer XY if supported (more compatible), fallback to HS
  const mode = caps.xy ? 'xy' : 'hs'
  try {
    const result = await api.sendColor(props.device.ieee, hex, mode, epId)
    store.state.pendingCommands.set(result.correlation_id, {
      ieee: props.device.ieee,
      endpoint: epId,
      action: 'color',
    })
  } catch (e: any) {
    store.logEvent('color error: ' + e.message)
  }
}

async function setCt(epId: number, ct: number) {
  try {
    const result = await api.sendColorCt(props.device.ieee, ct, epId)
    store.state.pendingCommands.set(result.correlation_id, {
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

/* Color mode row */
.color-mode-row {
  display: flex;
  align-items: center;
  gap: 10px;
}
.color-mode-label {
  font-size: 0.75rem;
  text-transform: uppercase;
  color: #888;
  letter-spacing: 0.5px;
}
.color-mode-select {
  background: rgba(0,0,0,0.4);
  border: 1px solid rgba(255,255,255,0.2);
  border-radius: 4px;
  color: #fff;
  padding: 4px 8px;
  font-size: 13px;
}
.color-mode-select option {
  background: #222;
  color: #fff;
}

/* Color picker */
.color-picker-row {
  display: flex;
  align-items: center;
}
.color-picker-native {
  width: 100%;
  height: 40px;
  border: none;
  border-radius: 8px;
  cursor: pointer;
  background: none;
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
