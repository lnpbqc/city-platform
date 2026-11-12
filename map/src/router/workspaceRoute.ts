export type WorkspacePage = 'map' | 'data' | 'simulation'
export function readWorkspacePage(hash: string): WorkspacePage {
  return hash === '#/data' ? 'data' : hash === '#/simulation' ? 'simulation' : 'map'
}
