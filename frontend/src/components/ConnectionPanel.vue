<template>
  <div class="connection-panel">
    <div class="connection-status">
      <div class="status-dot" :class="{ connected: store.state.isConnected }"></div>
      <span>{{ statusText }}</span>
    </div>
    <div class="connection-controls" v-if="!store.state.isConnected">
      <select v-model="selectedPort" class="port-select">
        <option value="">Select port...</option>
        <option v-for="p in ports" :key="p" :value="p">{{ p }}</option>
      </select>
      <button class="btn btn-secondary" @click="doRefreshPorts">Refresh</button>
      <button class="btn btn-success" @click="doConnect">Connect</button>
    </div>
    <button class="btn btn-danger" v-else @click="store.disconnect">Disconnect</button>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useHubStore } from '../composables/useHubStore'

const store = useHubStore()
const selectedPort = ref('')
const ports = ref<string[]>([])

const statusText = computed(() => {
  if (store.state.isConnected) return `Connected: ${store.state.currentPort}`
  return 'Disconnected'
})

async function doRefreshPorts() {
  ports.value = await store.refreshPorts()
}

async function doConnect() {
  if (!selectedPort.value) {
    alert('Select a COM port')
    return
  }
  const ok = await store.connect(selectedPort.value)
  if (ok) ports.value = []
}

onMounted(async () => {
  await doRefreshPorts()
  await store.restoreConnection()
  if (store.state.isConnected && store.state.currentPort) {
    selectedPort.value = store.state.currentPort
  }
})
</script>

<style scoped>
.connection-panel {
  background: rgba(255,255,255,0.05);
  border-radius: 12px;
  padding: 12px 20px;
  margin-bottom: 20px;
  display: flex;
  align-items: center;
  gap: 20px;
  flex-shrink: 0;
}
.connection-status {
  display: flex;
  align-items: center;
  gap: 10px;
  min-width: 200px;
}
.status-dot {
  width: 10px;
  height: 10px;
  border-radius: 50%;
  background: #ff4444;
  animation: pulse 2s infinite;
}
.status-dot.connected { background: #00ff88; animation: none; }
@keyframes pulse { 0%,100%{opacity:1;} 50%{opacity:0.5;} }
.connection-controls {
  display: flex;
  align-items: center;
  gap: 10px;
  flex: 1;
}
.port-select {
  padding: 8px 12px;
  border-radius: 6px;
  border: none;
  background: rgba(255,255,255,0.1);
  color: white;
  font-size: 13px;
}
.port-select option { background: #222; color: #fff; }

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
.btn-primary { background: #333; color: white; }
.btn-primary:hover:not(:disabled) { background: #444; }
.btn-success { background: #00ff88; color: #111; }
.btn-success:hover:not(:disabled) { background: #00cc6a; }
.btn-danger { background: #ff4444; color: white; }
.btn-danger:hover:not(:disabled) { background: #cc0000; }
.btn-secondary { background: rgba(255,255,255,0.1); color: white; }
.btn-secondary:hover:not(:disabled) { background: rgba(255,255,255,0.15); }

@media (max-width: 768px) {
  .connection-panel { flex-direction: column; align-items: stretch; gap: 10px; }
  .connection-controls { flex-wrap: wrap; }
}
</style>
