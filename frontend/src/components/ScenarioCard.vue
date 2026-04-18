<template>
  <div class="list-card" :class="{ 'is-editing': showEdit }">
    <div class="card-main">
      <div class="card-left">
        <div class="drag-handle" title="Drag to reorder">
          <svg viewBox="0 0 24 24" width="16" height="16" fill="#666">
            <circle cx="9" cy="6" r="2"/><circle cx="15" cy="6" r="2"/>
            <circle cx="9" cy="12" r="2"/><circle cx="15" cy="12" r="2"/>
            <circle cx="9" cy="18" r="2"/><circle cx="15" cy="18" r="2"/>
          </svg>
        </div>
        <input
          type="checkbox"
          class="enable-check"
          :checked="scenario.is_enabled"
          @change="toggle"
          title="Enable / Disable"
        />
      </div>
      <div class="list-info">
        <div class="editable-title">
          <span v-if="!editingName" class="title-text" @click="startNameEdit">{{ scenario.name }}</span>
          <svg v-if="!editingName" class="edit-icon" @click="startNameEdit" viewBox="0 0 24 24"><path d="M3 17.25V21h3.75L17.81 9.94l-3.75-3.75L3 17.25zM20.71 7.04c.39-.39.39-1.02 0-1.41l-2.34-2.34c-.39-.39-1.02-.39-1.41 0l-1.83 1.83 3.75 3.75 1.83-1.83z"/></svg>
          <input
            v-else
            ref="nameInputRef"
            v-model="editName"
            class="title-input"
            @keydown.enter="saveName"
            @keydown.esc="cancelName"
            @blur="saveName"
          />
        </div>
        <div class="list-details">
          <span>{{ details }}</span>
        </div>
        <div class="actions-summary">
          <span v-for="(act, i) in actionSummaries" :key="i" class="action-badge">{{ act }}</span>
        </div>
      </div>
      <div class="list-actions">
        <button class="btn-icon" @click="run" title="Run">
          <svg viewBox="0 0 24 24" width="18" height="18" fill="#00ff88">
            <polygon points="5,3 19,12 5,21"/>
          </svg>
        </button>
        <button class="btn-icon" :class="{ active: showEdit }" @click="toggleEdit" title="Edit">
          <svg viewBox="0 0 24 24" width="18" height="18" fill="#888">
            <path d="M3 17.25V21h3.75L17.81 9.94l-3.75-3.75L3 17.25zM20.71 7.04c.39-.39.39-1.02 0-1.41l-2.34-2.34c-.39-.39-1.02-.39-1.41 0l-1.83 1.83 3.75 3.75 1.83-1.83z"/>
          </svg>
        </button>
        <button class="btn-icon btn-danger" @click="remove" title="Delete">
          <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="#ff4444" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <path d="M3 6h18"/>
            <path d="M19 6v14a2 2 0 01-2 2H7a2 2 0 01-2-2V6"/>
            <path d="M8 6V4a2 2 0 012-2h4a2 2 0 012 2v2"/>
            <path d="M10 11v6"/>
            <path d="M14 11v6"/>
          </svg>
        </button>
      </div>
    </div>

    <div v-if="showEdit" class="edit-panel">
      <div class="edit-form">
        <div class="edit-row">
          <label class="edit-label">Trigger Type</label>
          <select v-model="editForm.trigger_type" class="edit-input" @change="onTriggerChange">
            <option value="manual">Manual</option>
            <option value="device_event">Device Event</option>
            <option value="schedule">Schedule</option>
          </select>
        </div>

        <template v-if="editForm.trigger_type === 'schedule'">
          <div class="edit-row">
            <label class="edit-label">Days of Week</label>
            <div class="checkbox-row">
              <label v-for="day in daysOfWeek" :key="day">
                <input type="checkbox" v-model="editForm.days" :value="day" /> {{ day.charAt(0).toUpperCase() + day.slice(1) }}
              </label>
            </div>
          </div>
          <div class="edit-row">
            <label class="edit-label">Time</label>
            <input type="time" v-model="editForm.time" class="edit-input" />
          </div>
        </template>

        <template v-if="editForm.trigger_type === 'device_event'">
          <div class="edit-row">
            <label class="edit-label">Trigger Config (JSON)</label>
            <input type="text" v-model="editForm.trigger_config" class="edit-input" placeholder='{"event":"device_joined"}' />
          </div>
        </template>

        <!-- Actions editor -->
        <div class="edit-row full-width">
          <label class="edit-label">Actions</label>
          <div class="actions-editor">
            <div v-for="(act, idx) in editForm.actions" :key="idx" class="action-edit-row">
              <select v-model="act.ieee" class="edit-input action-device">
                <option value="">Device...</option>
                <option v-for="d in store.state.devices" :key="d.ieee" :value="d.ieee">{{ d.name || 'Unknown' }}</option>
              </select>
              <select v-model="act.action" class="edit-input action-cmd">
                <option value="on">On</option>
                <option value="off">Off</option>
                <option value="toggle">Toggle</option>
                <option value="level">Level</option>
                <option value="color">Color</option>
                <option value="color_ct">CT</option>
              </select>
              <input type="text" v-model="act.params" class="edit-input action-params" placeholder='{"level":128}' />
              <button type="button" class="btn btn-danger btn-sm" @click="removeEditAction(idx)">×</button>
            </div>
          </div>
          <button type="button" class="btn btn-secondary btn-sm" @click="addEditAction">+ Add Action</button>
        </div>
      </div>
      <div class="edit-actions">
        <button class="btn btn-success" @click="saveEdit">Save</button>
        <button class="btn btn-secondary" @click="copyScenario">Copy</button>
        <button class="btn btn-toggle" @click="cancelEdit">Cancel</button>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, computed, nextTick, watch } from 'vue'
import { useHubStore } from '../composables/useHubStore'
import * as api from '../api'

const props = defineProps<{ scenario: any }>()
const emit = defineEmits(['update'])
const store = useHubStore()
const daysOfWeek = ['mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun']

// Inline name edit
const editingName = ref(false)
const editName = ref('')
const nameInputRef = ref<HTMLInputElement | null>(null)

// Full scenario edit
const showEdit = ref(false)

interface EditAction {
  ieee: string
  action: string
  params: string
}

const editForm = reactive({
  name: '',
  trigger_type: 'manual',
  days: [...daysOfWeek],
  time: '08:00',
  trigger_config: '',
  is_enabled: true,
  actions: [] as EditAction[],
})

const actionSummaries = computed(() => {
  const acts = props.scenario.actions || []
  return acts.map((act: any) => {
    const data = act.action_data || {}
    const device = store.state.devices.find((d: any) => d.ieee === data.ieee)
    const name = device?.name || data.ieee || '?'
    let extra = ''
    if (data.action === 'color' && data.params?.hex) extra = ` ${data.params.hex}`
    else if (data.action === 'color_ct' && data.params?.ct) extra = ` ${data.params.ct}K`
    else if (data.action === 'level' && data.params?.level != null) extra = ` ${data.params.level}`
    return `${name}: ${data.action}${extra}`
  })
})

const details = computed(() => {
  let s = `Trigger: ${props.scenario.trigger_type}`
  if (props.scenario.trigger_type === 'schedule' && props.scenario.trigger_data?.days) {
    const h = String(props.scenario.trigger_data.hour || 0).padStart(2, '0')
    const m = String(props.scenario.trigger_data.minute || 0).padStart(2, '0')
    s += ` · ${props.scenario.trigger_data.days} ${h}:${m}`
  }
  s += ` · ${(props.scenario.actions || []).length} action(s)`
  return s
})

function startNameEdit() {
  editingName.value = true
  editName.value = props.scenario.name
  nextTick(() => nameInputRef.value?.focus())
}

function cancelName() {
  editingName.value = false
}

async function saveName() {
  editingName.value = false
  const newName = editName.value.trim()
  if (!newName || newName === props.scenario.name) return
  try {
    await api.updateScenario(props.scenario.id, { name: newName })
    emit('update')
  } catch (e: any) {
    store.logEvent('Rename failed: ' + e.message)
  }
}

function addEditAction() {
  editForm.actions.push({ ieee: '', action: 'toggle', params: '' })
}
function removeEditAction(idx: number) {
  if (editForm.actions.length > 1) editForm.actions.splice(idx, 1)
}

function toggleEdit() {
  if (showEdit.value) {
    showEdit.value = false
    return
  }
  // Fill form from current scenario
  editForm.name = props.scenario.name
  editForm.trigger_type = props.scenario.trigger_type
  editForm.is_enabled = props.scenario.is_enabled

  const acts = props.scenario.actions || []
  editForm.actions = acts.map((act: any) => {
    const data = act.action_data || {}
    return {
      ieee: data.ieee || '',
      action: data.action || 'toggle',
      params: data.params ? JSON.stringify(data.params) : '',
    }
  })
  if (editForm.actions.length === 0) {
    editForm.actions.push({ ieee: '', action: 'toggle', params: '' })
  }

  if (props.scenario.trigger_type === 'schedule') {
    const td = props.scenario.trigger_data || {}
    editForm.days = (td.days || 'mon,tue,wed,thu,fri,sat,sun').split(',')
    editForm.time = `${String(td.hour || 0).padStart(2, '0')}:${String(td.minute || 0).padStart(2, '0')}`
    editForm.trigger_config = ''
  } else if (props.scenario.trigger_type === 'device_event') {
    editForm.trigger_config = props.scenario.trigger_data ? JSON.stringify(props.scenario.trigger_data) : ''
    editForm.days = [...daysOfWeek]
    editForm.time = '08:00'
  } else {
    editForm.trigger_config = ''
    editForm.days = [...daysOfWeek]
    editForm.time = '08:00'
  }

  showEdit.value = true
}

function onTriggerChange() {
  editForm.trigger_config = ''
  editForm.days = [...daysOfWeek]
  editForm.time = '08:00'
}

function cancelEdit() {
  showEdit.value = false
}

async function copyScenario() {
  const payloadActions: any[] = []
  for (const act of editForm.actions) {
    if (!act.ieee) {
      store.logEvent('Select a target device for every action')
      return
    }
    const actionData: any = { ieee: act.ieee, action: act.action, params: {} }
    if (act.params.trim()) {
      try {
        actionData.params = JSON.parse(act.params.trim())
      } catch {
        store.logEvent('Params must be valid JSON')
        return
      }
    }
    payloadActions.push({ action_type: 'command', action_data: actionData })
  }

  let trigger_data: any = null
  if (editForm.trigger_type === 'schedule') {
    const [h, m] = (editForm.time || '00:00').split(':')
    trigger_data = {
      days: editForm.days.join(','),
      hour: parseInt(h, 10),
      minute: parseInt(m, 10),
    }
  } else if (editForm.trigger_type === 'device_event' && editForm.trigger_config.trim()) {
    try {
      trigger_data = JSON.parse(editForm.trigger_config.trim())
    } catch {
      store.logEvent('Trigger Config must be valid JSON')
      return
    }
  }

  const payload = {
    name: editForm.name + ' (copy)',
    trigger_type: editForm.trigger_type,
    trigger_data,
    actions: payloadActions,
    is_enabled: editForm.is_enabled,
    sort_order: store.state.scenarios.length,
  }

  try {
    await api.createScenario(payload)
    showEdit.value = false
    emit('update')
  } catch (e: any) {
    store.logEvent('Copy failed: ' + e.message)
  }
}

async function saveEdit() {
  const payloadActions: any[] = []
  for (const act of editForm.actions) {
    if (!act.ieee) {
      store.logEvent('Select a target device for every action')
      return
    }
    const actionData: any = { ieee: act.ieee, action: act.action, params: {} }
    if (act.params.trim()) {
      try {
        actionData.params = JSON.parse(act.params.trim())
      } catch {
        store.logEvent('Params must be valid JSON')
        return
      }
    }
    payloadActions.push({ action_type: 'command', action_data: actionData })
  }

  let trigger_data: any = null
  if (editForm.trigger_type === 'schedule') {
    const [h, m] = (editForm.time || '00:00').split(':')
    trigger_data = {
      days: editForm.days.join(','),
      hour: parseInt(h, 10),
      minute: parseInt(m, 10),
    }
  } else if (editForm.trigger_type === 'device_event' && editForm.trigger_config.trim()) {
    try {
      trigger_data = JSON.parse(editForm.trigger_config.trim())
    } catch {
      store.logEvent('Trigger Config must be valid JSON')
      return
    }
  }

  const payload = {
    name: editForm.name,
    trigger_type: editForm.trigger_type,
    trigger_data,
    actions: payloadActions,
    is_enabled: editForm.is_enabled,
  }

  try {
    await api.updateScenario(props.scenario.id, payload)
    showEdit.value = false
    emit('update')
  } catch (e: any) {
    store.logEvent('Update failed: ' + e.message)
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
  flex-direction: column;
  gap: 12px;
  transition: all 0.2s;
}
.list-card:hover { background: rgba(255,255,255,0.05); border-color: rgba(255,255,255,0.2); }
.list-card.is-editing { border-color: rgba(0,255,136,0.3); }

.card-main {
  display: flex;
  align-items: center;
  gap: 12px;
}

.card-left {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-shrink: 0;
}

.drag-handle {
  cursor: grab;
  display: flex;
  align-items: center;
  padding: 4px;
  border-radius: 4px;
  transition: background 0.2s;
}
.drag-handle:hover { background: rgba(255,255,255,0.1); }
.drag-handle:active { cursor: grabbing; }

.enable-check {
  width: 18px;
  height: 18px;
  accent-color: #00ff88;
  cursor: pointer;
}

.list-info { display: flex; flex-direction: column; gap: 4px; flex: 1; min-width: 0; }
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
.actions-summary { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 4px; }
.action-badge {
  background: rgba(255,255,255,0.08);
  border: 1px solid rgba(255,255,255,0.15);
  border-radius: 4px;
  padding: 2px 8px;
  font-size: 0.75rem;
  color: #ccc;
}

.list-actions { display: flex; gap: 8px; flex-shrink: 0; }

.btn-icon {
  background: rgba(255,255,255,0.05);
  border: 1px solid rgba(255,255,255,0.1);
  border-radius: 6px;
  padding: 6px;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: all 0.2s;
}
.btn-icon:hover { background: rgba(255,255,255,0.15); border-color: rgba(255,255,255,0.25); }
.btn-icon.active { background: rgba(0,255,136,0.15); border-color: rgba(0,255,136,0.4); }
.btn-icon.active svg { fill: #00ff88; }
.btn-icon.btn-danger { background: rgba(255,255,255,0.05); border: 1px solid rgba(255,68,68,0.3); }
.btn-icon.btn-danger:hover { background: rgba(255,68,68,0.1); border-color: rgba(255,68,68,0.5); }

.edit-panel {
  border-top: 1px solid rgba(255,255,255,0.1);
  padding-top: 12px;
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.edit-form {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 10px;
}
.edit-row {
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.edit-row.full-width {
  grid-column: 1 / -1;
}
.edit-label {
  font-size: 0.75rem;
  text-transform: uppercase;
  color: #888;
  letter-spacing: 0.5px;
}
.edit-input {
  padding: 8px 12px;
  border-radius: 6px;
  border: none;
  background: rgba(255,255,255,0.1);
  color: white;
  font-size: 13px;
}
.edit-input:focus { outline: 2px solid rgba(255,255,255,0.3); }
.edit-input option { background: #222; color: #fff; }
.checkbox-row { display: flex; flex-wrap: wrap; gap: 10px; align-items: center; }
.checkbox-row label { display: flex; align-items: center; gap: 4px; font-size: 0.85rem; color: #ccc; cursor: pointer; }

.edit-actions { display: flex; gap: 10px; }

/* Multi-action editor inside card */
.actions-editor { display: flex; flex-direction: column; gap: 8px; margin-bottom: 8px; }
.action-edit-row {
  display: flex;
  gap: 8px;
  align-items: center;
}
.action-device { flex: 2; }
.action-cmd { flex: 1; min-width: 80px; }
.action-params { flex: 2; }

.btn { padding: 8px 16px; border: none; border-radius: 6px; cursor: pointer; font-size: 13px; font-weight: 600; transition: all 0.2s; text-transform: uppercase; letter-spacing: 0.5px; }
.btn-success { background: #00ff88; color: #111; }
.btn-success:hover { background: #00cc6a; }
.btn-toggle { background: rgba(255,255,255,0.08); border: 1px solid rgba(255,255,255,0.2); color: #fff; }
.btn-toggle:hover { background: rgba(255,255,255,0.15); }
.btn-secondary { background: rgba(255,255,255,0.1); color: #fff; border: 1px solid rgba(255,255,255,0.2); }
.btn-secondary:hover { background: rgba(255,255,255,0.2); }
.btn-danger { background: transparent; border: 1px solid rgba(255,68,68,0.4); color: #ff4444; }
.btn-danger:hover { background: rgba(255,68,68,0.1); }
.btn-sm { padding: 4px 10px; font-size: 12px; }

@media (max-width: 768px) {
  .card-main { flex-direction: column; align-items: flex-start; gap: 10px; }
  .list-actions { align-self: flex-end; }
  .edit-form { grid-template-columns: 1fr; }
  .edit-row.full-width { grid-column: auto; }
  .action-edit-row { flex-wrap: wrap; }
}
</style>
