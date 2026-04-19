<template>
  <div ref="wrapperRef" class="canvas-wrapper">
    <canvas
      ref="canvasRef"
      class="node-canvas"
      @mousedown="onMouseDown"
      @mousemove="onMouseMove"
      @mouseup="onMouseUp"
      @wheel.prevent="onWheel"
      @contextmenu.prevent
      tabindex="0"
      @keydown="onKeyDown"
    />
    <div
      v-if="editingField"
      class="field-overlay"
      :style="{
        left: editingField.screenX + 'px',
        top: editingField.screenY + 'px',
        width: editingField.width + 'px',
        height: editingField.height + 'px',
      }"
    >
      <input
        v-if="editingField.type === 'text'"
        v-model="editingField.value"
        class="overlay-input"
        @blur="commitEditing"
        @keydown.enter="commitEditing"
      />
      <select
        v-else-if="editingField.type === 'device_select'"
        v-model="editingField.value"
        class="overlay-select"
        @blur="commitEditing"
        @change="commitEditing"
      >
        <option value="">— Select device —</option>
        <option v-for="dev in devices" :key="dev.ieee" :value="dev.ieee">
          {{ dev.name || dev.ieee }}
        </option>
      </select>
      <input
        v-else-if="editingField.type === 'number'"
        v-model.number="editingField.value"
        type="number"
        class="overlay-input"
        @blur="commitEditing"
        @keydown.enter="commitEditing"
      />
      <input
        v-else-if="editingField.type === 'checkbox'"
        v-model="editingField.value"
        type="checkbox"
        class="overlay-checkbox"
        @change="commitEditing"
      />
      <input
        v-else-if="editingField.type === 'color'"
        v-model="editingField.value"
        type="color"
        class="overlay-color"
        @blur="commitEditing"
        @change="commitEditing"
      />
      <select
        v-else-if="editingField.type === 'select'"
        v-model="editingField.value"
        class="overlay-select"
        @blur="commitEditing"
        @change="commitEditing"
      >
        <option v-for="opt in editingField.options" :key="opt.value" :value="opt.value">
          {{ opt.label }}
        </option>
      </select>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, onUnmounted, watch } from 'vue'

interface NodeTypeMeta {
  type: string
  category: string
  label: string
  inputs: { name: string; label: string; type: string }[]
  outputs: { name: string; label: string; type: string }[]
}

interface CanvasNode {
  id: string
  type: string
  pos: { x: number; y: number }
  data: Record<string, any>
}

interface CanvasConnection {
  id: string
  from: { node: string; output: string }
  to: { node: string; input: string }
}

interface Camera {
  x: number
  y: number
  zoom: number
}

interface DeviceInfo {
  ieee: string
  name?: string
}

const props = defineProps<{
  nodes: CanvasNode[]
  connections: CanvasConnection[]
  registry: Record<string, NodeTypeMeta[]>
  selectedNodeId?: string
  devices?: DeviceInfo[]
}>()

const emit = defineEmits<{
  (e: 'updateNodes', nodes: CanvasNode[]): void
  (e: 'updateConnections', connections: CanvasConnection[]): void
  (e: 'selectNode', id: string | null): void
  (e: 'addNode', type: string, pos: { x: number; y: number }): void
  (e: 'updateNodeData', nodeId: string, data: Record<string, any>): void
}>()

const wrapperRef = ref<HTMLDivElement | null>(null)
const canvasRef = ref<HTMLCanvasElement | null>(null)
const ctxRef = ref<CanvasRenderingContext2D | null>(null)

const camera = ref<Camera>({ x: 0, y: 0, zoom: 1 })

const editingField = ref<{
  nodeId: string
  fieldName: string
  type: string
  value: any
  options?: { value: string; label: string }[]
  screenX: number
  screenY: number
  width: number
  height: number
} | null>(null)

// Mouse interaction state
const mouseState = ref<{
  mode: 'idle' | 'dragNode' | 'panCamera' | 'dragConnection'
  startX: number
  startY: number
  lastX: number
  lastY: number
  dragNodeId: string | null
  dragNodeStart: { x: number; y: number } | null
  connectFrom: { nodeId: string; output: string } | null
  connectToPort: { nodeId: string; input: string } | null
}>({
  mode: 'idle',
  startX: 0,
  startY: 0,
  lastX: 0,
  lastY: 0,
  dragNodeId: null,
  dragNodeStart: null,
  connectFrom: null,
  connectToPort: null,
})

// Node dimensions
const NODE_WIDTH = 180
const HEADER_HEIGHT = 28
const PORT_HEIGHT = 24
const PORT_RADIUS = 6
const NODE_PADDING = 8
const CONFIG_FIELD_HEIGHT = 22
const CONFIG_FIELD_PADDING = 6

function getNodeMeta(type: string): NodeTypeMeta | undefined {
  for (const cat of Object.values(props.registry)) {
    const found = cat.find((n) => n.type === type)
    if (found) return found
  }
}

function getNodeHeight(node: CanvasNode): number {
  const meta = getNodeMeta(node.type)
  const inputCount = meta?.inputs?.length || 0
  const outputCount = meta?.outputs?.length || 0
  const bodyHeight = Math.max(inputCount, outputCount) * PORT_HEIGHT + NODE_PADDING * 2
  const configCount = meta?.config_fields?.length || 0
  const configHeight = configCount > 0 ? configCount * CONFIG_FIELD_HEIGHT + NODE_PADDING : 0
  return HEADER_HEIGHT + bodyHeight + configHeight
}

function getCategoryColor(category: string): string {
  const map: Record<string, string> = {
    primitive: '#ffaa00',
    device: '#00ff88',
    color: '#ff55ff',
    panel: '#00ccff',
    math: '#ff5555',
    logic: '#ffff55',
    trigger: '#aa88ff',
  }
  return map[category] || '#666'
}

function getPortColor(type: string): string {
  const map: Record<string, string> = {
    bool: '#ff5555',
    int: '#55aaff',
    float: '#55aaff',
    string: '#ffaa55',
    device: '#00ff88',
    color: '#ff55ff',
    trigger: '#ffff55',
    any: '#888',
  }
  return map[type] || '#888'
}

// Coordinate transforms
function screenToWorld(sx: number, sy: number): { x: number; y: number } {
  return {
    x: sx / camera.value.zoom - camera.value.x,
    y: sy / camera.value.zoom - camera.value.y,
  }
}

function worldToScreen(wx: number, wy: number): { x: number; y: number } {
  return {
    x: (wx + camera.value.x) * camera.value.zoom,
    y: (wy + camera.value.y) * camera.value.zoom,
  }
}

// Port position helpers
function getInputPortPos(node: CanvasNode, portIndex: number): { x: number; y: number } {
  return {
    x: node.pos.x,
    y: node.pos.y + HEADER_HEIGHT + NODE_PADDING + portIndex * PORT_HEIGHT + PORT_HEIGHT / 2,
  }
}

function getOutputPortPos(node: CanvasNode, portIndex: number): { x: number; y: number } {
  return {
    x: node.pos.x + NODE_WIDTH,
    y: node.pos.y + HEADER_HEIGHT + NODE_PADDING + portIndex * PORT_HEIGHT + PORT_HEIGHT / 2,
  }
}

// Hit testing
function hitTestPort(
  worldX: number,
  worldY: number,
): { nodeId: string; portName: string; isInput: boolean } | null {
  for (const node of props.nodes) {
    const meta = getNodeMeta(node.type)
    if (!meta) continue
    const h = getNodeHeight(node)
    // Quick bounds reject
    if (worldX < node.pos.x - PORT_RADIUS || worldX > node.pos.x + NODE_WIDTH + PORT_RADIUS) continue
    if (worldY < node.pos.y || worldY > node.pos.y + h) continue

    // Check inputs
    for (let i = 0; i < meta.inputs.length; i++) {
      const p = getInputPortPos(node, i)
      const dx = worldX - p.x
      const dy = worldY - p.y
      if (dx * dx + dy * dy <= PORT_RADIUS * PORT_RADIUS * 2) {
        return { nodeId: node.id, portName: meta.inputs[i].name, isInput: true }
      }
    }
    // Check outputs
    for (let i = 0; i < meta.outputs.length; i++) {
      const p = getOutputPortPos(node, i)
      const dx = worldX - p.x
      const dy = worldY - p.y
      if (dx * dx + dy * dy <= PORT_RADIUS * PORT_RADIUS * 2) {
        return { nodeId: node.id, portName: meta.outputs[i].name, isInput: false }
      }
    }
  }
  return null
}

function hitTestNode(worldX: number, worldY: number): CanvasNode | null {
  // Iterate in reverse (top-most first)
  for (let i = props.nodes.length - 1; i >= 0; i--) {
    const node = props.nodes[i]
    const h = getNodeHeight(node)
    if (
      worldX >= node.pos.x &&
      worldX <= node.pos.x + NODE_WIDTH &&
      worldY >= node.pos.y &&
      worldY <= node.pos.y + h
    ) {
      return node
    }
  }
  return null
}

function hitTestConfigField(
  worldX: number,
  worldY: number,
  node: CanvasNode,
): { fieldName: string; fieldType: string; fieldMeta: any } | null {
  const meta = getNodeMeta(node.type)
  if (!meta || !meta.config_fields?.length) return null
  const inputCount = meta.inputs?.length || 0
  const outputCount = meta.outputs?.length || 0
  const bodyHeight = Math.max(inputCount, outputCount) * PORT_HEIGHT + NODE_PADDING * 2
  const configStartY = node.pos.y + HEADER_HEIGHT + bodyHeight + NODE_PADDING / 2

  for (let i = 0; i < meta.config_fields.length; i++) {
    const fy = configStartY + i * CONFIG_FIELD_HEIGHT
    if (
      worldX >= node.pos.x + CONFIG_FIELD_PADDING &&
      worldX <= node.pos.x + NODE_WIDTH - CONFIG_FIELD_PADDING &&
      worldY >= fy &&
      worldY <= fy + CONFIG_FIELD_HEIGHT
    ) {
      return {
        fieldName: meta.config_fields[i].name,
        fieldType: meta.config_fields[i].type,
        fieldMeta: meta.config_fields[i],
      }
    }
  }
  return null
}

// Rendering
function render() {
  const canvas = canvasRef.value
  const ctx = ctxRef.value
  if (!canvas || !ctx) return

  const w = canvas.width
  const h = canvas.height

  ctx.clearRect(0, 0, w, h)

  // Background
  ctx.fillStyle = '#161616'
  ctx.fillRect(0, 0, w, h)

  // Grid
  drawGrid(ctx, w, h)

  ctx.save()
  ctx.scale(camera.value.zoom, camera.value.zoom)
  ctx.translate(camera.value.x, camera.value.y)

  // Connections
  drawConnections(ctx)

  // Active connection line
  if (mouseState.value.connectFrom && mouseState.value.mode === 'dragConnection') {
    const fromNode = props.nodes.find((n) => n.id === mouseState.value.connectFrom!.nodeId)
    if (fromNode) {
      const meta = getNodeMeta(fromNode.type)
      const outIdx = meta?.outputs.findIndex((p) => p.name === mouseState.value.connectFrom!.output) ?? -1
      if (outIdx >= 0) {
        const fromPos = getOutputPortPos(fromNode, outIdx)
        const mouseWorld = screenToWorld(mouseState.value.lastX, mouseState.value.lastY)
        drawBezier(ctx, fromPos.x, fromPos.y, mouseWorld.x, mouseWorld.y, '#888')
      }
    }
  }

  // Nodes
  drawNodes(ctx)

  ctx.restore()
}

function drawGrid(ctx: CanvasRenderingContext2D, w: number, h: number) {
  const spacing = 20 * camera.value.zoom
  const offsetX = (camera.value.x * camera.value.zoom) % spacing
  const offsetY = (camera.value.y * camera.value.zoom) % spacing

  ctx.fillStyle = 'rgba(255,255,255,0.03)'
  for (let x = offsetX; x < w; x += spacing) {
    for (let y = offsetY; y < h; y += spacing) {
      ctx.beginPath()
      ctx.arc(x, y, 1, 0, Math.PI * 2)
      ctx.fill()
    }
  }
}

function drawBezier(
  ctx: CanvasRenderingContext2D,
  x1: number,
  y1: number,
  x2: number,
  y2: number,
  color: string,
  width = 2,
) {
  const cp1x = x1 + Math.abs(x2 - x1) * 0.5
  const cp1y = y1
  const cp2x = x2 - Math.abs(x2 - x1) * 0.5
  const cp2y = y2

  ctx.beginPath()
  ctx.moveTo(x1, y1)
  ctx.bezierCurveTo(cp1x, cp1y, cp2x, cp2y, x2, y2)
  ctx.strokeStyle = color
  ctx.lineWidth = width
  ctx.stroke()
}

function drawConnections(ctx: CanvasRenderingContext2D) {
  for (const conn of props.connections) {
    const fromNode = props.nodes.find((n) => n.id === conn.from.node)
    const toNode = props.nodes.find((n) => n.id === conn.to.node)
    if (!fromNode || !toNode) continue

    const fromMeta = getNodeMeta(fromNode.type)
    const toMeta = getNodeMeta(toNode.type)
    if (!fromMeta || !toMeta) continue

    const outIdx = fromMeta.outputs.findIndex((p) => p.name === conn.from.output)
    const inIdx = toMeta.inputs.findIndex((p) => p.name === conn.to.input)
    if (outIdx < 0 || inIdx < 0) continue

    const fromPos = getOutputPortPos(fromNode, outIdx)
    const toPos = getInputPortPos(toNode, inIdx)

    const portType = fromMeta.outputs[outIdx].type
    const color = getPortColor(portType)
    drawBezier(ctx, fromPos.x, fromPos.y, toPos.x, toPos.y, color)
  }
}

function drawNodes(ctx: CanvasRenderingContext2D) {
  for (const node of props.nodes) {
    const meta = getNodeMeta(node.type)
    if (!meta) continue

    const h = getNodeHeight(node)
    const isSelected = node.id === props.selectedNodeId

    // Shadow
    ctx.shadowColor = isSelected ? 'rgba(255,255,255,0.15)' : 'rgba(0,0,0,0.3)'
    ctx.shadowBlur = isSelected ? 12 : 6
    ctx.shadowOffsetX = 0
    ctx.shadowOffsetY = 2

    // Body
    ctx.fillStyle = '#222'
    ctx.beginPath()
    roundRect(ctx, node.pos.x, node.pos.y, NODE_WIDTH, h, 6)
    ctx.fill()

    ctx.shadowColor = 'transparent'
    ctx.shadowBlur = 0

    // Border
    ctx.strokeStyle = isSelected ? 'rgba(255,255,255,0.3)' : 'rgba(255,255,255,0.08)'
    ctx.lineWidth = isSelected ? 2 : 1
    ctx.beginPath()
    roundRect(ctx, node.pos.x, node.pos.y, NODE_WIDTH, h, 6)
    ctx.stroke()

    // Header
    const catColor = getCategoryColor(meta.category)
    ctx.fillStyle = catColor + '20' // 12% opacity
    ctx.beginPath()
    roundRect(ctx, node.pos.x + 1, node.pos.y + 1, NODE_WIDTH - 2, HEADER_HEIGHT - 1, [6, 6, 0, 0])
    ctx.fill()

    // Header line
    ctx.strokeStyle = catColor
    ctx.lineWidth = 1
    ctx.beginPath()
    ctx.moveTo(node.pos.x, node.pos.y + HEADER_HEIGHT)
    ctx.lineTo(node.pos.x + NODE_WIDTH, node.pos.y + HEADER_HEIGHT)
    ctx.stroke()

    // Title
    ctx.fillStyle = '#eee'
    ctx.font = '600 12px sans-serif'
    ctx.textAlign = 'left'
    ctx.textBaseline = 'middle'
    ctx.fillText(meta.label, node.pos.x + 10, node.pos.y + HEADER_HEIGHT / 2)

    // Inputs
    for (let i = 0; i < meta.inputs.length; i++) {
      const p = getInputPortPos(node, i)
      const port = meta.inputs[i]
      const color = getPortColor(port.type)
      drawPort(ctx, p.x, p.y, color)
      ctx.fillStyle = '#aaa'
      ctx.font = '11px sans-serif'
      ctx.textAlign = 'left'
      ctx.fillText(port.label, p.x + 10, p.y)
    }

    // Outputs
    for (let i = 0; i < meta.outputs.length; i++) {
      const p = getOutputPortPos(node, i)
      const port = meta.outputs[i]
      const color = getPortColor(port.type)
      drawPort(ctx, p.x, p.y, color)
      ctx.fillStyle = '#aaa'
      ctx.font = '11px sans-serif'
      ctx.textAlign = 'right'
      ctx.fillText(port.label, p.x - 10, p.y)
    }

    // Config fields (inline properties)
    if (meta.config_fields?.length) {
      const inputCount = meta.inputs?.length || 0
      const outputCount = meta.outputs?.length || 0
      const bodyHeight = Math.max(inputCount, outputCount) * PORT_HEIGHT + NODE_PADDING * 2
      const configStartY = node.pos.y + HEADER_HEIGHT + bodyHeight + NODE_PADDING / 2

      for (let i = 0; i < meta.config_fields.length; i++) {
        const field = meta.config_fields[i]
        const fy = configStartY + i * CONFIG_FIELD_HEIGHT
        const fx = node.pos.x + CONFIG_FIELD_PADDING
        const fw = NODE_WIDTH - CONFIG_FIELD_PADDING * 2

        // Background
        ctx.fillStyle = 'rgba(255,255,255,0.03)'
        ctx.fillRect(fx, fy, fw, CONFIG_FIELD_HEIGHT)

        // Label
        ctx.fillStyle = '#aaa'
        ctx.font = '10px sans-serif'
        ctx.textAlign = 'left'
        ctx.textBaseline = 'middle'
        ctx.fillText(field.label, fx + 4, fy + CONFIG_FIELD_HEIGHT / 2)

        // Value
        let value = node.data?.[field.name]
        if (value === undefined || value === null) value = field.default

        if (field.type === 'checkbox') {
          const cbSize = 10
          const cbX = node.pos.x + NODE_WIDTH - CONFIG_FIELD_PADDING - cbSize - 4
          const cbY = fy + (CONFIG_FIELD_HEIGHT - cbSize) / 2
          ctx.strokeStyle = '#888'
          ctx.lineWidth = 1
          ctx.strokeRect(cbX, cbY, cbSize, cbSize)
          if (value) {
            ctx.fillStyle = '#00ff88'
            ctx.fillRect(cbX + 2, cbY + 2, cbSize - 4, cbSize - 4)
          }
        } else {
          ctx.fillStyle = '#ddd'
          ctx.font = '10px sans-serif'
          ctx.textAlign = 'right'
          let text = String(value ?? '')
          if (field.type === 'device_select' && props.devices) {
            const dev = props.devices.find((d) => d.ieee === text)
            if (dev?.name) text = dev.name
          }
          // Truncate if too long
          const maxTextWidth = fw - 60
          if (ctx.measureText(text).width > maxTextWidth) {
            text = text.substring(0, 12) + '…'
          }
          ctx.fillText(text, node.pos.x + NODE_WIDTH - CONFIG_FIELD_PADDING - 4, fy + CONFIG_FIELD_HEIGHT / 2)
        }
      }
    }
  }
}

function drawPort(ctx: CanvasRenderingContext2D, x: number, y: number, color: string) {
  ctx.beginPath()
  ctx.arc(x, y, PORT_RADIUS, 0, Math.PI * 2)
  ctx.fillStyle = '#1a1a1a'
  ctx.fill()
  ctx.strokeStyle = color
  ctx.lineWidth = 2
  ctx.stroke()
}

function roundRect(
  ctx: CanvasRenderingContext2D,
  x: number,
  y: number,
  w: number,
  h: number,
  r: number | number[],
) {
  const radii = Array.isArray(r) ? r : [r, r, r, r]
  ctx.moveTo(x + radii[0], y)
  ctx.lineTo(x + w - radii[1], y)
  ctx.quadraticCurveTo(x + w, y, x + w, y + radii[1])
  ctx.lineTo(x + w, y + h - radii[2])
  ctx.quadraticCurveTo(x + w, y + h, x + w - radii[2], y + h)
  ctx.lineTo(x + radii[3], y + h)
  ctx.quadraticCurveTo(x, y + h, x, y + h - radii[3])
  ctx.lineTo(x, y + radii[0])
  ctx.quadraticCurveTo(x, y, x + radii[0], y)
  ctx.closePath()
}

// Mouse handlers
function getMousePos(e: MouseEvent): { x: number; y: number } {
  const canvas = canvasRef.value!
  const rect = canvas.getBoundingClientRect()
  return {
    x: e.clientX - rect.left,
    y: e.clientY - rect.top,
  }
}

function onMouseDown(e: MouseEvent) {
  canvasRef.value?.focus()
  const m = getMousePos(e)
  const world = screenToWorld(m.x, m.y)
  const state = mouseState.value

  state.startX = m.x
  state.startY = m.y
  state.lastX = m.x
  state.lastY = m.y

  // Check ports first
  const portHit = hitTestPort(world.x, world.y)
  if (portHit) {
    if (!portHit.isInput) {
      state.mode = 'dragConnection'
      state.connectFrom = { nodeId: portHit.nodeId, output: portHit.portName }
      _attachGlobalListeners()
      render()
      return
    }
  }

  // Check node body (and inline config fields)
  const nodeHit = hitTestNode(world.x, world.y)
  if (nodeHit) {
    const fieldHit = hitTestConfigField(world.x, world.y, nodeHit)
    if (fieldHit) {
      const meta = getNodeMeta(nodeHit.type)
      const fieldDef = meta?.config_fields?.find((f: any) => f.name === fieldHit.fieldName)
      const inputCount = meta?.inputs?.length || 0
      const outputCount = meta?.outputs?.length || 0
      const bodyHeight = Math.max(inputCount, outputCount) * PORT_HEIGHT + NODE_PADDING * 2
      const fieldIndex = meta?.config_fields?.findIndex((f: any) => f.name === fieldHit.fieldName) ?? 0
      const fieldY = nodeHit.pos.y + HEADER_HEIGHT + bodyHeight + NODE_PADDING / 2 + fieldIndex * CONFIG_FIELD_HEIGHT

      const screenPos = worldToScreen(nodeHit.pos.x + CONFIG_FIELD_PADDING, fieldY)
      const screenW = (NODE_WIDTH - CONFIG_FIELD_PADDING * 2) * camera.value.zoom
      const screenH = CONFIG_FIELD_HEIGHT * camera.value.zoom

      let value = nodeHit.data?.[fieldHit.fieldName]
      if (value === undefined || value === null) value = fieldDef?.default

      editingField.value = {
        nodeId: nodeHit.id,
        fieldName: fieldHit.fieldName,
        type: fieldHit.fieldType,
        value,
        options: fieldDef?.options,
        screenX: screenPos.x,
        screenY: screenPos.y,
        width: Math.max(screenW, 60),
        height: Math.max(screenH, 20),
      }

      emit('selectNode', nodeHit.id)
      render()
      return
    }

    state.mode = 'dragNode'
    state.dragNodeId = nodeHit.id
    state.dragNodeStart = { ...nodeHit.pos }
    emit('selectNode', nodeHit.id)
    _attachGlobalListeners()
    render()
    return
  }

  // Empty space — pan camera
  state.mode = 'panCamera'
  _attachGlobalListeners()
}

function onMouseMove(e: MouseEvent) {
  if (editingField.value) return
  const m = getMousePos(e)
  const state = mouseState.value

  if (state.mode === 'dragNode' && state.dragNodeId) {
    const node = props.nodes.find((n) => n.id === state.dragNodeId)
    if (node && state.dragNodeStart) {
      const dx = (m.x - state.startX) / camera.value.zoom
      const dy = (m.y - state.startY) / camera.value.zoom
      const newNodes = props.nodes.map((n) =>
        n.id === state.dragNodeId
          ? { ...n, pos: { x: state.dragNodeStart!.x + dx, y: state.dragNodeStart!.y + dy } }
          : n,
      )
      emit('updateNodes', newNodes)
    }
  } else if (state.mode === 'panCamera') {
    camera.value.x += (m.x - state.lastX) / camera.value.zoom
    camera.value.y += (m.y - state.lastY) / camera.value.zoom
    render()
  } else if (state.mode === 'dragConnection') {
    // Highlight target port if hovering
    const world = screenToWorld(m.x, m.y)
    const portHit = hitTestPort(world.x, world.y)
    if (portHit && portHit.isInput) {
      state.connectToPort = { nodeId: portHit.nodeId, input: portHit.portName }
    } else {
      state.connectToPort = null
    }
    render()
  }

  state.lastX = m.x
  state.lastY = m.y
}

function onMouseUp(e: MouseEvent) {
  if (editingField.value) return
  const state = mouseState.value
  if (state.mode === 'idle') return

  const m = getMousePos(e)

  if (state.mode === 'dragConnection' && state.connectFrom && state.connectToPort) {
    // Create connection
    const fromNodeId = state.connectFrom.nodeId
    const fromOutput = state.connectFrom.output
    const toNodeId = state.connectToPort.nodeId
    const toInput = state.connectToPort.input

    // Prevent self-connection
    if (fromNodeId !== toNodeId) {
      // Check if input already connected
      const existing = props.connections.find(
        (c) => c.to.node === toNodeId && c.to.input === toInput,
      )
      const newConnections = existing
        ? props.connections.filter((c) => !(c.to.node === toNodeId && c.to.input === toInput))
        : [...props.connections]

      newConnections.push({
        id: `c_${Date.now()}_${Math.floor(Math.random() * 1000)}`,
        from: { node: fromNodeId, output: fromOutput },
        to: { node: toNodeId, input: toInput },
      })
      emit('updateConnections', newConnections)
    }
  } else if (state.mode === 'dragNode') {
    // Snap to grid or just finalize
    const node = props.nodes.find((n) => n.id === state.dragNodeId)
    if (node) {
      const snapped = {
        ...node,
        pos: { x: Math.round(node.pos.x / 10) * 10, y: Math.round(node.pos.y / 10) * 10 },
      }
      const newNodes = props.nodes.map((n) => (n.id === state.dragNodeId ? snapped : n))
      emit('updateNodes', newNodes)
    }
  } else if (state.mode === 'idle') {
    // Click on empty space — deselect
    const world = screenToWorld(m.x, m.y)
    if (!hitTestNode(world.x, world.y)) {
      emit('selectNode', null)
      render()
    }
  }

  state.mode = 'idle'
  state.dragNodeId = null
  state.dragNodeStart = null
  state.connectFrom = null
  state.connectToPort = null
  render()
}

function onWindowMouseMove(e: MouseEvent) {
  onMouseMove(e)
}

function onWindowMouseUp(e: MouseEvent) {
  window.removeEventListener('mousemove', onWindowMouseMove)
  window.removeEventListener('mouseup', onWindowMouseUp)
  onMouseUp(e)
}

function _attachGlobalListeners() {
  window.addEventListener('mousemove', onWindowMouseMove)
  window.addEventListener('mouseup', onWindowMouseUp)
}

function commitEditing() {
  if (!editingField.value) return
  const { nodeId, fieldName, value } = editingField.value
  emit('updateNodeData', nodeId, { [fieldName]: value })
  editingField.value = null
  render()
}

function onWheel(e: WheelEvent) {
  const canvas = canvasRef.value!
  const rect = canvas.getBoundingClientRect()
  const mx = e.clientX - rect.left
  const my = e.clientY - rect.top

  const worldBefore = screenToWorld(mx, my)
  const zoomFactor = e.deltaY > 0 ? 0.9 : 1.1
  const newZoom = Math.max(0.2, Math.min(3, camera.value.zoom * zoomFactor))
  camera.value.zoom = newZoom
  const worldAfter = screenToWorld(mx, my)

  camera.value.x += worldAfter.x - worldBefore.x
  camera.value.y += worldAfter.y - worldBefore.y

  render()
}

function onKeyDown(e: KeyboardEvent) {
  if (e.key === 'Delete' || e.key === 'Backspace') {
    if (props.selectedNodeId) {
      const newNodes = props.nodes.filter((n) => n.id !== props.selectedNodeId)
      const newConnections = props.connections.filter(
        (c) => c.from.node !== props.selectedNodeId && c.to.node !== props.selectedNodeId,
      )
      emit('updateNodes', newNodes)
      emit('updateConnections', newConnections)
      emit('selectNode', null)
      render()
    }
  }
}

// Resize handling
function resize() {
  const canvas = canvasRef.value
  if (!canvas) return
  const parent = canvas.parentElement!
  canvas.width = parent.clientWidth
  canvas.height = parent.clientHeight
  render()
}

onMounted(() => {
  const canvas = canvasRef.value!
  ctxRef.value = canvas.getContext('2d')!
  resize()
  window.addEventListener('resize', resize)
  render()
})

onUnmounted(() => {
  window.removeEventListener('resize', resize)
})

watch(() => [props.nodes, props.connections, props.selectedNodeId], render, { deep: true })
</script>

<style scoped>
.canvas-wrapper {
  position: relative;
  width: 100%;
  height: 100%;
  overflow: hidden;
}
.node-canvas {
  display: block;
  width: 100%;
  height: 100%;
  outline: none;
  cursor: default;
}
.node-canvas:active {
  cursor: grabbing;
}

.field-overlay {
  position: absolute;
  z-index: 10;
  display: flex;
  align-items: center;
}

.overlay-input,
.overlay-select {
  width: 100%;
  height: 100%;
  background: #2a2a2a;
  border: 1px solid #00ff88;
  border-radius: 4px;
  color: #fff;
  font-size: 11px;
  padding: 0 4px;
  outline: none;
  box-sizing: border-box;
}

.overlay-checkbox {
  width: 16px;
  height: 16px;
  accent-color: #00ff88;
  cursor: pointer;
}

.overlay-color {
  width: 100%;
  height: 100%;
  border: none;
  padding: 0;
  cursor: pointer;
  background: transparent;
}
</style>
