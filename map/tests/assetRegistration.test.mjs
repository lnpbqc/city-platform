import { test } from 'node:test'
import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import { parse } from 'vue/compiler-sfc'
import ts from 'typescript'

const { descriptor } = parse(await readFile(new URL('../src/App.vue', import.meta.url), 'utf8'))
const script = ts.createSourceFile('App.ts', descriptor.scriptSetup.content, ts.ScriptTarget.ES2022, true)
const declaration = script.statements.find((node) => ts.isFunctionDeclaration(node) && node.name?.text === 'registerAsset')
const javascript = ts.transpileModule(declaration.getText(script), {
  compilerOptions: { target: ts.ScriptTarget.ES2022 },
}).outputText

function setup() {
  const editing = { value: { id: 'old' } }, initial = { value: undefined }, showDialog = { value: false }
  const register = new Function('editing', 'initial', 'showDialog', `${javascript}; return registerAsset`)(editing, initial, showDialog)
  return { register, editing, initial, showDialog }
}

test('reusing an external asset retains its catalogue name and source', () => {
  const { register, initial, editing, showDialog } = setup()
  register({ id: 'external-asset', name: '外部模型', source: '测绘提供方', source_kind: 'external', original_name: null,
    type: '3dtiles', entry_url: 'https://example.invalid/tileset.json' })
  assert.equal(initial.value.name, '外部模型')
  assert.equal(initial.value.source, '测绘提供方')
  assert.equal(initial.value.url, 'https://example.invalid/tileset.json')
  assert.equal(editing.value, undefined)
  assert.equal(showDialog.value, true)
})

test('legacy local assets retain their original filename fallback', () => {
  const { register, initial } = setup()
  register({ id: 'local', original_name: 'campus.zip', type: '3dtiles', entry_url: '/data-files/local/tileset.json' })
  assert.equal(initial.value.name, 'campus')
  assert.equal(initial.value.source, '本地文件资产')
})
