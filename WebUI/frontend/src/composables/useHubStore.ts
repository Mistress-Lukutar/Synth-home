import { reactive, readonly } from 'vue'
import * as api from '../api'

export interface Endpoint {
  id: number
  clusters: number[]
}

export interface Device {
  ieee: string
  name?: string
  endpoints: Endpoint[]
  state?: Record<string, any>
  online?: boolean
}

export interface Panel {
  id: number
  name: string
  is_enabled: boolean
  sort_order: number
  collapsed: boolean
  layout?: Record<string, any>
  created_at?: string
  updated_at?: string
}

export interface HubEvent {
  time: string
  text: string
}

interface PendingCommand {
  ieee: string
  endpoint?: number
  action: string
}

interface State {
  isConnected: boolean
  currentPort: string | null
  devices: Device[]
  panels: Panel[]
  panelOutputs: Record<number, Record<string, any>>
  events: HubEvent[]
  pendingCommands: Map<string, PendingCommand>
  sseReconnectDelay: number
  evtSource: EventSource | null
  sseReconnectTimer: ReturnType<typeof setTimeout> | null
  refreshingDevices: boolean
  refreshInterval: ReturnType<typeof setInterval> | null
}

const state = reactive<State>({
  isConnected: false,
  currentPort: null,
  devices: [],
  panels: [],
  panelOutputs: {},
  events: [],
  pendingCommands: new Map(),
  sseReconnectDelay: 1000,
  evtSource: null,
  sseReconnectTimer: null,
  refreshingDevices: false,
  refreshInterval: null,
})

function addPendingCommand(correlationId: string, cmd: PendingCommand) {
  state.pendingCommands.set(correlationId, cmd)
}

function removePendingCommand(correlationId: string) {
  state.pendingCommands.delete(correlationId)
}

function clearPendingCommands() {
  state.pendingCommands.clear()
}

function logEvent(text: string) {
  const t = new Date().toLocaleTimeString()
  state.events.push({ time: t, text })
  if (state.events.length > 200) state.events.shift()
}

function handleSSEMessage(msg: any) {
  if (msg.type === 'connected') {
    logEvent('Hub connected event')
  } else if (msg.type === 'disconnected') {
    logEvent('Hub disconnected event')
  } else if (msg.type === 'hub_serial') {
    const direction = msg.direction === 'tx' ? '→ TX' : '← RX'
    const payload = msg.payload || {}
    const pretty = JSON.stringify(payload, null, 2).substring(0, 600)
    logEvent(`${direction}\n${pretty}`)
  } else if (msg.type === 'hub_message') {
    const data = msg.data || {}
    const evt = data.evt || data.event || 'message'
    if (evt !== 'device_list') {
      logEvent(`Hub: ${evt}`)
    }
    if (['device_joined', 'device_left'].includes(evt)) {
      refreshDevices()
    }
    if (evt === 'state_change') {
      handleStateChange(data)
    }
    if (evt && evt.endsWith('_ack')) {
      handleAck(data)
    }
    if (evt === 'command_status') {
      handleCommandStatus(data)
    }
    if (evt === 'ping_result') {
      handlePingResult(data)
    }
  } else if (msg.type === 'panel_output') {
    const { panel_id, node_id, value } = msg
    if (!state.panelOutputs[panel_id]) {
      state.panelOutputs[panel_id] = {}
    }
    state.panelOutputs[panel_id][node_id] = value
  }
}

function handleAck(data: any) {
  const correlationId = data.correlation_id
  const ok = data.ok
  const error = data.error
  if (!correlationId) return

  const pending = state.pendingCommands.get(correlationId)
  if (!pending) return

  // An ack only tells us whether the firmware accepted the command. The actual
  // state update arrives via a state_change event. Failed sends are dropped
  // immediately; successful sends stay pending until confirmed.
  if (!ok) {
    logEvent(`Command ${pending.action} failed: ${error || 'unknown'}`)
    removePendingCommand(correlationId)
  } else {
    logEvent(`Command ${pending.action} accepted`)
  }
}

function resolvePendingByStateChange(
  ieee: string,
  endpoint: number | undefined,
  clusterId: number,
  attrId: number,
  value: any,
) {
  const ep = endpoint ?? 1
  for (const [correlationId, pending] of state.pendingCommands) {
    if (pending.ieee !== ieee || pending.endpoint !== ep) continue
    const action = pending.action
    let resolved = false
    if (clusterId === 0x0006 && attrId === 0x0000) {
      if (action === 'on' && value === true) resolved = true
      else if (action === 'off' && value === false) resolved = true
      else if (action === 'toggle') resolved = true
    } else if (clusterId === 0x0008 && attrId === 0x0000 && action === 'level') {
      resolved = true
    } else if (clusterId === 0x0300 && (action === 'color' || action === 'color_ct')) {
      resolved = true
    }
    if (resolved) {
      removePendingCommand(correlationId)
    }
  }
}

function handleStateChange(data: any) {
  const ieee = data.ieee_addr
  if (!ieee) return
  const device = state.devices.find(d => d.ieee === ieee)
  if (!device) return
  if (!device.state) device.state = {}

  // A state_change is a sign of life (mirror of the backend hub_service rule).
  device.online = true

  const changes = data.changes || []
  if (changes.length > 0) {
    for (const change of changes) {
      const cluster = change.cluster || ''
      const attr = change.attribute || ''
      const value = change.value
      const endpoint = change.endpoint
      const epKey = String(endpoint ?? '1')
      if (!device.state[epKey]) device.state[epKey] = {}

      const clusterId = parseInt(cluster, 16)
      const attrId = parseInt(attr, 16)

      // Xiaomi private cluster reports are liveness noise.
      if (clusterId === 0xFCC0) {
        continue
      }

      resolvePendingByStateChange(ieee, endpoint, clusterId, attrId, value)

      if (clusterId === 0x0006 && attrId === 0x0000) {
        device.state[epKey].on = Boolean(value)
      } else if (clusterId === 0x0008 && attrId === 0x0000) {
        device.state[epKey].level = Number(value)
      } else if (clusterId === 0x0008 && attrId === 0x0002) {
        device.state[epKey].level_min = Number(value)
      } else if (clusterId === 0x0008 && attrId === 0x0003) {
        device.state[epKey].level_max = Number(value)
      } else if (clusterId === 0x0300 && attrId === 0x0008) {
        const modeVal = Number(value)
        if (modeVal === 0) device.state[epKey].color_mode = 'hs'
        else if (modeVal === 1) device.state[epKey].color_mode = 'xy'
        else if (modeVal === 2) device.state[epKey].color_mode = 'ct'
      } else if (clusterId === 0x0300 && attrId === 0x400A) {
        // ZCL ColorCapabilities bitmap (0x400A). Zero/invalid reads are
        // treated as "unknown" rather than "no capabilities".
        const bitmask = Number(value)
        if (Number.isFinite(bitmask) && bitmask !== 0) {
          device.state[epKey].color_caps = {
            hs: !!(bitmask & 0x01),
            enhanced_hue: !!(bitmask & 0x02),
            color_loop: !!(bitmask & 0x04),
            xy: !!(bitmask & 0x08),
            ct: !!(bitmask & 0x10),
          }
        }
      } else if (clusterId === 0x0300 && attrId === 0x0000) {
        device.state[epKey].hue = Number(value)
      } else if (clusterId === 0x0300 && attrId === 0x0001) {
        device.state[epKey].sat = Number(value)
      } else if (clusterId === 0x0300 && attrId === 0x0003) {
        device.state[epKey].x = Number(value)
      } else if (clusterId === 0x0300 && attrId === 0x0004) {
        device.state[epKey].y = Number(value)
      } else if (clusterId === 0x0300 && attrId === 0x0007) {
        device.state[epKey].ct = Number(value)
      } else if (clusterId === 0x0300 && attrId === 0x400B) {
        device.state[epKey].ct_min = Number(value)
      } else if (clusterId === 0x0300 && attrId === 0x400C) {
        device.state[epKey].ct_max = Number(value)
      }
    }
  } else {
    // Old flat format fallback
    const endpoint = data.endpoint
    const epKey = String(endpoint || '1')
    if (!device.state[epKey]) device.state[epKey] = {}
    const clusterId = data.cluster_id
    const attrId = data.attr_id
    const value = data.value
    if (clusterId !== undefined && attrId !== undefined && value !== undefined) {
      resolvePendingByStateChange(ieee, endpoint, clusterId, attrId, value)
    }
    if (clusterId === 6 && attrId === 0) device.state[epKey].on = Boolean(value)
    else if (clusterId === 8) device.state[epKey].level = Number(value)
    else if (clusterId === 768) device.state[epKey].color = value
  }
}

function handleCommandStatus(data: any) {
  const correlationId = data.correlation_id
  const status = data.status
  const ieee = data.ieee_addr || data.ieee

  // command_status carries delivery/completion status. A delivered command
  // proves liveness; timeouts/failures must NOT flip the device offline —
  // liveness belongs to pings and state_change only (mirrors the backend).
  if (ieee && (status === 'completed' || status === 'delivered')) {
    const device = state.devices.find(d => d.ieee === ieee)
    if (device) device.online = true
  }

  if (!correlationId) return

  const pending = state.pendingCommands.get(correlationId)
  if (!pending) return

  if (status === 'timeout' || status === 'failed') {
    logEvent(`Command ${pending.action} ${status} for ${pending.ieee}`)
  }

  if (status === 'timeout' || status === 'failed' || status === 'completed' || status === 'delivered') {
    removePendingCommand(correlationId)
  }
}

function handlePingResult(data: any) {
  const ieee = data.ieee
  const online = data.online === true
  if (!ieee) return
  const device = state.devices.find(d => d.ieee === ieee)
  if (!device) return
  device.online = online
  if (!online) {
    logEvent(`Ping: ${ieee} is offline`)
  }
}

function startSSE() {
  if (state.evtSource) state.evtSource.close()
  state.evtSource = new EventSource('/events')
  state.evtSource.onopen = () => {
    state.sseReconnectDelay = 1000
  }
  state.evtSource.onmessage = (e) => {
    try {
      const msg = JSON.parse(e.data)
      handleSSEMessage(msg)
    } catch {
      logEvent('SSE raw: ' + e.data)
    }
  }
  state.evtSource.onerror = () => {
    logEvent('SSE error / disconnected')
    state.evtSource?.close()
    state.evtSource = null
    if (!state.sseReconnectTimer && state.isConnected) {
      state.sseReconnectTimer = setTimeout(() => {
        state.sseReconnectTimer = null
        startSSE()
      }, state.sseReconnectDelay)
      state.sseReconnectDelay = Math.min(state.sseReconnectDelay * 2, 30000)
    }
  }
}

function stopSSE() {
  if (state.sseReconnectTimer) {
    clearTimeout(state.sseReconnectTimer)
    state.sseReconnectTimer = null
  }
  if (state.evtSource) {
    state.evtSource.close()
    state.evtSource = null
  }
  if (state.refreshInterval) {
    clearInterval(state.refreshInterval)
    state.refreshInterval = null
  }
  clearPendingCommands()
  state.sseReconnectDelay = 1000
}

async function refreshPorts(): Promise<string[]> {
  try {
    const data = await api.listPorts()
    return data.ports
  } catch (e: any) {
    logEvent('Failed to list ports: ' + e.message)
    return []
  }
}

async function connect(port: string): Promise<boolean> {
  try {
    const data = await api.connectPort(port)
    if (data.success) {
      state.isConnected = true
      state.currentPort = port
      logEvent(`Connected: ${port}`)
      startSSE()
      await loadDevices()      // quick cache from DB
      await refreshDevices()   // sync with hub and poll attributes
      if (!state.refreshInterval) {
        state.refreshInterval = setInterval(async () => {
          await refreshDevices()
        }, 30000)
      }
      return true
    } else {
      logEvent(data.error || 'Connection failed')
      return false
    }
  } catch (e: any) {
    logEvent('Connection error')
    return false
  }
}

async function disconnect() {
  try {
    await api.disconnectPort()
  } catch {}
  state.isConnected = false
  state.currentPort = null
  state.devices = []
  clearPendingCommands()
  stopSSE()
  logEvent('Disconnected')
}

async function loadDevices() {
  try {
    const data = await api.listDevices()
    if (data.success) {
      state.devices = data.devices || []
    }
  } catch (e: any) {
    logEvent('Load devices error: ' + e.message)
  }
}

async function refreshDevices() {
  if (!state.isConnected || state.refreshingDevices) return
  state.refreshingDevices = true
  try {
    const data = await api.refreshDevices()
    if (data.success) {
      state.devices = data.devices || []
    }
  } catch (e: any) {
    logEvent('Refresh devices error: ' + e.message)
  } finally {
    state.refreshingDevices = false
  }
  // Refresh only reloads topology from DB; poll actual attributes so the UI
  // does not keep showing a stale on/off state.
  await pollDevices()
}

async function restoreConnection() {
  try {
    const data = await api.getStatus()
    if (data.connected && data.port) {
      state.isConnected = true
      state.currentPort = data.port
      startSSE()
      await loadDevices()   // quick cache from DB
      // Bring state in sync with the hub (includes attribute poll).
      setTimeout(() => refreshDevices(), 300)
      if (!state.refreshInterval) {
        state.refreshInterval = setInterval(async () => {
          await refreshDevices()
        }, 30000)
      }
    }
  } catch {
    // stay disconnected
  }
}

async function loadPanels() {
  try {
    state.panels = await api.listPanels()
  } catch (e: any) {
    logEvent('Load panels error: ' + e.message)
  }
}

async function reorderPanels(fromIndex: number, toIndex: number) {
  const list = [...state.panels]
  const [moved] = list.splice(fromIndex, 1)
  list.splice(toIndex, 0, moved)
  list.forEach((p, i) => { p.sort_order = i })
  state.panels = list
  try {
    await api.reorderPanels(list.map((p, i) => ({ id: p.id, sort_order: i })))
  } catch (e: any) {
    logEvent('Panels reorder failed: ' + e.message)
    await loadPanels()
  }
}

function _isStaticCached(ep: any, cluster: string, attribute: string): boolean {
  if (cluster === '0x0008') {
    if (attribute === '0x0002') return ep.level_min !== undefined
    if (attribute === '0x0003') return ep.level_max !== undefined
  }
  if (cluster === '0x0300') {
    if (attribute === '0x400A') return ep.color_caps !== undefined
    if (attribute === '0x400B') return ep.ct_min !== undefined
    if (attribute === '0x400C') return ep.ct_max !== undefined
  }
  return false
}

async function pollDevices() {
  if (!state.isConnected) return
  logEvent('Polling device attributes...')
  const items: { ieee: string; endpoint?: number; cluster: string; attribute: string }[] = []
  for (const device of state.devices) {
    if (device.online === false) continue
    const endpoints = device.endpoints || []
    for (const ep of endpoints) {
      const epId = ep.id
      const clusters = ep.clusters || []
      if (clusters.includes(6)) {
        items.push({ ieee: device.ieee, endpoint: epId, cluster: '0x0006', attribute: '0x0000' })
      }
      if (clusters.includes(8)) {
        items.push({ ieee: device.ieee, endpoint: epId, cluster: '0x0008', attribute: '0x0000' })
        if (!_isStaticCached(ep, '0x0008', '0x0002')) {
          items.push({ ieee: device.ieee, endpoint: epId, cluster: '0x0008', attribute: '0x0002' })
        }
        if (!_isStaticCached(ep, '0x0008', '0x0003')) {
          items.push({ ieee: device.ieee, endpoint: epId, cluster: '0x0008', attribute: '0x0003' })
        }
      }
      if (clusters.includes(768)) {
        if (!_isStaticCached(ep, '0x0300', '0x400A')) {
          items.push({ ieee: device.ieee, endpoint: epId, cluster: '0x0300', attribute: '0x400A' })
        }
        items.push({ ieee: device.ieee, endpoint: epId, cluster: '0x0300', attribute: '0x0008' })
        items.push({ ieee: device.ieee, endpoint: epId, cluster: '0x0300', attribute: '0x0000' })
        items.push({ ieee: device.ieee, endpoint: epId, cluster: '0x0300', attribute: '0x0001' })
        items.push({ ieee: device.ieee, endpoint: epId, cluster: '0x0300', attribute: '0x0003' })
        items.push({ ieee: device.ieee, endpoint: epId, cluster: '0x0300', attribute: '0x0004' })
        items.push({ ieee: device.ieee, endpoint: epId, cluster: '0x0300', attribute: '0x0007' })
        if (!_isStaticCached(ep, '0x0300', '0x400B')) {
          items.push({ ieee: device.ieee, endpoint: epId, cluster: '0x0300', attribute: '0x400B' })
        }
        if (!_isStaticCached(ep, '0x0300', '0x400C')) {
          items.push({ ieee: device.ieee, endpoint: epId, cluster: '0x0300', attribute: '0x400C' })
        }
      }
    }
    if (endpoints.length === 0) {
      items.push({ ieee: device.ieee, endpoint: 1, cluster: '0x0006', attribute: '0x0000' })
    }
  }
  if (items.length > 0) {
    try {
      await api.readAttrBatch(items)
    } catch (e: any) {
      logEvent('Batch read_attr failed: ' + e.message)
    }
  }
}

export function useHubStore() {
  return {
    state: readonly(state),
    logEvent,
    clearEvents: () => { state.events = [] },
    connect,
    disconnect,
    loadDevices,
    refreshDevices,
    refreshPorts,
    restoreConnection,
    loadPanels,
    reorderPanels,
    pollDevices,
    addPendingCommand,
    removePendingCommand,
    clearPendingCommands,
  }
}
