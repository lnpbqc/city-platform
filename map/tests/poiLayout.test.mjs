import { test } from 'node:test'
import assert from 'node:assert/strict'
import { layoutPois } from '../src/map/poiLayout.ts'
import { poiCategory, poiIcon, poiName } from '../src/map/poi.ts'

const item = (id, x, y, text = id, weight = 0, priority = 0) => ({ id, x, y, text, weight, priority })
test('categories normalize Chinese and OSM tags and icons use distinct Lucide pictograms', () => {
  assert.equal(poiCategory({ amenity: 'restaurant' }), '餐饮')
  assert.equal(poiCategory({ amenity: 'school' }), '教育')
  assert.equal(poiCategory({ tourism: 'hotel' }), '住宿')
  assert.equal(poiCategory({ railway: 'station' }), '交通')
  assert.equal(poiCategory({ amenity: 'fire_station' }), '公共服务')
  assert.equal(poiCategory({ historic: 'memorial' }), '文旅')
  assert.equal(poiName({ name: '餐馆' }), '')
  assert.equal(poiName({ name: '1234' }), '')
  assert.equal(poiName({ name: '图书馆' }), '')
  assert.equal(poiName({ 'name:zh': '广州大学', name: 'Guangzhou University' }), '广州大学')
  assert.match(decodeURIComponent(poiIcon('餐饮')), /<path/)
  assert.notEqual(poiIcon('餐饮'), poiIcon('医疗'))
})
test('full text boxes compete with icons and labels; alternate anchors are stable', () => {
  const items = [item('main', 100, 100, '长名称', 10), item('other', 145, 100, '另一地点')]
  const result = layoutPois(items, new Map(), () => 60)
  assert.equal(result.find(i => i.id === 'main').labelVisible, true)
  assert.equal(result.find(i => i.id === 'other').visible, false)
  const left = layoutPois([item('one', 100, 100)], new Map([['one', 'left']]), () => 50)
  assert.equal(left[0].anchor, 'left')
})
test('explicit weight then semantic priority and stable ID choose colliding markers', () => {
  const items = [item('b', 10, 10, '乙', 0, 1), item('a', 10, 10, '甲', 0, 10)]
  assert.equal(layoutPois(items).find(i => i.visible).id, 'a')
  assert.deepEqual(layoutPois(items), layoutPois([...items].reverse()))
  assert.equal(layoutPois([items[1], item('weighted', 10, 10, '丙', 1)]).find(i => i.visible).id, 'weighted')
})
test('duplicate names nearby are suppressed and a colliding label degrades to an icon', () => {
  const duplicate = layoutPois([item('a', 0, 0, '同名'), item('b', 70, 0, '同名')])
  assert.equal(duplicate.filter(i => i.visible).length, 1)
  const positions = [item('right', 200, 100, '', 20), item('left', 0, 100, '', 20), item('top', 100, 65, '', 20), item('next', 100, 100, '长名称')]
  const result = layoutPois(positions, new Map(), () => 100)
  assert.equal(result.find(i => i.id === 'next').visible, true)
  assert.equal(result.find(i => i.id === 'next').labelVisible, false)
  assert.ok(result.every(i => ['right', 'left', 'top'].includes(i.anchor)))
})
