<template>
  <div class="device-card">
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
      </div>
      <div class="device-details">
        <span class="device-ieee">{{ device.ieee }}</span>
        <span>EP {{ device.endpoint ?? '-' }}</span>
        <span :class="device.online !== false ? 'device-online' : 'device-offline'">{{ device.online !== false ? 'Online' : 'Offline' }}</span>
      </div>
    </div>
    <div class="device-actions">
      <div
        class="toggle-switch"
        :class="{ on: localState === 'on', pending: localState === 'pending' }"
        @click="toggle"
      >
        <div class="knob"></div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, nextTick } from 'vue'
import { useHubStore } from '../composables/useHubStore'
import * as api from '../api'

const props = defineProps<{ device: any }>()
const store = useHubStore()

const editing = ref(false)
const editName = ref('')
const inputRef = ref<HTMLInputElement | null>(null)

// Local toggle state: off -> on, on -> off. Defaults to off.
const localState = ref<'off' | 'on' | 'pending'>('off')

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

async function toggle() {
  if (!store.state.isConnected || localState.value === 'pending') return

  const target = localState.value === 'on' ? 'off' : 'on'
  const action = target === 'on' ? 'on' : 'off'
  localState.value = 'pending'

  store.logEvent(`Command ${action} → ${props.device.ieee}`)
  try {
    await api.sendCommand(props.device.ieee, action)
    localState.value = target
  } catch (e: any) {
    store.logEvent('Command error: ' + e.message)
    // Revert to previous state on failure
    localState.value = target === 'on' ? 'off' : 'on'
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
  align-items: center;
  justify-content: space-between;
  transition: all 0.2s;
}
.device-card:hover { background: rgba(255,255,255,0.05); border-color: rgba(255,255,255,0.2); }
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
.device-actions { display: flex; gap: 8px; flex-wrap: wrap; align-items: center; }

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
.toggle-switch.pending {
  cursor: wait;
}
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
.toggle-switch.on {
  background: #00ff88;
}
.toggle-switch.on .knob {
  left: 29px;
}
.toggle-switch.pending {
  background: #ffaa00;
}
.toggle-switch.pending .knob {
  left: 16px;
}

@media (max-width: 768px) {
  .device-card { flex-direction: column; align-items: flex-start; gap: 10px; }
}
</style>
