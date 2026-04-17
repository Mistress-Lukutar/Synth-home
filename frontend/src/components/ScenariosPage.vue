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
            <div class="form-group">
              <label class="form-label">Action Type</label>
              <select v-model="form.action_type" class="input-select">
                <option value="command">Command</option>
              </select>
            </div>
            <div class="form-group full-width">
              <label class="form-label">Target Device</label>
              <select v-model="selectedDevice" class="input-select">
                <option value="">Select device...</option>
                <option v-for="d in store.state.devices" :key="d.ieee" :value="d.ieee">{{ d.name || 'Unknown' }} ({{ d.ieee }})</option>
              </select>
            </div>
            <div class="form-group">
              <label class="form-label">Action</label>
              <select v-model="form.action" class="input-select">
                <option value="on">On</option>
                <option value="off">Off</option>
                <option value="toggle" selected>Toggle</option>
                <option value="level">Level</option>
                <option value="color">Color</option>
              </select>
            </div>
            <div class="form-group">
              <label class="form-label">Params (JSON)</label>
              <input type="text" v-model="paramsRaw" class="input-field" placeholder='{"level":128}' />
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
          <ScenarioCard v-for="s in store.state.scenarios" :key="s.id" :scenario="s" @update="store.loadScenarios" />
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { reactive, ref, watch, onMounted } from 'vue'
import { useHubStore } from '../composables/useHubStore'
import * as api from '../api'
import ScenarioCard from './ScenarioCard.vue'

const store = useHubStore()
const daysOfWeek = ['mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun']

const form = reactive({
  name: '',
  trigger_type: 'manual',
  action_type: 'command',
  action: 'toggle',
  is_enabled: true,
  time: '08:00',
})
const selectedDevice = ref('')
const paramsRaw = ref('')
const triggerConfigRaw = ref('')
const selectedDays = ref([...daysOfWeek])

function onTriggerChange() {
  triggerConfigRaw.value = ''
}

async function submit() {
  if (!selectedDevice.value) {
    alert('Select a target device')
    return
  }
  let action_data: any = { ieee: selectedDevice.value, action: form.action, params: {} }
  if (paramsRaw.value.trim()) {
    try {
      action_data.params = JSON.parse(paramsRaw.value.trim())
    } catch {
      alert('Params must be valid JSON or empty')
      return
    }
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
    trigger_data: trigger_data,
    action_type: form.action_type,
    action_data,
    is_enabled: form.is_enabled,
  }

  try {
    await api.createScenario(payload)
    form.name = ''
    paramsRaw.value = ''
    triggerConfigRaw.value = ''
    selectedDevice.value = ''
    await store.loadScenarios()
  } catch (e: any) {
    alert('Failed to create scenario')
  }
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
.list-cards-container::-webkit-scrollbar { width: 6px; }
.list-cards-container::-webkit-scrollbar-track { background: rgba(0,0,0,0.1); border-radius: 3px; }
.list-cards-container::-webkit-scrollbar-thumb { background: rgba(255,255,255,0.2); border-radius: 3px; }
.list-empty { text-align: center; color: #666; padding: 30px; font-style: italic; }

.btn { padding: 8px 16px; border: none; border-radius: 6px; cursor: pointer; font-size: 13px; font-weight: 600; transition: all 0.2s; text-transform: uppercase; letter-spacing: 0.5px; }
.btn-success { background: #00ff88; color: #111; }
.btn-success:hover { background: #00cc6a; }

@media (max-width: 1200px) {
  .dashboard { grid-template-columns: 1fr; }
}
@media (max-width: 768px) {
  .form-grid { grid-template-columns: 1fr; }
}
</style>
