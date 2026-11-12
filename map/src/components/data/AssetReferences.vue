<script setup lang="ts">
import type { AssetReference } from '../../layers/types'
import { referenceGuidance, referenceType, referenceVersion } from '../../catalog/assetReferences'

defineProps<{ references: AssetReference[]; sceneLinks?: boolean }>()
const emit = defineEmits<{ scene: [id: string] }>()
</script>

<template>
  <ul class="asset-references">
    <li v-for="record in references" :key="`${record.type || 'layer'}:${record.id}:${referenceVersion(record)}`">
      <strong>{{ referenceType(record) }} · {{ record.name }}</strong>
      <span>ID：{{ record.id }}</span>
      <span v-if="referenceVersion(record)">{{ referenceVersion(record) }}</span>
      <p>{{ referenceGuidance(record) }}</p>
      <button v-if="sceneLinks && record.type === 'scene'" class="text-button" @click="emit('scene', record.id)">管理此场景</button>
    </li>
  </ul>
</template>

<style scoped>
.asset-references {
  margin: 12px 0 0;
  padding: 0;
  list-style: none;
}
.asset-references li {
  display: grid;
  gap: 4px;
  padding: 12px 0;
  border-bottom: 1px solid #e2e8f0;
  overflow-wrap: anywhere;
}
button { justify-self: start; }
strong {
  font-size: 13px;
  color: #29405a;
}
span {
  font-size: 12px;
  color: #65788e;
}
p {
  margin: 3px 0 0;
  font-size: 12px;
  line-height: 1.6;
  color: #65788e;
}
</style>
