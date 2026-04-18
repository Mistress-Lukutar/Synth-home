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
          <svg viewBox="0 0 24 24" width="14" height="14" fill="#ff4444">
            <path d="M3 6h18v2H3zm2 3h14v13H5zm3-5h8v2H8z"/>
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

          <!-- Level slider (cluster 0x0008 = 8) -->
          <div v-if="hasCluster(ep, 8)" class="level-control">
            <input
              type="range"
              :min="getState(ep.id, 'level_min') ?? 0"
              :max="getState(ep.id, 'level_max') ?? 255"
              :value="getState(ep.id, 'level') ?? (getState(ep.id, 'level_max') ?? 255) / 2"
              @change="(e) => setLevel(ep.id, Number((e.target as HTMLInputElement).value))"
              :disabled="isPending(ep.id, 'level')"
            />
          </div>

          <!-- Color mode selector (cluster 0x0300 = 768) -->
          <template v-if="hasCluster(ep, 768)">
            <div class="color-mode-row">
              <label class="color-mode-label">Color</label>
              <select v-model="colorModes[ep.id]" class="color-mode-select" @change="onColorModeChange(ep.id)">
                <option value="">—</option>
                <option v-if="colorSupports(ep.id, 'hs')" value="hs">HS</option>
                <option v-if="colorSupports(ep.id, 'xy')" value="xy">XY</option>
                <option v-if="colorSupports(ep.id, 'ct')" value="ct">CT</option>
              </select>
            </div>

            <!-- HS sliders -->
            <template v-if="colorModes[ep.id] === 'hs'">
              <div class="slider-row">
                <label>Hue</label>
                <input type="range" min="0" max="360" :value="getState(ep.id, 'hue') ?? 0" @change="(e) => setColorHs(ep.id, Number((e.target as HTMLInputElement).value), getState(ep.id, 'sat') ?? 100)" />
                <span>{{ getState(ep.id, 'hue') ?? 0 }}</span>
              </div>
              <div class="slider-row">
                <label>Sat</label>
                <input type="range" min="0" max="100" :value="getState(ep.id, 'sat') ?? 100" @change="(e) => setColorHs(ep.id, getState(ep.id, 'hue') ?? 0, Number((e.target as HTMLInputElement).value))" />
                <span>{{ getState(ep.id, 'sat') ?? 100 }}%</span>
              </div>
            </template>

            <!-- XY sliders -->
            <template v-if="colorModes[ep.id] === 'xy'">
              <div class="slider-row">
                <label>X</label>
                <input type="range" min="0" max="1" step="0.01" :value="getState(ep.id, 'x') ?? 0.5" @change="(e) => setColorXy(ep.id, Number((e.target as HTMLInputElement).value), getState(ep.id, 'y') ?? 0.5)" />
                <span>{{ (getState(ep.id, 'x') ?? 0.5).toFixed(2) }}</span>
              </div>
              <div class="slider-row">
                <label>Y</label>
                <input type="range" min="0" max="1" step="0.01" :value="getState(ep.id, 'y') ?? 0.5" @change="(e) => setColorXy(ep.id, getState(ep.id, 'x') ?? 0.5, Number((e.target as HTMLInputElement).value))" />
                <span>{{ (getState(ep.id, 'y') ?? 0.5).toFixed(2) }}</span>
              </div>
            </template>

            <!-- CT slider -->
            <template v-if="colorModes[ep.id] === 'ct'">
              <div class="slider-row">
                <label>CT</label>
                <input type="range" min="153" max="500" :value="getState(ep.id, 'ct') ?? 300" @change="(e) => setCt(ep.id, Number((e.target as HTMLInputElement).value))" />
                <span>{{ getState(ep.id, 'ct') ?? 300 }} mireds</span>
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
import { ref, computed, nextTick, reactive } from 'vue'
import { useHubStore } from '../composables/useHubStore'
import * as api from '../api'

const props = defineProps<{ device: any }>()
const store = useHubStore()

const editing = ref(false)
const editName = ref('')
const inputRef = ref<HTMLInputElement | null>(null)
const colorModes = reactive<Record<number, string>>({})

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
  if (!caps) return true // show all options until caps are known
  return !!caps[cap]
}

function onColorModeChange(epId: number) {
  // when mode changes, read the relevant attributes to populate sliders
  const mode = colorModes[epId]
  if (mode === 'hs') {
    api.readAttr(props.device.ieee, epId, '0x0300', '0x0000').catch(() => {}) // hue
    api.readAttr(props.device.ieee, epId, '0x0300', '0x0001').catch(() => {}) // sat
  } else if (mode === 'xy') {
    api.readAttr(props.device.ieee, epId, '0x0300', '0x0003').catch(() => {}) // x
    api.readAttr(props.device.ieee, epId, '0x0300', '0x0004').catch(() => {}) // y
  } else if (mode === 'ct') {
    api.readAttr(props.device.ieee, epId, '0x0300', '0x0007').catch(() => {}) // ct
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

async function setColorHs(epId: number, hue: number, sat: number) {
  try {
    const result = await api.sendColorHs(props.device.ieee, hue, sat, epId)
    store.state.pendingCommands.set(result.correlation_id, {
      ieee: props.device.ieee,
      endpoint: epId,
      action: 'color',
    })
  } catch (e: any) {
    store.logEvent('color hs error: ' + e.message)
  }
}

async function setColorXy(epId: number, x: number, y: number) {
  try {
    const result = await api.sendColorXy(props.device.ieee, x, y, epId)
    store.state.pendingCommands.set(result.correlation_id, {
      ieee: props.device.ieee,
      endpoint: epId,
      action: 'color',
    })
  } catch (e: any) {
    store.logEvent('color xy error: ' + e.message)
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

/* Level slider */
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
  background: rgba(255,255,255,0.1);
  border: 1px solid rgba(255,255,255,0.2);
  border-radius: 4px;
  color: #fff;
  padding: 4px 8px;
  font-size: 13px;
}

/* Slider rows */
.slider-row {
  display: flex;
  align-items: center;
  gap: 8px;
}
.slider-row label {
  font-size: 0.75rem;
  text-transform: uppercase;
  color: #888;
  width: 30px;
  flex-shrink: 0;
}
.slider-row input[type="range"] {
  flex: 1;
  accent-color: #00ff88;
}
.slider-row span {
  font-size: 0.8rem;
  color: #aaa;
  width: 60px;
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
.btn-icon.btn-danger:hover { background: rgba(255,68,68,0.15); border-color: rgba(255,68,68,0.3); }

@media (max-width: 768px) {
  .device-card { padding: 10px 12px; }
}
</style>
