<template>
  <div class="panel-card" :class="{ disabled: !panel.is_enabled }">
    <div class="panel-card-header">
      <input
        v-if="editingName"
        v-model="nameEdit"
        class="panel-name-input"
        @blur="finishRename"
        @keyup.enter="finishRename"
        ref="nameInput"
      />
      <h3 v-else class="panel-name" @click="startRename">{{ panel.name }}</h3>
      <div class="panel-actions">
        <button class="btn-icon" title="Toggle enabled" @click="toggleEnabled">
          {{ panel.is_enabled ? '●' : '○' }}
        </button>
        <button class="btn-icon" title="Edit graph" @click="$emit('edit', panel.id)">✎</button>
        <button class="btn-icon" title="Delete" @click="$emit('delete', panel.id)">×</button>
      </div>
    </div>
    <div v-if="loading" class="panel-loading">Loading…</div>
    <div v-else class="panel-controls">
      <template v-for="node in uiInputNodes" :key="node.id">
        <div class="control-row" v-if="node.type === 'panel_switch_input'">
          <span class="control-label">{{ node.data.label || 'Switch' }}</span>
          <label class="switch">
            <input
              type="checkbox"
              :checked="inputValues[node.id] || false"
              @change="e => onInputChange(node.id, (e.target as HTMLInputElement).checked)"
            />
            <span class="slider"></span>
          </label>
        </div>
        <div class="control-row" v-else-if="node.type === 'panel_int_input'">
          <span class="control-label">{{ node.data.label || 'Value' }}</span>
          <input
            type="range"
            class="control-slider"
            :min="node.data.min ?? 0"
            :max="node.data.max ?? 255"
            :value="inputValues[node.id] ?? 0"
            @input="e => onInputChange(node.id, parseInt((e.target as HTMLInputElement).value))"
          />
          <span class="control-value">{{ inputValues[node.id] ?? 0 }}</span>
        </div>
        <div class="control-row" v-else-if="node.type === 'panel_button_input'">
          <button
            class="btn btn-primary btn-small"
            @click="onInputChange(node.id, true)"
          >
            {{ node.data.label || 'Button' }}
          </button>
        </div>
      </template>
      <template v-for="node in uiOutputNodes" :key="node.id">
        <div class="control-row output" v-if="node.type === 'panel_int_output'">
          <span class="control-label">{{ node.data.label || 'Value' }}</span>
          <span class="output-value">{{ outputValues[node.id] ?? '-' }}</span>
        </div>
        <div class="control-row output" v-else-if="node.type === 'panel_text_output'">
          <span class="control-label">{{ node.data.label || 'Status' }}</span>
          <span class="output-value">{{ outputValues[node.id] ?? '-' }}</span>
        </div>
      </template>
      <div v-if="uiInputNodes.length === 0 && uiOutputNodes.length === 0" class="panel-placeholder">
        <span class="placeholder-icon">◈</span>
        <span class="placeholder-text">No UI nodes in graph</span>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, computed } from 'vue'
import type { Panel } from '../composables/useHubStore'
import { useHubStore } from '../composables/useHubStore'
import * as api from '../api'

interface GraphNode {
  id: string
  type: string
  data: Record<string, any>
}

const props = defineProps<{
  panel: Panel
}>()

const emit = defineEmits<{
  (e: 'edit', id: number): void
  (e: 'delete', id: number): void
  (e: 'update', id: number, data: Partial<Panel>): void
}>()

const store = useHubStore()
const editingName = ref(false)
const nameEdit = ref('')
const nameInput = ref<HTMLInputElement | null>(null)
const loading = ref(true)
const graphNodes = ref<GraphNode[]>([])
const inputValues = ref<Record<string, any>>({})

const outputValues = computed(() => {
  const outs: Record<string, any> = {}
  const panelOuts = store.state.panelOutputs[props.panel.id]
  if (panelOuts) {
    for (const [key, val] of Object.entries(panelOuts)) {
      if (key.startsWith('_out_')) {
        outs[key.slice(5)] = val
      }
    }
  }
  return outs
})

const uiInputNodes = computed(() =>
  graphNodes.value.filter(n => ['panel_switch_input', 'panel_int_input', 'panel_button_input'].includes(n.type))
)
const uiOutputNodes = computed(() =>
  graphNodes.value.filter(n => ['panel_int_output', 'panel_text_output'].includes(n.type))
)

onMounted(async () => {
  try {
    const graph = await api.getGraph(props.panel.id)
    graphNodes.value = graph.nodes || []
    const state = await api.getPanelState(props.panel.id)
    inputValues.value = state.inputs || {}
  } catch (e: any) {
    console.error('Failed to load panel graph:', e)
  } finally {
    loading.value = false
  }
})

async function onInputChange(nodeId: string, value: any) {
  inputValues.value[nodeId] = value
  try {
    await api.setPanelInput(props.panel.id, nodeId, value)
  } catch (e: any) {
    console.error('Input update failed:', e)
  }
}

function startRename() {
  nameEdit.value = props.panel.name
  editingName.value = true
  setTimeout(() => nameInput.value?.focus(), 0)
}

function finishRename() {
  editingName.value = false
  const trimmed = nameEdit.value.trim()
  if (trimmed && trimmed !== props.panel.name) {
    emit('update', props.panel.id, { name: trimmed })
  }
}

function toggleEnabled() {
  emit('update', props.panel.id, { is_enabled: !props.panel.is_enabled })
}
</script>

<style scoped>
.panel-card {
  background: rgba(255,255,255,0.05);
  border-radius: 12px;
  padding: 16px;
  backdrop-filter: blur(10px);
  transition: opacity 0.3s;
  display: flex;
  flex-direction: column;
  gap: 12px;
  min-height: 120px;
}
.panel-card.disabled {
  opacity: 0.5;
}

.panel-card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 8px;
}

.panel-name {
  font-size: 0.95rem;
  font-weight: 600;
  color: #fff;
  margin: 0;
  cursor: pointer;
  flex: 1;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.panel-name:hover {
  color: #00ff88;
}

.panel-name-input {
  flex: 1;
  background: rgba(0,0,0,0.3);
  border: 1px solid rgba(0,255,136,0.3);
  border-radius: 6px;
  padding: 4px 8px;
  color: #fff;
  font-size: 0.95rem;
  outline: none;
}

.panel-actions {
  display: flex;
  gap: 4px;
  flex-shrink: 0;
}

.btn-icon {
  background: transparent;
  border: none;
  color: #888;
  cursor: pointer;
  font-size: 1rem;
  width: 28px;
  height: 28px;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: 6px;
  transition: all 0.2s;
}
.btn-icon:hover {
  background: rgba(255,255,255,0.1);
  color: #fff;
}

.panel-loading {
  text-align: center;
  color: #666;
  font-size: 0.85rem;
  padding: 20px;
}

.panel-controls {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.control-row {
  display: flex;
  align-items: center;
  gap: 10px;
}
.control-row.output {
  justify-content: space-between;
}

.control-label {
  font-size: 0.85rem;
  color: #aaa;
  min-width: 60px;
}

.control-value {
  font-size: 0.85rem;
  color: #fff;
  min-width: 30px;
  text-align: right;
}

.output-value {
  font-size: 0.9rem;
  color: #00ff88;
  font-weight: 600;
}

/* Toggle switch */
.switch {
  position: relative;
  display: inline-block;
  width: 40px;
  height: 22px;
}
.switch input {
  opacity: 0;
  width: 0;
  height: 0;
}
.slider {
  position: absolute;
  cursor: pointer;
  top: 0; left: 0; right: 0; bottom: 0;
  background-color: #444;
  transition: .3s;
  border-radius: 22px;
}
.slider:before {
  position: absolute;
  content: "";
  height: 16px;
  width: 16px;
  left: 3px;
  bottom: 3px;
  background-color: white;
  transition: .3s;
  border-radius: 50%;
}
input:checked + .slider {
  background-color: #00ff88;
}
input:checked + .slider:before {
  transform: translateX(18px);
}

.control-slider {
  flex: 1;
  -webkit-appearance: none;
  height: 6px;
  border-radius: 3px;
  background: rgba(255,255,255,0.1);
  outline: none;
}
.control-slider::-webkit-slider-thumb {
  -webkit-appearance: none;
  appearance: none;
  width: 14px;
  height: 14px;
  border-radius: 50%;
  background: #00ff88;
  cursor: pointer;
}

.btn {
  padding: 6px 14px;
  border: none;
  border-radius: 6px;
  cursor: pointer;
  font-size: 12px;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.5px;
  transition: all 0.2s;
}
.btn-primary {
  background: #00ff88;
  color: #000;
  width: 100%;
}
.btn-primary:hover {
  background: #00dd77;
}
.btn-small {
  padding: 5px 10px;
  font-size: 11px;
}

.panel-placeholder {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 8px;
  color: #666;
  padding: 20px;
}
.placeholder-icon {
  font-size: 1.5rem;
  opacity: 0.5;
}
.placeholder-text {
  font-size: 0.8rem;
}
</style>
