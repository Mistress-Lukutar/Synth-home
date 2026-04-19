<template>
  <div class="node-palette">
    <div class="palette-header">
      <input
        v-model="filter"
        class="palette-filter"
        placeholder="Search nodes..."
      />
    </div>
    <div class="palette-content">
      <div
        v-for="(nodes, category) in filteredGroups"
        :key="category"
        class="palette-category"
      >
        <div class="category-title" @click="toggleCategory(category)">
          <span class="category-chevron" :class="{ collapsed: collapsed[category] }">▾</span>
          {{ formatCategory(category) }}
        </div>
        <div v-show="!collapsed[category]" class="category-nodes">
          <div
            v-for="node in nodes"
            :key="node.type"
            class="palette-node"
            :title="node.description"
            @click="$emit('add', node.type)"
          >
            <span class="node-dot" :style="{ background: categoryColor(category) }" />
            <span class="node-label">{{ node.label }}</span>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed } from 'vue'

interface NodeTypeMeta {
  type: string
  category: string
  label: string
  description: string
}

const props = defineProps<{
  registry: Record<string, NodeTypeMeta[]>
}>()

const emit = defineEmits<{
  (e: 'add', type: string): void
}>()

const filter = ref('')
const collapsed = ref<Record<string, boolean>>({})

function toggleCategory(cat: string) {
  collapsed.value[cat] = !collapsed.value[cat]
}

function formatCategory(cat: string): string {
  return cat.replace(/_/g, ' ').replace(/\b\w/g, l => l.toUpperCase())
}

function categoryColor(cat: string): string {
  const map: Record<string, string> = {
    primitive: '#ffaa00',
    device: '#00ff88',
    color: '#ff55ff',
    panel: '#00ccff',
    math: '#ff5555',
    logic: '#ffff55',
    trigger: '#aa88ff',
  }
  return map[cat] || '#888'
}

const filteredGroups = computed(() => {
  const q = filter.value.toLowerCase()
  const result: Record<string, NodeTypeMeta[]> = {}
  for (const [cat, nodes] of Object.entries(props.registry)) {
    const filtered = nodes.filter(
      n =>
        n.label.toLowerCase().includes(q) ||
        n.type.toLowerCase().includes(q) ||
        n.description.toLowerCase().includes(q)
    )
    if (filtered.length) {
      result[cat] = filtered
    }
  }
  return result
})
</script>

<style scoped>
.node-palette {
  display: flex;
  flex-direction: column;
  width: 240px;
  background: rgba(0, 0, 0, 0.4);
  border-right: 1px solid rgba(255, 255, 255, 0.05);
  height: 100%;
  overflow: hidden;
}

.palette-header {
  padding: 12px;
  border-bottom: 1px solid rgba(255, 255, 255, 0.05);
}

.palette-filter {
  width: 100%;
  background: rgba(255, 255, 255, 0.05);
  border: 1px solid rgba(255, 255, 255, 0.1);
  border-radius: 6px;
  padding: 6px 10px;
  color: #fff;
  font-size: 0.85rem;
  outline: none;
}
.palette-filter::placeholder {
  color: #666;
}

.palette-content {
  flex: 1;
  overflow-y: auto;
  padding: 8px;
}

.palette-category {
  margin-bottom: 8px;
}

.category-title {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 0.75rem;
  text-transform: uppercase;
  color: #888;
  padding: 6px 4px;
  cursor: pointer;
  user-select: none;
  letter-spacing: 0.5px;
}
.category-title:hover {
  color: #aaa;
}

.category-chevron {
  display: inline-block;
  transition: transform 0.2s;
  font-size: 0.7rem;
}
.category-chevron.collapsed {
  transform: rotate(-90deg);
}

.category-nodes {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.palette-node {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 6px 8px;
  border-radius: 6px;
  cursor: pointer;
  font-size: 0.85rem;
  color: #ccc;
  transition: background 0.15s;
}
.palette-node:hover {
  background: rgba(255, 255, 255, 0.08);
  color: #fff;
}

.node-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  flex-shrink: 0;
}

.node-label {
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
</style>
