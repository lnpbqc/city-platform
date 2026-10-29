import { test } from 'node:test'
import assert from 'node:assert/strict'
import { readWorkspacePage } from '../src/workspaceRoute.ts'

test('workspace routes distinguish map, direct data entry, and unknown hashes', () => {
  assert.equal(readWorkspacePage('#/map'), 'map')
  assert.equal(readWorkspacePage('#/data'), 'data')
  assert.equal(readWorkspacePage('#/simulation'), 'simulation')
  assert.equal(readWorkspacePage(''), 'map')
  assert.equal(readWorkspacePage('#unknown'), 'map')
})
