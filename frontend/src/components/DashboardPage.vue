<template>
  <div class="dashboard" :class="{ disabled: !store.state.isConnected }">
    <div class="dashboard-left">
      <div class="control-panel">
        <div class="panel-header">
          <h2 class="panel-title">Devices</h2>
          <button class="btn btn-secondary btn-small" @click="store.refreshDevices" :disabled="!store.state.isConnected">Refresh</button>
        </div>
        <div class="device-cards-container">
          <div v-if="store.state.devices.length === 0" class="device-empty">{{ store.state.isConnected ? 'No devices found' : 'Not connected' }}</div>
          <DeviceCard v-for="d in store.state.devices" :key="d.ieee" :device="d" />
        </div>
      </div>

      <div class="control-panel">
        <h2 class="panel-title">Network</h2>
        <div class="network-actions">
          <button class="btn btn-primary" @click="doPermitJoin" :disabled="!store.state.isConnected">Permit Join</button>
        </div>
        <div class="info-grid">
          <div class="info-item">
            <div class="info-label">Network State</div>
            <div class="info-value">{{ store.state.isConnected ? 'Open' : '-' }}</div>
          </div>
          <div class="info-item">
            <div class="info-label">Joined Devices</div>
            <div class="info-value">{{ store.state.devices.length }}</div>
          </div>
        </div>
      </div>
    </div>

    <div class="dashboard-right">
      <div class="control-panel">
        <h2 class="panel-title">Hub Info</h2>
        <div class="info-grid">
          <div class="info-item">
            <div class="info-label">Port</div>
            <div class="info-value">{{ store.state.currentPort ?? '-' }}</div>
          </div>
          <div class="info-item">
            <div class="info-label">Uptime</div>
            <div class="info-value">-</div>
          </div>
          <div class="info-item">
            <div class="info-label">Firmware</div>
            <div class="info-value">-</div>
          </div>
          <div class="info-item">
            <div class="info-label">Zigbee Role</div>
            <div class="info-value">Coordinator</div>
          </div>
        </div>
      </div>

      <EventLog />
    </div>
  </div>
</template>

<script setup lang="ts">
import { useHubStore } from '../composables/useHubStore'
import * as api from '../api'
import DeviceCard from './DeviceCard.vue'
import EventLog from './EventLog.vue'

const store = useHubStore()

async function doPermitJoin() {
  if (!store.state.isConnected) return
  store.logEvent('Permit join sent (180s)')
  try {
    await api.permitJoin(180)
  } catch (e: any) {
    store.logEvent('Permit join error: ' + e.message)
  }
}
</script>

<style scoped>
.dashboard {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 20px;
  align-items: start;
}
.dashboard.disabled { opacity: 0.5; pointer-events: none; }
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
  transition: opacity 0.3s;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}
.panel-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 15px;
  flex-shrink: 0;
}
.panel-title {
  font-size: 1rem;
  color: #aaa;
  text-transform: uppercase;
  letter-spacing: 1px;
  flex-shrink: 0;
}
.device-cards-container {
  display: flex;
  flex-direction: column;
  gap: 10px;
  flex: 1;
  overflow-y: auto;
  min-height: 0;
}
.device-cards-container::-webkit-scrollbar { width: 6px; }
.device-cards-container::-webkit-scrollbar-track { background: rgba(0,0,0,0.1); border-radius: 3px; }
.device-cards-container::-webkit-scrollbar-thumb { background: rgba(255,255,255,0.2); border-radius: 3px; }
.device-empty { text-align: center; color: #666; padding: 30px; font-style: italic; }
.network-actions { display: flex; gap: 10px; flex-wrap: wrap; margin-bottom: 15px; }
.info-grid { display: grid; grid-template-columns: repeat(2, 1fr); gap: 10px; }
.info-item { background: rgba(0,0,0,0.2); padding: 12px; border-radius: 8px; }
.info-label { font-size: 0.65rem; text-transform: uppercase; color: #888; margin-bottom: 4px; letter-spacing: 0.5px; }
.info-value { font-size: 0.95rem; font-weight: 600; }

.btn { padding: 8px 16px; border: none; border-radius: 6px; cursor: pointer; font-size: 13px; font-weight: 600; transition: all 0.2s; text-transform: uppercase; letter-spacing: 0.5px; }
.btn:disabled { opacity: 0.4; cursor: not-allowed; }
.btn-primary { background: #333; color: white; }
.btn-primary:hover:not(:disabled) { background: #444; }
.btn-secondary { background: rgba(255,255,255,0.1); color: white; }
.btn-secondary:hover:not(:disabled) { background: rgba(255,255,255,0.15); }
.btn-small { padding: 6px 12px; font-size: 12px; }

@media (max-width: 1200px) {
  .dashboard { grid-template-columns: 1fr; }
}
@media (max-width: 768px) {
  .info-grid { grid-template-columns: 1fr; }
}
</style>
