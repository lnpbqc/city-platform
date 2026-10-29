import { test } from 'node:test'
import assert from 'node:assert/strict'
import { readWorkspaceAddress, workspaceURL } from '../src/workspaceState.ts'
import { getScene } from '../src/api.ts'

const camera = { longitude: 113.364, latitude: 23.043, height: 1400, heading: 0.4, pitch: -1.4, roll: 0.1, scene_mode: '3d' }
test('full map and simulation URLs round-trip fixed references, camera and independent times', () => {
  for (const page of ['map', 'simulation']) {
    const state = { page, scene_id: 'scene/id', scene_version: 3, run_id: page === 'simulation' ? 'run/id' : null,
      time: '2026-10-25T00:00:00.000Z', resolution: 'hour', camera,
      comparison: page === 'map' ? { time: '2026-10-24T16:00:00.000Z', resolution: 'day' } : null }
    const url = new URL(workspaceURL(state, 'http://localhost:5173/?custom=keep&run=old#/data'))
    assert.equal(url.searchParams.get('custom'), 'keep')
    assert.equal(url.hash, `/${page}`.replace('/', '#/'))
    assert.deepEqual(readWorkspaceAddress(url), { ...state, run_id: state.run_id ?? undefined })
  }
  assert.equal(readWorkspaceAddress(new URL('http://localhost/#/map')), null)
})
test('documented unzoned links use Shanghai time and run-only links select simulation', () => {
  const value = readWorkspaceAddress(new URL('http://localhost/?scene=s1&run=r1&t=2026-10-25T12:00'))
  assert.equal(value.time, '2026-10-25T04:00:00.000Z')
  assert.equal(value.page, 'simulation')
  assert.equal(readWorkspaceAddress(new URL('http://localhost/?t=1988-08-01T08:00')).time, '1988-07-31T23:00:00.000Z')
  assert.equal(readWorkspaceAddress(new URL('http://localhost/?t=2026-10-25T08:00:00%2B08:00')).time, '2026-10-25T00:00:00.000Z')
})
test('malformed references, dates, modes and camera fail with a trace instead of fallback', () => {
  for (const query of ['scene=', 'v=1', 'scene=s&v=0', 'scene=s&v=1.5', 'scene=s&v=9999999999999999999', 'scene=a&scene=b',
    'resolution=minute', 'compare_resolution=day', 'run=r&compare_t=2026-10-25T08:00', 't=2026-02-30T08:00', 't=2026-10-25T24:00',
    't=2026-10-25T08:00:00%2B25:00', 'camera={}', 'camera=invalid']) {
    assert.throws(() => readWorkspaceAddress(new URL(`http://localhost/?${query}`)), cause => cause.code === 'INVALID_WORKSPACE_LINK' && !!cause.traceId, query)
  }
})
test('fixed scene GET is conditional without changing legacy request URLs', async t => {
  const calls = [], signal = new AbortController().signal
  t.mock.method(globalThis, 'fetch', async (url, options) => { calls.push({ url, options }); return new Response('{}') })
  await getScene('s/id', signal)
  await getScene('s/id', signal, 7)
  assert.equal(calls[0].url, '/api/scenes/s%2Fid')
  assert.equal(calls[1].url, '/api/scenes/s%2Fid?version=7')
  assert.ok(calls.every(call => call.options.signal === signal))
})
