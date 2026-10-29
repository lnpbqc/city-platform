<script setup lang="ts">
import type { AssetReference } from '../types'
import { referenceGuidance, referenceType, referenceVersion } from '../assetReferences'

defineProps<{ references: AssetReference[] }>()
</script>

<template>
  <ul class="asset-references">
    <li v-for="record in references" :key="`${record.type || 'layer'}:${record.id}:${referenceVersion(record)}`">
      <strong>{{ referenceType(record) }} · {{ record.name }}</strong>
      <span>ID：{{ record.id }}</span>
      <span v-if="referenceVersion(record)">{{ referenceVersion(record) }}</span>
      <p>{{ referenceGuidance(record) }}</p>
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
