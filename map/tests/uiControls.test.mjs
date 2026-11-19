import { test } from 'node:test'
import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'

test('each map toolbar tooltip describes exactly one native button', async () => {
  const source = await readFile(new URL('../src/components/map/MapToolbar.vue', import.meta.url), 'utf8')
  for (const match of source.matchAll(/<UiTooltip\b[\s\S]*?<\/UiTooltip>/g)) {
    assert.equal((match[0].match(/<button\b/g) ?? []).length, 1)
  }
})
