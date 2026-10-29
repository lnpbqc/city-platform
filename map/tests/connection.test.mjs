import { test } from 'node:test'
import assert from 'node:assert/strict'
import { createRenderer, defineComponent } from 'vue'
import { ApiError, getScene } from '../src/api.ts'
import { publishApiEvent, subscribeApiEvents } from '../src/apiEvents.ts'
import { useConnection } from '../src/composables/useConnection.ts'

const renderer = createRenderer({ createElement:()=>({}),createText:()=>({}),createComment:()=>({}),insert(){},remove(){},setText(){},setElementText(){},patchProp(){},parentNode:()=>null,nextSibling:()=>null })
const flush = async () => { for(let i=0;i<6;i++) await Promise.resolve() }
function setup(t, fetch) {
  const previous=globalThis.window
  globalThis.window=new EventTarget()
  t.mock.timers.enable({apis:['setTimeout']})
  t.mock.method(globalThis,'fetch',fetch)
  let state, recovered=0
  const app=renderer.createApp(defineComponent({setup(){state=useConnection(()=>recovered++);return()=>null}}))
  app.mount({});t.after(()=>{app.unmount();globalThis.window=previous})
  return {state,app,recovered:()=>recovered}
}
test('connection coalesces failures, backs off, recovers once and releases timers/listeners',async t=>{
  let calls=0, healthy=true
  const ctx=setup(t,async()=>{calls++;if(!healthy)throw new TypeError('offline');return new Response('{}')})
  await flush();assert.equal(ctx.state.status.value,'online');assert.equal(ctx.recovered(),0)
  healthy=false
  publishApiEvent({reachable:false,error:new ApiError('offline',0,null,'NETWORK_ERROR','trace')})
  publishApiEvent({reachable:false})
  t.mock.timers.tick(0);await flush()
  assert.equal(calls,2)
  assert.equal(ctx.state.status.value,'retrying')
  assert.equal(ctx.state.retryIn.value,1)
  publishApiEvent({reachable:false})
  t.mock.timers.tick(999);await flush();assert.equal(calls,2)
  t.mock.timers.tick(1);await flush();assert.equal(calls,3);assert.equal(ctx.state.retryIn.value,2)
  healthy=true
  window.dispatchEvent(new Event('online'));await flush()
  assert.equal(ctx.state.status.value,'online');assert.equal(ctx.recovered(),1)
  publishApiEvent({reachable:true});assert.equal(ctx.recovered(),1)
  ctx.app.unmount();const stopped=calls
  t.mock.timers.tick(60000);window.dispatchEvent(new Event('online'));await flush()
  assert.equal(calls,stopped)
})
test('an in-flight health failure cannot overwrite a later successful API response',async t=>{
  let reject
  const ctx=setup(t,()=>new Promise((resolve,no)=>{reject=no}))
  publishApiEvent({reachable:true})
  reject(new TypeError('late failure'));await flush()
  assert.equal(ctx.state.status.value,'online')
  assert.equal(ctx.recovered(),0)
})
test('permission and validation failures expose diagnostics without declaring a network outage',async t=>{
  const ctx=setup(t,async()=>new Response('{}'));await flush()
  const events=[],stop=subscribeApiEvents(event=>events.push(event));t.after(stop)
  t.mock.method(globalThis,'fetch',async()=>new Response(JSON.stringify({code:'ACCESS_DENIED',message:'读取被拒绝',trace_id:'server-trace'}),{status:403}))
  await assert.rejects(getScene('s'),cause=>cause.status===403&&cause.message.startsWith('无权限：')&&cause.traceId==='server-trace')
  assert.equal(ctx.state.status.value,'online');assert.equal(ctx.recovered(),0)
  assert.equal(ctx.state.lastError.value.code,'ACCESS_DENIED')
  assert.ok(events.every(event=>event.reachable))
  publishApiEvent({reachable:true,error:new ApiError('invalid edge',422,null,'INVALID_EDGE','edge-trace')})
  assert.equal(ctx.state.status.value,'online')
})
test('a response body interrupted after successful headers still reports an uncertain network failure',async t=>{
  const ctx=setup(t,async()=>new Response('{}'));await flush()
  t.mock.method(globalThis,'fetch',async()=>new Response(new ReadableStream({start(controller){controller.error(new TypeError('connection lost'))}})))
  await assert.rejects(getScene('s'),cause=>cause.code==='NETWORK_ERROR'&&cause.status===0&&cause.traceId.startsWith('client-'))
  assert.equal(ctx.state.status.value,'retrying')
  assert.equal(ctx.recovered(),0)
})
