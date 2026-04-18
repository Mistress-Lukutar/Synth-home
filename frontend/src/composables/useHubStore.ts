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

export interface Scenario {
  id: number
  name: string
  is_enabled: boolean
  sort_order: number
  trigger_type: string
  trigger_data?: any
  action_type: string
  action_data?: any
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
  scenarios: Scenario[]
  events: HubEvent[]
  pendingCommands: Map<string, PendingCommand>
  sseReconnectDelay: number
  evtSource: EventSource | null
  sseReconnectTimer: ReturnType<typeof setTimeout> | null
  refreshingDevices: boolean
}

const state = reactive<State>({
  isConnected: false,
  currentPort: null,
  devices: [],
  scenarios: [],
  events: [],
  pendingCommands: new Map(),
  sseReconnectDelay: 1000,
  evtSource: null,
  sseReconnectTimer: null,
  refreshingDevices: false,
})

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
  } else if (msg.type === 'scenario_triggered') {
    logEvent(`⏰ Scenario triggered: ${msg.scenario_name} (id=${msg.scenario_id})`)
  } else if (msg.type === 'scenario_executed') {
    logEvent(`✅ Scenario executed: ${msg.scenario_name} (id=${msg.scenario_id})`)
  } else if (msg.type === 'scenario_execution_failed') {
    logEvent(`❌ Scenario FAILED: ${msg.scenario_name} — ${msg.error}`)
  } else if (msg.type === 'scenario_skipped') {
    logEvent(`⏭️ Scenario skipped: ${msg.scenario_name} — ${msg.reason}`)
  }
}

function handleAck(data: any) {
  const evt = data.evt || data.event || ''
  const action = evt.replace('_ack', '')
  const ieee = data.ieee
  const ok = data.ok
  const value = data.value
  const endpoint = data.endpoint
  if (!ieee) return

  const device = state.devices.find(d => d.ieee === ieee)
  if (!device) return
  if (!device.state) device.state = {}
  const epKey = String(endpoint || '1')
  if (!device.state[epKey]) device.state[epKey] = {}

  if (action === 'on') {
    device.state[epKey].on = Boolean(ok)
  } else if (action === 'off') {
    device.state[epKey].on = !Boolean(ok)
  } else if (action === 'toggle') {
    device.state[epKey].on = Boolean(ok)
  } else if (action === 'level') {
    if (value !== undefined) device.state[epKey].level = Number(value)
  } else if (action === 'color') {
    if (value !== undefined) device.state[epKey].color = value
  }
}

function handleStateChange(data: any) {
  const ieee = data.ieee_addr
  if (!ieee) return
  const device = state.devices.find(d => d.ieee === ieee)
  if (!device) return
  if (!device.state) device.state = {}

  const changes = data.changes || []
  if (changes.length > 0) {
    for (const change of changes) {
      const cluster = change.cluster || ''
      const attr = change.attribute || ''
      const value = change.value
      const epKey = '1' // read_attr doesn't specify endpoint in changes; assume 1
      if (!device.state[epKey]) device.state[epKey] = {}

      const clusterId = parseInt(cluster, 16)
      const attrId = parseInt(attr, 16)

      if (clusterId === 0x0006 && attrId === 0x0000) {
        device.state[epKey].on = Boolean(value)
      } else if (clusterId === 0x0008 && attrId === 0x0000) {
        device.state[epKey].level = Number(value)
      } else if (clusterId === 0x0008 && attrId === 0x0002) {
        device.state[epKey].level_min = Number(value)
      } else if (clusterId === 0x0008 && attrId === 0x0003) {
        device.state[epKey].level_max = Number(value)
      } else if (clusterId === 0x0300 && attrId === 0x4002) {
        const bitmask = Number(value)
        device.state[epKey].color_caps = {
          hs: !!(bitmask & 0x01),
          xy: !!(bitmask & 0x10),
          ct: !!(bitmask & 0x20),
          color_loop: !!(bitmask & 0x08),
        }
      } else if (clusterId === 0x0300 && attrId === 0x0000) {
        device.state[epKey].hue = Number(value)
      } else if (clusterId === 0x0300 && attrId === 0x0001) {
        device.state[epKey].sat = Number(value)
      } else if (clusterId === 0x0300 && attrId === 0x0003) {
        device.state[epKey].x = Number(value) / 65535
      } else if (clusterId === 0x0300 && attrId === 0x0004) {
        device.state[epKey].y = Number(value) / 65535
      } else if (clusterId === 0x0300 && attrId === 0x0007) {
        device.state[epKey].ct = Number(value)
      }
    }
  } else {
    // Old flat format fallback
    const epKey = String(data.endpoint || '1')
    if (!device.state[epKey]) device.state[epKey] = {}
    const clusterId = data.cluster_id
    const attrId = data.attr_id
    const value = data.value
    if (clusterId === 6 && attrId === 0) device.state[epKey].on = Boolean(value)
    else if (clusterId === 8) device.state[epKey].level = Number(value)
    else if (clusterId === 768) device.state[epKey].color = value
  }
}

function handleCommandStatus(data: any) {
  const correlationId = data.correlation_id
  const status = data.status
  if (!correlationId) return

  const pending = state.pendingCommands.get(correlationId)
  if (!pending) return

  // Ignore timeout — on_ack or state_change will eventually update the real state
  if (status === 'timeout') {
    logEvent(`Command ${pending.action} timeout for ${pending.ieee} (ignored, waiting for on_ack/state_change)`)
    state.pendingCommands.delete(correlationId)
    return
  }

  if (status === 'completed') {
    const device = state.devices.find(d => d.ieee === pending.ieee)
    if (device) {
      const epKey = String(pending.endpoint || '1')
      if (!device.state) device.state = {}
      if (!device.state[epKey]) device.state[epKey] = {}
      if (pending.action === 'on') device.state[epKey].on = true
      else if (pending.action === 'off') device.state[epKey].on = false
      else if (pending.action === 'toggle') device.state[epKey].on = !device.state[epKey].on
    }
    state.pendingCommands.delete(correlationId)
  } else if (status === 'failed') {
    logEvent(`Command ${pending.action} failed for ${pending.ieee}`)
    state.pendingCommands.delete(correlationId)
  } else if (status === 'pending' || status === 'delivered') {
    // Intermediate states — keep waiting
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
      await refreshDevices()
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
  stopSSE()
  logEvent('Disconnected')
}

async function refreshDevices() {
  if (!state.isConnected || state.refreshingDevices) return
  state.refreshingDevices = true
  try {
    const data = await api.listDevices()
    if (data.success) {
      state.devices = data.devices || []
    }
    // Request ColorCapabilities (0x0300/0x4002) for every endpoint with Color Control cluster
    for (const device of state.devices) {
      for (const ep of device.endpoints || []) {
        if ((ep.clusters || []).includes(768)) {
          api.readAttr(device.ieee, ep.id, '0x0300', '0x4002').catch(() => {})
        }
      }
    }
  } catch (e: any) {
    logEvent('Load devices error: ' + e.message)
  } finally {
    state.refreshingDevices = false
  }
}

async function restoreConnection() {
  try {
    const data = await api.getStatus()
    if (data.connected && data.port) {
      state.isConnected = true
      state.currentPort = data.port
      startSSE()
      await refreshDevices()
    }
  } catch {
    // stay disconnected
  }
}

async function loadScenarios() {
  try {
    state.scenarios = await api.listScenarios()
  } catch (e: any) {
    logEvent('Load scenarios error: ' + e.message)
  }
}

async function reorderScenarios(fromIndex: number, toIndex: number) {
  const list = [...state.scenarios]
  const [moved] = list.splice(fromIndex, 1)
  list.splice(toIndex, 0, moved)
  list.forEach((s, i) => { s.sort_order = i })
  state.scenarios = list
  try {
    await api.reorderScenarios(list.map((s, i) => ({ id: s.id, sort_order: i })))
  } catch (e: any) {
    logEvent('Reorder failed: ' + e.message)
    await loadScenarios()
  }
}

async function pollDevices() {
  if (!state.isConnected) return
  logEvent('Polling device attributes...')
  for (const device of state.devices) {
    if (device.online === false) continue
    const endpoints = device.endpoints || []
    for (const ep of endpoints) {
      const epId = ep.id
      const clusters = ep.clusters || []
      if (clusters.includes(6)) {
        await api.readAttr(device.ieee, epId, '0x0006', '0x0000').catch(() => {})
      }
      if (clusters.includes(8)) {
        await api.readAttr(device.ieee, epId, '0x0008', '0x0000').catch(() => {}) // CurrentLevel
        await api.readAttr(device.ieee, epId, '0x0008', '0x0002').catch(() => {}) // MinLevel
        await api.readAttr(device.ieee, epId, '0x0008', '0x0003').catch(() => {}) // MaxLevel
      }
      if (clusters.includes(768)) {
        await api.readAttr(device.ieee, epId, '0x0300', '0x4002').catch(() => {}) // ColorCapabilities
        await api.readAttr(device.ieee, epId, '0x0300', '0x0000').catch(() => {}) // CurrentHue
        await api.readAttr(device.ieee, epId, '0x0300', '0x0001').catch(() => {}) // CurrentSaturation
        await api.readAttr(device.ieee, epId, '0x0300', '0x0003').catch(() => {}) // CurrentX
        await api.readAttr(device.ieee, epId, '0x0300', '0x0004').catch(() => {}) // CurrentY
        await api.readAttr(device.ieee, epId, '0x0300', '0x0007').catch(() => {}) // ColorTemperatureMireds
      }
    }
    if (endpoints.length === 0) {
      await api.readAttr(device.ieee, 1, '0x0006', '0x0000').catch(() => {})
    }
  }
}

export function useHubStore() {
  return {
    state: readonly(state),
    logEvent,
    connect,
    disconnect,
    refreshDevices,
    refreshPorts,
    restoreConnection,
    loadScenarios,
    reorderScenarios,
    pollDevices,
  }
}
