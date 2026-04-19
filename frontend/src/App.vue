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
      <nav class="nav-links">
        <button :class="['nav-link', { active: page === 'dashboard' }]" @click="page = 'dashboard'">Dashboard</button>
        <button :class="['nav-link', { active: page === 'scenarios' }]" @click="page = 'scenarios'">Scenarios</button>
      </nav>
    </header>

    <ConnectionPanel />

    <DashboardPage v-if="page === 'dashboard'" />
    <ScenariosPage v-else />
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import ConnectionPanel from './components/ConnectionPanel.vue'
import DashboardPage from './components/DashboardPage.vue'
import ScenariosPage from './components/ScenariosPage.vue'
import { useHubStore } from './composables/useHubStore'

const page = ref<'dashboard' | 'scenarios'>('dashboard')
const store = useHubStore()

onMounted(() => {
  store.restoreConnection()
  store.loadScenarios()
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

.nav-links { display: flex; gap: 8px; }
.nav-link {
  color: #888;
  background: transparent;
  border: none;
  text-decoration: none;
  font-size: 0.9rem;
  padding: 6px 12px;
  border-radius: 6px;
  cursor: pointer;
  transition: all 0.2s;
}
.nav-link:hover { color: #fff; background: rgba(255,255,255,0.05); }
.nav-link.active { color: #00ff88; background: rgba(0,255,136,0.1); }

@media (max-width: 768px) {
  .container { padding: 10px 15px; }
  header { flex-direction: column; text-align: center; gap: 5px; }
}
</style>
