<template>
  <div class="dashboard" :class="{ disabled: !store.state.isConnected }">
    <!-- Devices -->
    <div class="control-panel">
      <div class="panel-header">
        <h2 class="panel-title">Devices</h2>
        <button class="btn btn-secondary btn-small" @click="onRefresh" :disabled="!store.state.isConnected">Refresh</button>
      </div>
      <div class="device-cards-container">
        <div v-if="store.state.devices.length === 0" class="device-empty">{{ store.state.isConnected ? 'No devices found' : 'Not connected' }}</div>
        <DeviceCard v-for="d in store.state.devices" :key="d.ieee" :device="d" />
      </div>
    </div>

    <!-- Event Log -->
    <EventLog />

    <!-- System Info (Network + Hub Info) -->
    <div class="system-info-row">
      <div class="control-panel">
        <div class="panel-header">
          <h2 class="panel-title">Network</h2>
          <button class="btn btn-secondary btn-small" @click="doPermitJoin" :disabled="!store.state.isConnected">Permit Join</button>
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
    </div>
  </div>
</template>

<script setup lang="ts">
import { useHubStore } from '../composables/useHubStore'
import * as api from '../api'
import DeviceCard from './DeviceCard.vue'
import EventLog from './EventLog.vue'

const store = useHubStore()

async function onRefresh() {
  await store.refreshDevices()
  await store.pollDevices()
}

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
  display: flex;
  flex-direction: column;
  gap: 20px;
}
.dashboard.disabled { opacity: 0.5; pointer-events: none; }

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

/* Devices grid — up to 4 columns */
.device-cards-container {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(300px, 1fr));
  gap: 12px;
}
.device-empty {
  grid-column: 1 / -1;
  text-align: center;
  color: #666;
  padding: 30px;
  font-style: italic;
}

/* System info row (Network + Hub Info side by side) */
.system-info-row {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 20px;
}

.info-grid {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 10px;
}
.info-item {
  background: rgba(0,0,0,0.2);
  padding: 12px;
  border-radius: 8px;
}
.info-label {
  font-size: 0.65rem;
  text-transform: uppercase;
  color: #888;
  margin-bottom: 4px;
  letter-spacing: 0.5px;
}
.info-value {
  font-size: 0.95rem;
  font-weight: 600;
}

.btn {
  padding: 8px 16px;
  border: none;
  border-radius: 6px;
  cursor: pointer;
  font-size: 13px;
  font-weight: 600;
  transition: all 0.2s;
  text-transform: uppercase;
  letter-spacing: 0.5px;
}
.btn:disabled { opacity: 0.4; cursor: not-allowed; }
.btn-secondary {
  background: rgba(255,255,255,0.1);
  color: white;
}
.btn-secondary:hover:not(:disabled) { background: rgba(255,255,255,0.15); }
.btn-small { padding: 6px 12px; font-size: 12px; }

@media (max-width: 1200px) {
  .system-info-row { grid-template-columns: 1fr; }
}
@media (max-width: 768px) {
  .device-cards-container { grid-template-columns: 1fr; }
  .info-grid { grid-template-columns: 1fr; }
}
</style>
