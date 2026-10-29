import type { CameraState } from './mapNavigation'

type CameraView = { getCamera: () => CameraState; setCamera: (value: CameraState) => unknown }
const angleDistance = (left: number, right: number, period: number) => Math.abs((left - right + period * 1.5) % period - period / 2)
export function matchingCameras(left: CameraState, right: CameraState) {
  return left.scene_mode === right.scene_mode && angleDistance(left.longitude, right.longitude, 360) < 1e-7
    && Math.abs(left.latitude - right.latitude) < 1e-7 && Math.abs(left.height - right.height) < 0.01
    && (['heading', 'pitch', 'roll'] as const).every(key => angleDistance(left[key], right[key], Math.PI * 2) < 1e-7)
}
export function linkedCameras(getLeft: () => CameraView | undefined, getRight: () => CameraView | undefined) {
  let updating = false
  return (side: 'left' | 'right', camera: CameraState) => {
    const target = side === 'left' ? getRight() : getLeft()
    if (updating || !target || matchingCameras(target.getCamera(), camera)) return
    updating = true
    try { target.setCamera({ ...camera }) } finally { updating = false }
  }
}
