<template>
  <div class="control-panel">
    <div class="log-header">
      <h2 class="panel-title">Event Log</h2>
      <div class="log-actions">
        <input
          v-model="filterText"
          type="text"
          class="log-filter"
          placeholder="Filter events..."
        />
        <button class="btn btn-small" @click="copyFiltered">Copy</button>
        <button class="btn btn-small" @click="clearLogs">Clear</button>
      </div>
    </div>
    <div class="event-log" ref="logRef">
      <div v-if="filteredEvents.length === 0" class="event-item" style="color:#666;">
        {{ store.state.events.length === 0 ? 'Waiting for connection...' : 'No matching events.' }}
      </div>
      <div v-for="(evt, i) in filteredEvents" :key="i" class="event-item">
        <span class="event-time">[{{ evt.time }}]</span> {{ evt.text }}
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, watch, nextTick, computed } from 'vue'
import { useHubStore } from '../composables/useHubStore'

const store = useHubStore()
const logRef = ref<HTMLDivElement | null>(null)
const filterText = ref('')

const filteredEvents = computed(() => {
  const q = filterText.value.trim().toLowerCase()
  if (!q) return store.state.events
  return store.state.events.filter((e) =>
    e.text.toLowerCase().includes(q) || e.time.toLowerCase().includes(q)
  )
})

async function copyFiltered() {
  const text = filteredEvents.value.map((e) => `[${e.time}] ${e.text}`).join('\n')
  try {
    await navigator.clipboard.writeText(text)
  } catch {
    // Fallback for non-secure contexts
    const ta = document.createElement('textarea')
    ta.value = text
    document.body.appendChild(ta)
    ta.select()
    document.execCommand('copy')
    document.body.removeChild(ta)
  }
}

function clearLogs() {
  store.clearEvents()
}

watch(() => store.state.events.length, async () => {
  await nextTick()
  if (logRef.value) logRef.value.scrollTop = logRef.value.scrollHeight
})
</script>

<style scoped>
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
.log-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
  margin-bottom: 15px;
  flex-shrink: 0;
}
.panel-title {
  font-size: 1rem;
  margin: 0;
  color: #aaa;
  text-transform: uppercase;
  letter-spacing: 1px;
}
.log-actions {
  display: flex;
  align-items: center;
  gap: 8px;
}
.log-filter {
  background: rgba(0,0,0,0.2);
  border: 1px solid rgba(255,255,255,0.1);
  border-radius: 4px;
  color: #fff;
  padding: 4px 8px;
  font-size: 0.8rem;
  outline: none;
  min-width: 140px;
}
.log-filter:focus {
  border-color: #00ff88;
}
.btn {
  background: rgba(255,255,255,0.1);
  border: 1px solid rgba(255,255,255,0.15);
  border-radius: 4px;
  color: #ccc;
  padding: 4px 10px;
  font-size: 0.75rem;
  cursor: pointer;
  transition: background 0.2s;
}
.btn:hover {
  background: rgba(255,255,255,0.2);
}
.event-log {
  max-height: 260px;
  overflow-y: auto;
  background: rgba(0,0,0,0.2);
  border-radius: 8px;
  padding: 10px 12px;
  font-family: 'SF Mono', Monaco, monospace;
  font-size: 0.8rem;
}
.event-log::-webkit-scrollbar { width: 6px; }
.event-log::-webkit-scrollbar-track { background: rgba(0,0,0,0.1); border-radius: 3px; }
.event-log::-webkit-scrollbar-thumb { background: rgba(255,255,255,0.2); border-radius: 3px; }
.event-item { margin-bottom: 4px; color: #ccc; white-space: pre-wrap; }
.event-time { color: #666; }
</style>
