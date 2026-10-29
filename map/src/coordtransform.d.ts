declare module 'coordtransform' {
  const coordtransform: {
    gcj02towgs84(longitude: number, latitude: number): [number, number]
  }
  export default coordtransform
}
