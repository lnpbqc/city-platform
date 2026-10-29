import { test } from 'node:test'
import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import { campuses, defaultCampus } from '../src/campuses.ts'
import { campusRegions, demoRegion } from '../src/regions.ts'
import { samples, samplesForCampus } from '../src/types.ts'

test('University Town is the default and both campus shortcuts use their own WGS84 targets', () => {
  assert.equal(defaultCampus.key, 'university-town')
  assert.equal(demoRegion.sampleKey, 'university-town')
  assert.equal(campusRegions.length, 2)
  assert.ok(demoRegion.label.includes('广州大学大学城校区'))
  const huangpu = campusRegions.find((region) => region.sampleKey === 'huangpu')
  assert.ok(huangpu.label.includes('广州大学黄埔校区'))
  assert.ok(huangpu.longitude > 113.568 && huangpu.longitude < 113.574)
  assert.ok(huangpu.latitude > 23.308 && huangpu.latitude < 23.313)
  assert.ok(Math.abs(demoRegion.longitude - huangpu.longitude) > 0.1)
  assert.deepEqual(samples, samplesForCampus('university-town'))
})

for (const campus of campuses)
  test(`${campus.key} samples, tiles transform and labels agree with the camera reference`, async () => {
    const records = samplesForCampus(campus.key)
    assert.equal(records.length, 5)
    assert.deepEqual(
      records.map((record) => record.id),
      samples.map((record) => record.id),
    )
    for (const record of records.filter(
      (record) => record.id !== 'campus-buildings',
    )) {
      const data = JSON.parse(
        await readFile(
          new URL(`../public${record.url}`, import.meta.url),
          'utf8',
        ),
      )
      assert.ok(record.source.includes(campus.shortName))
      if (record.type === 'geojson') {
        assert.equal(data.type, 'FeatureCollection')
        assert.ok(data.features.length)
        const visit = (coordinates) => {
          if (typeof coordinates[0] === 'number') {
            assert.ok(Math.abs(coordinates[0] - campus.longitude) < 0.004)
            assert.ok(Math.abs(coordinates[1] - campus.latitude) < 0.004)
          } else coordinates.forEach(visit)
        }
        for (const feature of data.features) {
          assert.equal(feature.properties['校区'], campus.name)
          assert.equal(feature.properties['数据性质'], '合成演示')
          visit(feature.geometry.coordinates)
        }
      } else {
        assert.equal(data.extras.campus, campus.name)
        assert.match(data.extras.source, /非真实校园建筑/)
        assert.equal(data.root.content.uri, 'buildings.glb')
        const lon = (campus.longitude * Math.PI) / 180
        const lat = (campus.latitude * Math.PI) / 180
        const n = 6378137 / Math.sqrt(1 - 6.69437999014e-3 * Math.sin(lat) ** 2)
        const expected = [
          (n + campus.altitude) * Math.cos(lat) * Math.cos(lon),
          (n + campus.altitude) * Math.cos(lat) * Math.sin(lon),
          (n * (1 - 6.69437999014e-3) + campus.altitude) * Math.sin(lat),
        ]
        data.root.transform
          .slice(12, 15)
          .forEach((value, index) =>
            assert.ok(Math.abs(value - expected[index]) < 0.001),
          )
      }
    }
  })

for (const campus of campuses)
  test(`${campus.key} white model preserves OSM footprints, attribution and height provenance`, async () => {
    const record = samplesForCampus(campus.key).find(
      (item) => item.id === 'campus-buildings',
    )
    assert.match(record.source, /OSM.*高度含估计/)
    const data = JSON.parse(
      await readFile(
        new URL(`../public${record.url}`, import.meta.url),
        'utf8',
      ),
    )
    assert.equal(data.attribution, 'https://www.openstreetmap.org/copyright')
    assert.match(data.license, /odbl/)
    assert.equal(data.features.length, campus.key === 'huangpu' ? 27 : 135)
    assert.equal(
      new Set(data.features.map((feature) => feature.id)).size,
      data.features.length,
    )
    let estimated = 0
    for (const feature of data.features) {
      const props = feature.properties
      assert.equal(props['校区'], campus.name)
      assert.equal(props['数据来源'], 'OpenStreetMap')
      assert.match(
        props['来源链接'],
        /^https:\/\/www.openstreetmap.org\/(way|relation)\/\d+$/,
      )
      const height = props.map_extrude_height_m
      assert.equal(typeof height, 'number')
      assert.ok(Number.isFinite(height) && height > 0 && height <= 1000)
      assert.equal(props['显示高度_米'], height)
      if (props['高度是否估计']) {
        estimated++
        assert.match(props['高度依据'], /估计/)
      } else assert.equal(props['高度依据'], 'OSM标注高度（未核验）')
      assert.ok(['Polygon', 'MultiPolygon'].includes(feature.geometry.type))
      const polygons =
        feature.geometry.type === 'Polygon'
          ? [feature.geometry.coordinates]
          : feature.geometry.coordinates
      for (const polygon of polygons) {
        for (const [index, ring] of polygon.entries()) {
          assert.ok(ring.length >= 4)
          assert.deepEqual(ring[0], ring.at(-1))
          let area = 0
          for (let i = 1; i < ring.length; i++)
            area += ring[i - 1][0] * ring[i][1] - ring[i][0] * ring[i - 1][1]
          assert.equal(area > 0, index === 0)
          for (const [longitude, latitude] of ring) {
            assert.ok(Math.abs(longitude - campus.longitude) < 0.02)
            assert.ok(Math.abs(latitude - campus.latitude) < 0.02)
          }
        }
      }
    }
    assert.equal(estimated, campus.key === 'huangpu' ? 27 : 83)
  })
