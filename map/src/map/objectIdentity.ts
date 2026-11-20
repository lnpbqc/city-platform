import { v5 as uuidv5 } from 'uuid'

export async function objectIdentity(assetId: string, version: string, featureIndex: number) {
  return uuidv5(`city:objects:${assetId}@${version}:${featureIndex}`, uuidv5.URL)
}

export async function identifyFeatures<T>(data: T, assetId: string, version: string): Promise<{ data: T; ids: string[] }> {
  const copy = structuredClone(data)
  const document = copy as { type?: string; features?: { id?: string | number }[] } | null
  if (document?.type !== 'FeatureCollection' || !Array.isArray(document.features)) return { data: copy, ids: [] }
  const ids = await Promise.all(document.features.map((_, index) => objectIdentity(assetId, version, index)))
  document.features.forEach((feature, index) => { feature.id = ids[index]! })
  return { data: copy, ids: [...ids].sort() }
}
