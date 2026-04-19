<template>
  <div class="node-editor-overlay" @click.self="$emit('close')">
    <div class="node-editor">
      <div class="editor-header">
        <h3>Edit Graph: {{ panelName }}</h3>
        <div class="editor-actions">
          <button class="btn btn-secondary btn-small" @click="validate">Validate</button>
          <button class="btn btn-primary btn-small" @click="save">Save</button>
          <button class="btn-icon" @click="$emit('close')">×</button>
        </div>
      </div>
      <div class="editor-body">
        <NodePalette :registry="registry" @add="addNode" />
        <div class="editor-canvas-wrapper">
          <NodeCanvas
            :nodes="nodes"
            :connections="connections"
            :registry="registry"
            :selected-node-id="selectedNodeId"
            @update-nodes="onUpdateNodes"
            @update-connections="onUpdateConnections"
            @select-node="selectedNodeId = $event"
          />
        </div>
        <NodeProperties
          v-if="selectedNode"
          :node="selectedNode"
          :registry="registry"
          @update="onUpdateNodeData"
        />
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, computed } from 'vue'
import NodePalette from './NodePalette.vue'
import NodeCanvas from './NodeCanvas.vue'
import NodeProperties from './NodeProperties.vue'
import * as api from '../api'

interface GraphNode {
  id: string
  type: string
  pos: { x: number; y: number }
  data: Record<string, any>
}

interface GraphConnection {
  id: string
  from: { node: string; output: string }
  to: { node: string; input: string }
}

const props = defineProps<{
  panelId: number
  panelName: string
}>()

const emit = defineEmits<{
  (e: 'close'): void
  (e: 'saved'): void
}>()

const registry = ref<Record<string, any[]>>({})
const nodes = ref<GraphNode[]>([])
const connections = ref<GraphConnection[]>([])
const selectedNodeId = ref<string | null>(null)

const selectedNode = computed(() => {
  if (!selectedNodeId.value) return null
  return nodes.value.find((n) => n.id === selectedNodeId.value) || null
})

onMounted(async () => {
  try {
    const [reg, gr] = await Promise.all([
      api.getNodeRegistry(),
      api.getGraph(props.panelId),
    ])
    registry.value = reg
    nodes.value = gr.nodes || []
    connections.value = gr.connections || []
  } catch (e: any) {
    console.error('Failed to load editor data:', e)
  }
})

function addNode(type: string) {
  const id = `n_${Date.now()}_${Math.floor(Math.random() * 1000)}`
  const canvasCenter = { x: 400, y: 300 }
  nodes.value.push({
    id,
    type,
    pos: {
      x: canvasCenter.x + (Math.random() - 0.5) * 100,
      y: canvasCenter.y + (Math.random() - 0.5) * 100,
    },
    data: {},
  })
}

function onUpdateNodes(newNodes: GraphNode[]) {
  nodes.value = newNodes
}

function onUpdateConnections(newConnections: GraphConnection[]) {
  connections.value = newConnections
}

function onUpdateNodeData(nodeId: string, data: Record<string, any>) {
  const idx = nodes.value.findIndex((n) => n.id === nodeId)
  if (idx >= 0) {
    nodes.value[idx] = { ...nodes.value[idx], data: { ...nodes.value[idx].data, ...data } }
  }
}

async function save() {
  try {
    await api.saveGraph(props.panelId, {
      nodes: nodes.value,
      connections: connections.value,
    })
    emit('saved')
    emit('close')
  } catch (e: any) {
    alert('Save failed: ' + e.message)
  }
}

async function validate() {
  try {
    const result = await api.validateGraph(props.panelId, {
      nodes: nodes.value,
      connections: connections.value,
    })
    if (result.valid) {
      alert('Graph is valid!')
    } else {
      alert('Errors:\n' + result.errors.join('\n'))
    }
  } catch (e: any) {
    alert('Validation failed: ' + e.message)
  }
}
</script>

<style scoped>
.node-editor-overlay {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.7);
  backdrop-filter: blur(4px);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 1000;
}

.node-editor {
  width: 92vw;
  height: 88vh;
  background: #1e1e1e;
  border-radius: 12px;
  border: 1px solid rgba(255, 255, 255, 0.08);
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.editor-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 12px 16px;
  border-bottom: 1px solid rgba(255, 255, 255, 0.08);
  flex-shrink: 0;
}
.editor-header h3 {
  font-size: 1rem;
  color: #fff;
  margin: 0;
}

.editor-actions {
  display: flex;
  gap: 8px;
  align-items: center;
}

.editor-body {
  flex: 1;
  display: flex;
  overflow: hidden;
}

.editor-canvas-wrapper {
  flex: 1;
  position: relative;
  overflow: hidden;
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
.btn-secondary {
  background: rgba(255, 255, 255, 0.1);
  color: white;
}
.btn-secondary:hover {
  background: rgba(255, 255, 255, 0.15);
}
.btn-primary {
  background: #00ff88;
  color: #000;
}
.btn-primary:hover {
  background: #00dd77;
}
.btn-small {
  padding: 5px 10px;
  font-size: 11px;
}

.btn-icon {
  background: transparent;
  border: none;
  color: #888;
  cursor: pointer;
  font-size: 1.4rem;
  width: 32px;
  height: 32px;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: 6px;
}
.btn-icon:hover {
  background: rgba(255, 255, 255, 0.1);
  color: #fff;
}
</style>
