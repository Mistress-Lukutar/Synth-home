<template>
  <div class="node-properties">
    <div class="properties-header">
      <h4>{{ meta?.label || node.type }}</h4>
      <span class="properties-type">{{ node.type }}</span>
    </div>
    <div v-if="meta?.description" class="properties-desc">{{ meta.description }}</div>
    <div class="properties-fields">
      <div v-for="field in meta?.config_fields" :key="field.name" class="field-row">
        <label class="field-label">{{ field.label }}</label>
        <input
          v-if="field.type === 'text' || field.type === 'device_select'"
          class="field-input"
          :value="node.data[field.name] ?? field.default ?? ''"
          @input="e => update(field.name, (e.target as HTMLInputElement).value)"
        />
        <input
          v-else-if="field.type === 'number'"
          class="field-input"
          type="number"
          :value="node.data[field.name] ?? field.default ?? 0"
          @input="e => update(field.name, parseFloat((e.target as HTMLInputElement).value))"
        />
        <input
          v-else-if="field.type === 'checkbox'"
          class="field-checkbox"
          type="checkbox"
          :checked="node.data[field.name] ?? field.default ?? false"
          @change="e => update(field.name, (e.target as HTMLInputElement).checked)"
        />
        <input
          v-else-if="field.type === 'color'"
          class="field-color"
          type="color"
          :value="node.data[field.name] ?? field.default ?? '#ffffff'"
          @input="e => update(field.name, (e.target as HTMLInputElement).value)"
        />
        <select
          v-else-if="field.type === 'select'"
          class="field-select"
          :value="node.data[field.name] ?? field.default ?? ''"
          @change="e => update(field.name, (e.target as HTMLSelectElement).value)"
        >
          <option v-for="opt in field.options" :key="opt.value" :value="opt.value">
            {{ opt.label }}
          </option>
        </select>
      </div>
      <div v-if="!meta?.config_fields?.length" class="no-fields">No configurable properties</div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'

interface NodeConfigField {
  name: string
  label: string
  type: string
  default?: any
  options?: { value: string; label: string }[]
}

interface NodeTypeMeta {
  type: string
  label: string
  description: string
  category: string
  config_fields: NodeConfigField[]
}

const props = defineProps<{
  node: { id: string; type: string; data: Record<string, any> }
  registry: Record<string, NodeTypeMeta[]>
}>()

const emit = defineEmits<{
  (e: 'update', nodeId: string, data: Record<string, any>): void
}>()

const meta = computed(() => {
  for (const cat of Object.values(props.registry)) {
    const found = cat.find((n) => n.type === props.node.type)
    if (found) return found
  }
  return null
})

function update(fieldName: string, value: any) {
  emit('update', props.node.id, { [fieldName]: value })
}
</script>

<style scoped>
.node-properties {
  width: 240px;
  background: rgba(0, 0, 0, 0.4);
  border-left: 1px solid rgba(255, 255, 255, 0.05);
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.properties-header {
  padding: 12px;
  border-bottom: 1px solid rgba(255, 255, 255, 0.08);
}
.properties-header h4 {
  font-size: 0.9rem;
  color: #fff;
  margin: 0 0 4px;
}
.properties-type {
  font-size: 0.7rem;
  color: #888;
  text-transform: uppercase;
  letter-spacing: 0.5px;
}

.properties-desc {
  padding: 8px 12px;
  font-size: 0.8rem;
  color: #888;
  border-bottom: 1px solid rgba(255, 255, 255, 0.05);
}

.properties-fields {
  flex: 1;
  overflow-y: auto;
  padding: 12px;
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.field-row {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.field-label {
  font-size: 0.75rem;
  color: #aaa;
}

.field-input,
.field-select {
  background: rgba(255, 255, 255, 0.05);
  border: 1px solid rgba(255, 255, 255, 0.1);
  border-radius: 6px;
  padding: 6px 8px;
  color: #fff;
  font-size: 0.85rem;
  outline: none;
}
.field-input:focus,
.field-select:focus {
  border-color: rgba(0, 255, 136, 0.4);
}

.field-checkbox {
  width: 18px;
  height: 18px;
  accent-color: #00ff88;
}

.field-color {
  width: 100%;
  height: 32px;
  border: none;
  border-radius: 6px;
  cursor: pointer;
  background: transparent;
}

.no-fields {
  color: #666;
  font-size: 0.8rem;
  text-align: center;
  padding: 20px 0;
  font-style: italic;
}
</style>
