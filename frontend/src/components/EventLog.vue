<template>
  <div class="control-panel">
    <h2 class="panel-title">Event Log</h2>
    <div class="event-log" ref="logRef">
      <div v-if="store.state.events.length === 0" class="event-item" style="color:#666;">Waiting for connection...</div>
      <div v-for="(evt, i) in store.state.events" :key="i" class="event-item">
        <span class="event-time">[{{ evt.time }}]</span> {{ evt.text }}
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, watch, nextTick } from 'vue'
import { useHubStore } from '../composables/useHubStore'

const store = useHubStore()
const logRef = ref<HTMLDivElement | null>(null)

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
.panel-title {
  font-size: 1rem;
  margin-bottom: 15px;
  color: #aaa;
  text-transform: uppercase;
  letter-spacing: 1px;
  flex-shrink: 0;
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
.event-item { margin-bottom: 4px; color: #ccc; }
.event-time { color: #666; }
</style>
