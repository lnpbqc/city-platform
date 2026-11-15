import { Cartesian3, Matrix3, Matrix4, Transforms } from 'cesium'
import type { TilesCalibrationOffsets } from './tilesCalibrationTypes.ts'

export function calibrationFrame(pivot: Cartesian3) {
  const frame = Transforms.eastNorthUpToFixedFrame(pivot)
  return { frame, inverse: Matrix4.inverseTransformation(frame, new Matrix4()) }
}

export function calibrationMatrix(
  coordinates: ReturnType<typeof calibrationFrame>, baseline: Matrix4, offsets: TilesCalibrationOffsets,
): Matrix4 | null {
  if (!Object.values(offsets).every(Number.isFinite)) return null
  const { east, north, up, yaw, pitch, roll } = offsets
  if (!east && !north && !up && !yaw && !pitch && !roll) return Matrix4.clone(baseline)
  // ENU frame: north is +Y. Positive yaw turns clockwise when looking down.
  const radians = Math.PI / 180
  const rotation = Matrix3.fromRotationZ(-yaw * radians)
  Matrix3.multiply(rotation, Matrix3.fromRotationX(pitch * radians), rotation)
  Matrix3.multiply(rotation, Matrix3.fromRotationY(roll * radians), rotation)
  const adjustment = Matrix4.fromRotationTranslation(rotation, new Cartesian3(east, north, up))
  Matrix4.multiply(coordinates.frame, adjustment, adjustment)
  Matrix4.multiply(adjustment, coordinates.inverse, adjustment)
  return Matrix4.multiply(adjustment, baseline, adjustment)
}
