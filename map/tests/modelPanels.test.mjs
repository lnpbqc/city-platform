import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { test } from 'node:test'
import { stripTypeScriptTypes } from 'node:module'
import { compileScript, parse } from 'vue/compiler-sfc'
import { createSSRApp, createRenderer, h, nextTick } from 'vue'
import { renderToString } from 'vue/server-renderer'

async function component(path) {
  const url = new URL(path, import.meta.url)
  const { descriptor } = parse(readFileSync(url, 'utf8'))
  const script = compileScript(descriptor, { id: path, inlineTemplate: true }).content
  const source = stripTypeScriptTypes(script, { mode: 'transform' })
    .replace(/^import (.*?) from ['"]([^'"]+)['"];?$/gm, (_line, names, specifier) => {
      if (specifier.endsWith('UiTooltip.vue')) return `const ${names} = { inheritAttrs: false, setup: (_props, { slots }) => () => slots.default?.() }`
      if (specifier.endsWith('RenderStatus.vue')) return `const ${names} = { inheritAttrs: false, render() { return this.$attrs.render ? '显示数据处理反馈' : '' } }`
      if (specifier.endsWith('.vue')) {
        const text = specifier.endsWith('TilesHeightSettings.vue') ? '模型高度' : ''
        return `const ${names} = { inheritAttrs: false, render: () => ${JSON.stringify(text)} }`
      }
      return `import ${names} from ${JSON.stringify(specifier.startsWith('.') ? new URL(`${specifier}.ts`, url).href : import.meta.resolve(specifier))}`
    })
  return (await import(`data:text/javascript;base64,${Buffer.from(source).toString('base64')}`)).default
}

const layer = {
  id: 'model', name: '模型名称', type: '3dtiles', attached: true, visible: true, status: 'ready', opacity: 0.4,
  color: '#2672b4', category: '建筑', url: 'https://example.invalid/tileset.json',
}

test('model layer cards use calibration as the only height control and retain common actions', async () => {
  const item = await component('../src/components/layers/LayerItem.vue')
  const html = await renderToString(createSSRApp(item, { layer: { ...layer, tiles_calibration_allowed: true }, allowCalibration: true }))
  assert.doesNotMatch(html, /模型高度|对齐地形|手动锚点|保存高度设置/)
  assert.match(html, /校准模型/)
  assert.match(html, /定位模型名称/)
  assert.match(html, /模型名称不透明度/)
  assert.match(html, /从地图移除模型名称/)

  const external = await renderToString(createSSRApp(item, { layer, allowCalibration: true }))
  assert.match(external, /上传本地 3D Tiles 副本后可校准/)
  assert.doesNotMatch(external, /模型高度|手动锚点/)
})

test('calibration separates position and rotation and enables both save actions for a yaw-only edit', async () => {
  const panel = await component('../src/components/map/TilesCalibrationPanel.vue')
  const props = {
    name: layer.name, offsets: { east: 0, north: 0, up: 0, yaw: 6, pitch: 0, roll: 0 },
    busy: false, ready: true, saveReady: true, canPick: false, message: '', error: '',
  }
  const html = await renderToString(createSSRApp(panel, props))
  assert.match(html, /<legend>位置<\/legend>[\s\S]*选择模型贴地点（可选）[\s\S]*<legend>旋转<\/legend>[\s\S]*另选旋转中心/)
  assert.doesNotMatch(html, /<button[^>]*disabled[^>]*>(更新原资产|另存为新资产)<\/button>/)
  const unchanged = await renderToString(createSSRApp(panel, { ...props, offsets: { ...props.offsets, yaw: 0 }, saveReady: false, canPick: true }))
  assert.match(unchanged, /<button[^>]*disabled[^>]*>更新原资产<\/button>/)
  assert.match(unchanged, /<button[^>]*disabled[^>]*>另存为新资产<\/button>/)
  const failed = await renderToString(createSSRApp(panel, { ...props, error: '地形采样失败，请重试。' }))
  assert.match(failed, /<\/div><footer[^>]*><p[^>]*role="alert"[^>]*>地形采样失败，请重试。<\/p>/)
})

test('compact layer cards keep feedback outside hidden secondary controls', async () => {
  const item = await component('../src/components/layers/LayerItem.vue')
  const render = props => renderToString(createSSRApp(item, { layer: { ...layer, ...props } }))
  const html = await render({ status: 'error', error: '资源离线' })
  assert.match(html, /aria-expanded="false"/)
  assert.match(html, /class="layer-expanded"[^>]*style="display:none;"/)
  assert.match(html, /重试/)
  assert.ok(html.indexOf('重试') < html.indexOf('class="layer-expanded"'))
  assert.match(html, /role="alert">资源离线/)
  const loading = await render({ status: 'loading', progress: 42, loadPhase: '读取模型' })
  assert.match(loading, /读取模型 · 42%/)
  assert.ok(loading.indexOf('读取模型') < loading.indexOf('class="layer-expanded"'))
  for (const status of ['queued', 'running', 'failed', 'cancelled']) {
    const processing = await render({ render: { status, profile: 'roads' } })
    assert.match(processing, /显示数据处理反馈/)
    assert.ok(processing.indexOf('显示数据处理反馈') < processing.indexOf('class="layer-expanded"'), `${status} feedback stays visible when settings are collapsed`)
  }
})

test('layer details expand independently and preserve action event payloads', async () => {
  const item = await component('../src/components/layers/LayerItem.vue')
  const node = tag => ({ tag, props: {}, style: {}, children: [] })
  const renderer = createRenderer({
    createElement: node, createText: text => ({ ...node('#text'), text }), createComment: () => node('#comment'),
    setText: (n, text) => { n.text = text }, setElementText: (n, text) => { n.text = text },
    patchProp(n, key, _old, value) { n.props[key] = value },
    insert(n, parent, anchor) { n.parent = parent; const index = parent.children.indexOf(anchor); parent.children.splice(index < 0 ? parent.children.length : index, 0, n) },
    remove(n) { n.parent.children.splice(n.parent.children.indexOf(n), 1) },
    parentNode: n => n.parent, nextSibling: () => null,
  })
  const root = node('root'), events = []
  const firstProps = {
    layer: { ...layer, category: '道路', orderable: true, tiles_calibration_allowed: true },
    allowCalibration: true, canMoveUp: true, canMoveDown: true,
    onToggle: () => events.push(['toggle']), onLocate: () => events.push(['locate']),
    onRemove: () => events.push(['remove']), onMove: value => events.push(['move', value]),
    onOpacity: value => events.push(['opacity', value]), onRoadMaxLevel: value => events.push(['roadMaxLevel', value]),
    onCalibrate: () => events.push(['calibrate']),
  }
  const app = renderer.createApp({ render: () => h('div', [h(item, firstProps), h(item, { layer: { ...layer, id: 'second', name: '第二个图层' } })]) })
  app.mount(root)
  try {
    const walk = n => [n, ...n.children.flatMap(walk)]
    const find = predicate => walk(root).find(predicate)
    const label = text => find(n => n.props['aria-label'] === text)
    const detail = find(n => n.props.id === 'layer-details-model')
    const second = find(n => n.props.id === 'layer-details-second')
    const toggle = find(n => n.props.class === 'details-toggle')
    assert.equal(detail.style.display, 'none')
    assert.ok(walk(detail).includes(find(n => n.props.class === 'calibration-button')), 'calibration belongs to the expanded settings')
    assert.equal(walk(root).filter(n => n.tag === 'strong' && n.text === layer.name).length, 1, 'the layer name is shown only once')
    assert.ok(!walk(detail).some(n => n.text === layer.name), 'settings do not duplicate the summary name')
    assert.ok(walk(detail).some(n => n.text === '图层设置'))
    toggle.props.onClick(); await nextTick()
    assert.equal(toggle.props['aria-expanded'], true)
    assert.notEqual(detail.style.display, 'none')
    assert.equal(second.style.display, 'none')
    for (const [aria, title] of [['上移模型名称', '上移'], ['下移模型名称', '下移'], ['从地图移除模型名称', '移除']]) {
      assert.ok(walk(label(aria)).some(n => n.text === title), `${title} has a visible text label`)
    }
    label('隐藏模型名称').props.onClick()
    label('定位模型名称').props.onClick()
    label('上移模型名称').props.onClick()
    label('模型名称不透明度').props.onInput({ target: { value: '0.65' } })
    label('道路显示到 模型名称').props.onChange({ target: { value: '3' } })
    find(n => n.props.class === 'calibration-button').props.onClick()
    label('从地图移除模型名称').props.onClick()
    toggle.props.onClick(); await nextTick()
    assert.equal(detail.style.display, 'none')
    label('查看模型名称详情').props.onClick(); await nextTick()
    assert.notEqual(detail.style.display, 'none')
    assert.deepEqual(events, [['toggle'], ['locate'], ['move', -1], ['opacity', 0.65], ['roadMaxLevel', 3], ['calibrate'], ['remove']])
  } finally { app.unmount() }
})
