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

export const MAP_BOUNDS = {
  minLat: 53,
  maxLat: 55.5,
  minLon: 13,
  maxLon: 20,
}
