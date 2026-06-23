import type { TrafficStatus, Verdict } from '../types/traffic'

export const REFRESH_INTERVAL_MS = 30_000

export const TRAFFIC_STATUS_COLORS: Record<TrafficStatus, string> = {
  CRITICAL: 'var(--color-traffic-critical)',
  CONGESTION: 'var(--color-traffic-congestion)',
  CLEAR: 'var(--color-traffic-clear)',
}

export const VERDICT_COLORS: Record<Verdict, string> = {
  NORMAL: 'var(--color-verdict-normal)',
  ANOMALY: 'var(--color-verdict-anomaly)',
  WATCH: 'var(--color-verdict-watch)',
  CALM: 'var(--color-verdict-calm)',
}

export const MAP_DEFAULT_CENTER: [number, number] = [54.52, 18.53]
export const MAP_DEFAULT_ZOOM = 11

/** Quick map navigation targets per port region. */
export const MAP_REGION_VIEWS: Record<
  string,
  { center: [number, number]; zoom: number; labelKey: string }
> = {
  gdynia: { center: [54.52, 18.53], zoom: 13, labelKey: 'map.zoomGdynia' },
  gdansk: { center: [54.36, 18.66], zoom: 12, labelKey: 'map.zoomGdansk' },
  szczecin: { center: [53.43, 14.55], zoom: 12, labelKey: 'map.zoomSzczecin' },
  swinoujscie: { center: [53.91, 14.27], zoom: 13, labelKey: 'map.zoomSwinoujscie' },
}

export const MAP_REGION_ORDER = ['gdynia', 'gdansk', 'szczecin', 'swinoujscie'] as const

export const MAP_BOUNDS = {
  minLat: 53,
  maxLat: 55.5,
  minLon: 13,
  maxLon: 20,
}
