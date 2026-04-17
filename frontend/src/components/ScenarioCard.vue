<template>
  <div class="list-card">
    <div class="list-info">
      <div class="editable-title">
        <span v-if="!editing" class="title-text" @click="startEdit">{{ scenario.name }}</span>
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
      <div class="list-details">
        <span>{{ details }}</span>
        <span :class="scenario.is_enabled ? 'device-online' : 'device-offline'">{{ scenario.is_enabled ? 'Enabled' : 'Disabled' }}</span>
      </div>
    </div>
    <div class="list-actions">
      <button class="btn btn-small btn-success" @click="run">Run</button>
      <button class="btn btn-small btn-toggle" @click="toggle">{{ scenario.is_enabled ? 'Disable' : 'Enable' }}</button>
      <button class="btn btn-small btn-danger" @click="remove">Delete</button>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, nextTick } from 'vue'
import { useHubStore } from '../composables/useHubStore'
import * as api from '../api'

const props = defineProps<{ scenario: any }>()
const emit = defineEmits(['update'])
const store = useHubStore()

const editing = ref(false)
const editName = ref('')
const inputRef = ref<HTMLInputElement | null>(null)

const details = computed(() => {
  let s = `Trigger: ${props.scenario.trigger_type}`
  if (props.scenario.trigger_type === 'schedule' && props.scenario.trigger_data?.days) {
    const h = String(props.scenario.trigger_data.hour || 0).padStart(2, '0')
    const m = String(props.scenario.trigger_data.minute || 0).padStart(2, '0')
    s += ` · ${props.scenario.trigger_data.days} ${h}:${m}`
  }
  s += ` · Action: ${props.scenario.action_type}`
  return s
})

function startEdit() {
  editing.value = true
  editName.value = props.scenario.name
  nextTick(() => inputRef.value?.focus())
}

function cancel() {
  editing.value = false
}

async function save() {
  editing.value = false
  const newName = editName.value.trim()
  if (!newName || newName === props.scenario.name) return
  try {
    await api.updateScenario(props.scenario.id, { name: newName })
    emit('update')
  } catch (e: any) {
    store.logEvent('Rename failed: ' + e.message)
  }
}

async function run() {
  try {
    await api.triggerScenario(props.scenario.id)
    store.logEvent('Scenario ' + props.scenario.id + ' triggered')
  } catch (e: any) {
    store.logEvent('Trigger failed: ' + e.message)
  }
}

async function toggle() {
  try {
    await api.updateScenario(props.scenario.id, { is_enabled: !props.scenario.is_enabled })
    emit('update')
  } catch (e: any) {
    store.logEvent('Toggle failed: ' + e.message)
  }
}

async function remove() {
  if (!confirm('Delete scenario?')) return
  try {
    await api.deleteScenario(props.scenario.id)
    emit('update')
  } catch (e: any) {
    store.logEvent('Delete failed: ' + e.message)
  }
}
</script>

<style scoped>
.list-card {
  background: rgba(0,0,0,0.2);
  border: 1px solid rgba(255,255,255,0.1);
  border-radius: 10px;
  padding: 12px 16px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  transition: all 0.2s;
}
.list-card:hover { background: rgba(255,255,255,0.05); border-color: rgba(255,255,255,0.2); }
.list-info { display: flex; flex-direction: column; gap: 4px; }
.editable-title { display: flex; align-items: center; gap: 8px; cursor: text; }
.title-text { font-weight: 600; font-size: 1rem; color: #fff; border-bottom: 1px dashed transparent; transition: border-color 0.2s; }
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
.list-details { font-size: 0.8rem; color: #888; display: flex; gap: 12px; flex-wrap: wrap; }
.device-online { color: #00ff88; }
.device-offline { color: #ff4444; }
.list-actions { display: flex; gap: 8px; flex-wrap: wrap; }

.btn { padding: 8px 16px; border: none; border-radius: 6px; cursor: pointer; font-size: 13px; font-weight: 600; transition: all 0.2s; text-transform: uppercase; letter-spacing: 0.5px; }
.btn:disabled { opacity: 0.4; cursor: not-allowed; }
.btn-success { background: #00ff88; color: #111; }
.btn-success:hover { background: #00cc6a; }
.btn-toggle { background: rgba(255,255,255,0.08); border: 1px solid rgba(255,255,255,0.2); color: #fff; }
.btn-toggle:hover { background: rgba(255,255,255,0.15); }
.btn-danger { background: #ff4444; color: white; }
.btn-danger:hover { background: #cc0000; }
.btn-small { padding: 6px 12px; font-size: 12px; }

@media (max-width: 768px) {
  .list-card { flex-direction: column; align-items: flex-start; gap: 10px; }
}
</style>
