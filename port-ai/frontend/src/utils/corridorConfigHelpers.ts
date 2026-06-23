import type { CorridorBbox, CorridorConfig, LatLng, PortConfig } from '../constants/ports'
import { bboxFromPoints } from './corridorGeometry'

export const PORT_DISPLAY_ORDER = ['gdynia', 'gdansk', 'szczecin', 'swinoujscie'] as const

/** Ports shown in dashboard / editor. */
export const UI_VISIBLE_PORT_IDS = new Set<string>(['gdynia', 'gdansk', 'szczecin', 'swinoujscie'])

export function sortPorts(ports: PortConfig[]): PortConfig[] {
  return [...ports].sort(
    (left, right) =>
      PORT_DISPLAY_ORDER.indexOf(left.id as (typeof PORT_DISPLAY_ORDER)[number]) -
      PORT_DISPLAY_ORDER.indexOf(right.id as (typeof PORT_DISPLAY_ORDER)[number]),
  )
}

export function filterUiPorts(ports: PortConfig[]): PortConfig[] {
  return sortPorts(ports.filter((port) => UI_VISIBLE_PORT_IDS.has(port.id)))
}

export function findCorridor(
  ports: PortConfig[] | undefined,
  corridorId: string,
): CorridorConfig | undefined {
  if (!ports) {
    return undefined
  }
  for (const port of ports) {
    const corridor = port.corridors.find((item) => item.id === corridorId)
    if (corridor) {
      return corridor
    }
  }
  return undefined
}

export function findPort(ports: PortConfig[] | undefined, portId: string): PortConfig | undefined {
  return ports?.find((port) => port.id === portId)
}

/** Effective map bounds — saved polygon envelope or bbox. */
export function corridorMapBounds(corridor: CorridorConfig): CorridorBbox {
  if (corridor.polygon && corridor.polygon.length >= 3) {
    return bboxFromPoints(corridor.polygon) ?? corridor.bbox
  }
  return corridor.bbox
}

export function portMapBounds(port: PortConfig): CorridorBbox | null {
  if (port.corridors.length === 0) {
    return null
  }
  const boxes = port.corridors.map((corridor) => corridorMapBounds(corridor))
  return {
    min_lat: Math.min(...boxes.map((box) => box.min_lat)),
    max_lat: Math.max(...boxes.map((box) => box.max_lat)),
    min_lon: Math.min(...boxes.map((box) => box.min_lon)),
    max_lon: Math.max(...boxes.map((box) => box.max_lon)),
  }
}

export function resolveFocusGeometry(
  ports: PortConfig[] | undefined,
  selectedPortId: string,
  selectedCorridorId: string | null,
): { bbox: CorridorBbox | null; polygon: LatLng[] | null } {
  if (!ports) {
    return { bbox: null, polygon: null }
  }

  if (selectedCorridorId) {
    const corridor = findCorridor(ports, selectedCorridorId)
    if (!corridor) {
      return { bbox: null, polygon: null }
    }
    return {
      bbox: corridorMapBounds(corridor),
      polygon: corridor.polygon && corridor.polygon.length >= 3 ? corridor.polygon : null,
    }
  }

  const port = findPort(ports, selectedPortId)
  return {
    bbox: port ? portMapBounds(port) : null,
    polygon: null,
  }
}
