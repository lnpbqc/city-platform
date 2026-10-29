// DataV GeoAtlas's directory is used only for region names and approximate camera targets.
import { mkdir, writeFile } from 'node:fs/promises'
import { createHash } from 'node:crypto'
import coordtransform from 'coordtransform'

const source = 'https://geo.datav.aliyun.com/areas_v3/bound/all.json'
const response = await fetch(source, { signal: AbortSignal.timeout(30_000) })
if (!response.ok)
  throw new Error(`Region source returned HTTP ${response.status}`)
const original = await response.text()
const input = JSON.parse(original)
const regions = input
  .map((row) => {
    // The DataV directory follows GCJ-02; Taiwan's reference is not offset.
    const center = String(row.adcode).startsWith('71')
      ? [row.lng, row.lat]
      : coordtransform.gcj02towgs84(row.lng, row.lat)
    if (!row.name || !center.every(Number.isFinite))
      throw new Error(`Invalid region ${row.adcode}`)
    return {
      id: String(row.adcode),
      name: row.name,
      // DataV labels directly administered counties as "city"; do not create a fake city tier.
      level:
        row.level === 'city' && row.adcode % 100 !== 0 ? 'district' : row.level,
      parent: row.parent === null ? null : String(row.parent),
      longitude: +center[0].toFixed(6),
      latitude: +center[1].toFixed(6),
    }
  })
  .sort((a, b) => a.id.localeCompare(b.id))
const catalog = {
  source,
  retrievedAt: new Date().toISOString(),
  sourceSha256: createHash('sha256').update(original).digest('hex'),
  coordinateNote:
    'DataV GCJ-02 reference points converted to approximate WGS84 using coordtransform 2.1.2; Taiwan unchanged. Camera navigation only.',
  coverageNote:
    'The source provides only the province-level Taiwan entry; missing lower levels are not synthesized.',
  hierarchyNote:
    'Source city entries with a county code (last two digits non-zero) are normalized to district; parent codes are preserved.',
  regions,
}
const directory = new URL('../public/data/', import.meta.url)
await mkdir(directory, { recursive: true })
await writeFile(
  new URL('regions.json', directory),
  JSON.stringify(catalog) + '\n',
  'utf8',
)
console.log(
  `Saved ${regions.length} region reference points; source SHA256 ${catalog.sourceSha256}`,
)
