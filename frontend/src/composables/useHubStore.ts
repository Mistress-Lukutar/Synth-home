import { reactive, readonly } from 'vue'
import * as api from '../api'

export interface Device {
  ieee: string
  name?: string
  endpoint?: number
  online?: boolean
}

export interface Scenario {
  id: number
  name: string
  is_enabled: boolean
  trigger_type: string
  trigger_data?: any
  action_type: string
  action_data?: any
}

export interface HubEvent {
  time: string
  text: string
}

interface State {
  isConnected: boolean
  currentPort: string | null
  devices: Device[]
  scenarios: Scenario[]
  events: HubEvent[]
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
  } else if (msg.type === 'hub_message') {
    const data = msg.data || {}
    const evt = data.evt || data.event || 'message'
    if (evt !== 'device_list') {
      logEvent(`Hub: ${evt}`)
    }
    if (['device_joined', 'device_left', 'state_change'].includes(evt)) {
      refreshDevices()
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
  }
}
