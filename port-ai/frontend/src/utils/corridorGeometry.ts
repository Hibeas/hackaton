import type { CorridorBbox } from '../constants/ports'

export type LatLng = [number, number]

export function bboxFromPoints(points: LatLng[]): CorridorBbox | null {
  if (points.length === 0) {
    return null
  }
  const lats = points.map((point) => point[0])
  const lons = points.map((point) => point[1])
  return {
    min_lat: roundCoord(Math.min(...lats)),
    max_lat: roundCoord(Math.max(...lats)),
    min_lon: roundCoord(Math.min(...lons)),
    max_lon: roundCoord(Math.max(...lons)),
  }
}

export function bboxToPolygon(bbox: CorridorBbox): LatLng[] {
  return [
    [bbox.min_lat, bbox.min_lon],
    [bbox.min_lat, bbox.max_lon],
    [bbox.max_lat, bbox.max_lon],
    [bbox.max_lat, bbox.min_lon],
  ]
}

export function roundCoord(value: number): number {
  return Math.round(value * 1_000_000) / 1_000_000
}

export function formatGeometrySnippet(
  corridorId: string,
  bbox: CorridorBbox,
  polygon: LatLng[],
): string {
  const payload = {
    id: corridorId,
    bbox,
    polygon: polygon.map(([lat, lon]) => [roundCoord(lat), roundCoord(lon)]),
  }
  return JSON.stringify(payload, null, 2)
}
