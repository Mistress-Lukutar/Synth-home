<template>
  <div class="dashboard">
    <div class="dashboard-left">
      <div class="control-panel">
        <div class="panel-header"><h2 class="panel-title">New Scenario</h2></div>
        <form @submit.prevent="submit">
          <div class="form-grid">
            <div class="form-group full-width">
              <label class="form-label">Name</label>
              <input type="text" v-model="form.name" class="input-field" placeholder="Scenario name" required />
            </div>
            <div class="form-group">
              <label class="form-label">Trigger Type</label>
              <select v-model="form.trigger_type" class="input-select" @change="onTriggerChange">
                <option value="manual">Manual</option>
                <option value="device_event">Device Event</option>
                <option value="schedule">Schedule</option>
              </select>
            </div>

            <div v-if="form.trigger_type === 'schedule'" class="schedule-fields full-width">
              <label class="form-label">Days of Week</label>
              <div class="form-checkbox-row">
                <label v-for="day in daysOfWeek" :key="day"><input type="checkbox" v-model="selectedDays" :value="day" checked> {{ day.charAt(0).toUpperCase() + day.slice(1) }}</label>
              </div>
            </div>
            <div v-if="form.trigger_type === 'schedule'" class="schedule-fields">
              <label class="form-label">Time</label>
              <input type="time" v-model="form.time" class="input-field" value="08:00" />
            </div>

            <div v-if="form.trigger_type !== 'manual'" class="form-group full-width">
              <label class="form-label">Trigger Config (JSON)</label>
              <textarea v-model="triggerConfigRaw" class="input-textarea" placeholder='{"event":"device_joined"} or {"cron":"0 7 * * 1,2,5"}'></textarea>
            </div>

            <!-- Actions -->
            <div class="form-group full-width">
              <label class="form-label">Actions</label>
              <div class="actions-list">
                <div v-for="(act, idx) in actions" :key="idx" class="action-row">
                  <select v-model="act.ieee" class="input-select action-device">
                    <option value="">Device...</option>
                    <option v-for="d in store.state.devices" :key="d.ieee" :value="d.ieee">{{ d.name || 'Unknown' }}</option>
                  </select>
                  <select v-model="act.action" class="input-select action-cmd">
                    <option value="on">On</option>
                    <option value="off">Off</option>
                    <option value="toggle">Toggle</option>
                    <option value="level">Level</option>
                    <option value="color">Color</option>
                    <option value="color_ct">CT</option>
                  </select>
                  <input type="text" v-model="act.params" class="input-field action-params" placeholder='{"level":128} or {"hex":"#FF0000"}' />
                  <button type="button" class="btn btn-danger btn-sm" @click="removeAction(idx)" title="Remove">×</button>
                </div>
              </div>
              <button type="button" class="btn btn-secondary btn-sm" @click="addAction">+ Add Action</button>
            </div>

            <div class="form-group full-width">
              <label class="form-checkbox-row">
                <input type="checkbox" v-model="form.is_enabled" checked />
                <span>Enabled</span>
              </label>
            </div>
          </div>
          <div class="form-actions">
            <button type="submit" class="btn btn-success">Create</button>
          </div>
        </form>
      </div>
    </div>
    <div class="dashboard-right">
      <div class="control-panel">
        <div class="panel-header"><h2 class="panel-title">Scenarios</h2></div>
        <div class="list-cards-container">
          <div v-if="store.state.scenarios.length === 0" class="list-empty">No scenarios</div>
          <div
            v-for="(s, index) in store.state.scenarios"
            :key="s.id"
            class="drag-item"
            draggable="true"
            @dragstart="dragStart($event, index)"
            @dragover.prevent
            @drop="drop($event, index)"
          >
            <ScenarioCard :scenario="s" @update="store.loadScenarios" />
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { reactive, ref, onMounted } from 'vue'
import { useHubStore } from '../composables/useHubStore'
import * as api from '../api'
import ScenarioCard from './ScenarioCard.vue'

const store = useHubStore()
const daysOfWeek = ['mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun']

const form = reactive({
  name: '',
  trigger_type: 'manual',
  is_enabled: true,
  time: '08:00',
})
const triggerConfigRaw = ref('')
const selectedDays = ref([...daysOfWeek])

interface ActionForm {
  ieee: string
  action: string
  params: string
}
const actions = ref<ActionForm[]>([{ ieee: '', action: 'toggle', params: '' }])

function addAction() {
  actions.value.push({ ieee: '', action: 'toggle', params: '' })
}
function removeAction(idx: number) {
  if (actions.value.length > 1) actions.value.splice(idx, 1)
}

function onTriggerChange() {
  triggerConfigRaw.value = ''
}

async function submit() {
  const payloadActions: any[] = []
  for (const act of actions.value) {
    if (!act.ieee) {
      alert('Select a target device for every action')
      return
    }
    const actionData: any = { ieee: act.ieee, action: act.action, params: {} }
    if (act.params.trim()) {
      try {
        actionData.params = JSON.parse(act.params.trim())
      } catch {
        alert('Params must be valid JSON or empty')
        return
      }
    }
    payloadActions.push({ action_type: 'command', action_data: actionData })
  }

  let trigger_data: any = null
  if (form.trigger_type === 'schedule') {
    const [h, m] = (form.time || '00:00').split(':')
    trigger_data = {
      days: selectedDays.value.join(','),
      hour: parseInt(h, 10),
      minute: parseInt(m, 10),
    }
  } else if (form.trigger_type === 'device_event' && triggerConfigRaw.value.trim()) {
    try {
      trigger_data = JSON.parse(triggerConfigRaw.value.trim())
    } catch {
      alert('Trigger Config must be valid JSON or empty')
      return
    }
  }

  const payload = {
    name: form.name,
    trigger_type: form.trigger_type,
    trigger_data,
    actions: payloadActions,
    is_enabled: form.is_enabled,
    sort_order: store.state.scenarios.length,
  }

  try {
    await api.createScenario(payload)
    form.name = ''
    triggerConfigRaw.value = ''
    actions.value = [{ ieee: '', action: 'toggle', params: '' }]
    await store.loadScenarios()
  } catch (e: any) {
    alert('Failed to create scenario')
  }
}

let dragIndex = -1

function dragStart(e: DragEvent, index: number) {
  dragIndex = index
  if (e.dataTransfer) {
    e.dataTransfer.effectAllowed = 'move'
    e.dataTransfer.setData('text/plain', String(index))
  }
}

function drop(e: DragEvent, index: number) {
  e.preventDefault()
  const from = dragIndex
  if (from === -1 || from === index) return
  store.reorderScenarios(from, index)
  dragIndex = -1
}

onMounted(() => {
  store.loadScenarios()
})
</script>

<style scoped>
.dashboard {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 20px;
  align-items: start;
}
.dashboard-left, .dashboard-right {
  display: grid;
  grid-template-rows: auto auto;
  gap: 20px;
  align-content: start;
}
.control-panel {
  background: rgba(255,255,255,0.05);
  border-radius: 12px;
  padding: 20px;
  backdrop-filter: blur(10px);
  display: flex;
  flex-direction: column;
  overflow: hidden;
}
.panel-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 15px; flex-shrink: 0; }
.panel-title { font-size: 1rem; color: #aaa; text-transform: uppercase; letter-spacing: 1px; flex-shrink: 0; }
.form-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }
.form-group { display: flex; flex-direction: column; gap: 4px; }
.form-group.full-width { grid-column: 1 / -1; }
.form-label { font-size: 0.75rem; text-transform: uppercase; color: #888; letter-spacing: 0.5px; }
.input-field, .input-select, .input-textarea {
  padding: 8px 12px;
  border-radius: 6px;
  border: none;
  background: rgba(255,255,255,0.1);
  color: white;
  font-size: 13px;
}
.input-field:focus, .input-select:focus, .input-textarea:focus { outline: 2px solid rgba(255,255,255,0.3); }
.input-select option { background: #222; color: #fff; }
.input-textarea { font-family: 'SF Mono', Monaco, monospace; min-height: 60px; resize: vertical; }
.form-checkbox-row { display: flex; flex-wrap: wrap; gap: 10px; align-items: center; }
.form-checkbox-row label { display: flex; align-items: center; gap: 4px; font-size: 0.85rem; color: #ccc; cursor: pointer; }
.form-actions { display: flex; gap: 10px; margin-top: 8px; }
.schedule-fields { display: contents; }
.list-cards-container { display: flex; flex-direction: column; gap: 10px; flex: 1; overflow-y: auto; min-height: 0; }
.drag-item { cursor: grab; }
.drag-item:active { cursor: grabbing; }
.list-cards-container::-webkit-scrollbar { width: 6px; }
.list-cards-container::-webkit-scrollbar-track { background: rgba(0,0,0,0.1); border-radius: 3px; }
.list-cards-container::-webkit-scrollbar-thumb { background: rgba(255,255,255,0.2); border-radius: 3px; }
.list-empty { text-align: center; color: #666; padding: 30px; font-style: italic; }

/* Multi-action rows */
.actions-list { display: flex; flex-direction: column; gap: 8px; margin-bottom: 8px; }
.action-row {
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
.btn-secondary { background: rgba(255,255,255,0.1); color: #fff; border: 1px solid rgba(255,255,255,0.2); }
.btn-secondary:hover { background: rgba(255,255,255,0.2); }
.btn-danger { background: transparent; border: 1px solid rgba(255,68,68,0.4); color: #ff4444; }
.btn-danger:hover { background: rgba(255,68,68,0.1); }
.btn-sm { padding: 4px 10px; font-size: 12px; }

@media (max-width: 1200px) {
  .dashboard { grid-template-columns: 1fr; }
}
@media (max-width: 768px) {
  .form-grid { grid-template-columns: 1fr; }
  .action-row { flex-wrap: wrap; }
}
</style>
