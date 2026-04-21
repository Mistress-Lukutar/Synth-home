<template>
  <div class="container">
    <header>
      <div class="brand">
        <img src="/favicon.svg" alt="" class="logo" />
        <div>
          <h1>ZigbeeHUB</h1>
          <p>USB Serial Zigbee Coordinator</p>
        </div>
      </div>
    </header>

    <ConnectionPanel />

    <DashboardPage />
  </div>
</template>

<script setup lang="ts">
import { onMounted } from 'vue'
import ConnectionPanel from './components/ConnectionPanel.vue'
import DashboardPage from './components/DashboardPage.vue'
import { useHubStore } from './composables/useHubStore'

const store = useHubStore()

onMounted(() => {
  store.restoreConnection()
  store.loadPanels()
})
</script>

<style>
* { margin: 0; padding: 0; box-sizing: border-box; }

body {
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
  background: #1a1a1a;
  min-height: 100vh;
  color: #fff;
}

/* Dark scrollbars globally */
::-webkit-scrollbar {
  width: 8px;
  height: 8px;
}
::-webkit-scrollbar-track {
  background: rgba(0, 0, 0, 0.2);
  border-radius: 4px;
}
::-webkit-scrollbar-thumb {
  background: rgba(255, 255, 255, 0.15);
  border-radius: 4px;
}
::-webkit-scrollbar-thumb:hover {
  background: rgba(255, 255, 255, 0.25);
}
/* Firefox */
* {
  scrollbar-width: thin;
  scrollbar-color: rgba(255, 255, 255, 0.15) rgba(0, 0, 0, 0.2);
}

.container {
  max-width: 1600px;
  margin: 0 auto;
  padding: 15px 30px 30px;
  display: flex;
  flex-direction: column;
}

header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 15px 0 20px;
  border-bottom: 1px solid rgba(255,255,255,0.1);
  margin-bottom: 20px;
  flex-shrink: 0;
}

.brand { display: flex; align-items: center; gap: 15px; }
.brand .logo { width: 40px; height: 40px; }
h1 { font-size: 1.5rem; color: #fff; }
header p { color: #888; font-size: 0.9rem; }

@media (max-width: 768px) {
  .container { padding: 10px 15px; }
  header { flex-direction: column; text-align: center; gap: 5px; }
}
</style>
