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
      <button class="btn btn-small btn-on" @click="sendCmd('on')">On</button>
      <button class="btn btn-small btn-off" @click="sendCmd('off')">Off</button>
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

async function sendCmd(action: string) {
  if (!store.state.isConnected) return
  store.logEvent(`Command ${action} → ${props.device.ieee}`)
  try {
    await api.sendCommand(props.device.ieee, action)
  } catch (e: any) {
    store.logEvent('Command error: ' + e.message)
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
.device-actions { display: flex; gap: 8px; flex-wrap: wrap; }
.btn-small { padding: 6px 12px; font-size: 12px; }
.btn-on { background: rgba(0,255,136,0.15); border: 1px solid rgba(0,255,136,0.4); color: #00ff88; }
.btn-on:hover { background: rgba(0,255,136,0.25); }
.btn-off { background: rgba(255,68,68,0.15); border: 1px solid rgba(255,68,68,0.4); color: #ff4444; }
.btn-off:hover { background: rgba(255,68,68,0.25); }

@media (max-width: 768px) {
  .device-card { flex-direction: column; align-items: flex-start; gap: 10px; }
}
</style>
