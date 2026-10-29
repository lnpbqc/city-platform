const urlNamespace = new Uint8Array([0x6b, 0xa7, 0xb8, 0x11, 0x9d, 0xad, 0x11, 0xd1, 0x80, 0xb4, 0x00, 0xc0, 0x4f, 0xd4, 0x30, 0xc8])

export async function objectIdentity(assetId: string, version: string, featureIndex: number) {
  const name = new TextEncoder().encode(`city:objects:${assetId}@${version}:${featureIndex}`)
  const input = new Uint8Array(urlNamespace.length + name.length)
  input.set(urlNamespace)
  input.set(name, urlNamespace.length)
  const bytes = new Uint8Array(await crypto.subtle.digest('SHA-1', input)).slice(0, 16)
  bytes[6] = (bytes[6]! & 0x0f) | 0x50
  bytes[8] = (bytes[8]! & 0x3f) | 0x80
  const hex = Array.from(bytes, byte => byte.toString(16).padStart(2, '0')).join('')
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`
}

export async function identifyFeatures<T>(data: T, assetId: string, version: string): Promise<{ data: T; ids: string[] }> {
  const copy = structuredClone(data)
  const document = copy as { type?: string; features?: { id?: string | number }[] } | null
  if (document?.type !== 'FeatureCollection' || !Array.isArray(document.features)) return { data: copy, ids: [] }
  const ids = await Promise.all(document.features.map((_, index) => objectIdentity(assetId, version, index)))
  document.features.forEach((feature, index) => { feature.id = ids[index]! })
  return { data: copy, ids: [...ids].sort() }
}
