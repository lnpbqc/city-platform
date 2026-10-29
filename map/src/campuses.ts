import campusData from './data/campuses.json' with { type: 'json' }

export type CampusKey = 'university-town' | 'huangpu'
export const campuses = campusData as (Omit<
  (typeof campusData)[number],
  'key'
> & { key: CampusKey })[]
export const defaultCampus = campuses[0]!
