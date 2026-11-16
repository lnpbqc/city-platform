import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { test } from 'node:test'
import { stripTypeScriptTypes } from 'node:module'
import { compileScript, parse } from 'vue/compiler-sfc'
import { createSSRApp } from 'vue'
import { renderToString } from 'vue/server-renderer'

async function component(path) {
  const url = new URL(path, import.meta.url)
  const { descriptor } = parse(readFileSync(url, 'utf8'))
  const script = compileScript(descriptor, { id: path, inlineTemplate: true }).content
  const source = stripTypeScriptTypes(script, { mode: 'transform' })
    .replace(/^import (.*?) from ['"]([^'"]+)['"];?$/gm, (_line, names, specifier) => {
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
})
