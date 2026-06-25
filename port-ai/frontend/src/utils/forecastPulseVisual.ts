import type { PathOptions } from 'leaflet'
import type { CorridorPulseDetail, ForecastPulseSeverity } from './forecastPulseReport'

export type CauseCategory = 'accident' | 'congestion' | 'roadworks' | 'weather' | 'unknown'

const CAUSE_PALETTE: Record<CauseCategory, { bright: string; dim: string }> = {
  accident: { bright: '#dc2626', dim: '#991b1b' },
  congestion: { bright: '#ea580c', dim: '#facc15' },
  roadworks: { bright: '#ca8a04', dim: '#fde047' },
  weather: { bright: '#2563eb', dim: '#93c5fd' },
  unknown: { bright: '#dc2626', dim: '#ca8a04' },
}

const SEVERITY_INTERVAL_MS: Record<ForecastPulseSeverity, number> = {
  critical: 200,
  high: 250,
  medium: 350,
  low: 450,
}

const SEVERITY_WEIGHT: Record<ForecastPulseSeverity, number> = {
  critical: 5,
  high: 4,
  medium: 3.5,
  low: 3,
}

const SEVERITY_FILL_OPACITY: Record<ForecastPulseSeverity, { bright: number; dim: number }> = {
  critical: { bright: 0.45, dim: 0.3 },
  high: { bright: 0.38, dim: 0.28 },
  medium: { bright: 0.3, dim: 0.2 },
  low: { bright: 0.22, dim: 0.14 },
}

export function iconCategoryToCauseCategory(icon: number | null | undefined): CauseCategory {
  const value = icon ?? 0
  if (value === 1 || value === 8 || value === 14) {
    return 'accident'
  }
  if (value === 6) {
    return 'congestion'
  }
  if (value === 7 || value === 9) {
    return 'roadworks'
  }
  if (value === 2 || value === 3 || value === 4 || value === 5 || value === 10 || value === 11) {
    return 'weather'
  }
  return 'unknown'
}

export function getPulsePhaseInterval(severity: ForecastPulseSeverity): number {
  return SEVERITY_INTERVAL_MS[severity]
}

export function isPulseBright(pulse: CorridorPulseDetail, now: number): boolean {
  const interval = getPulsePhaseInterval(pulse.severity)
  const elapsed = now - pulse.startedAt
  return Math.floor(elapsed / interval) % 2 === 0
}

export function buildCorridorPulsePathOptions(
  pulse: CorridorPulseDetail,
  brightPhase: boolean,
): PathOptions {
  const palette = CAUSE_PALETTE[pulse.causeCategory]
  const opacity = SEVERITY_FILL_OPACITY[pulse.severity]
  const stroke = brightPhase ? palette.bright : palette.dim
  const fill = brightPhase ? palette.bright : palette.dim

  return {
    color: stroke,
    weight: SEVERITY_WEIGHT[pulse.severity],
    fillColor: fill,
    fillOpacity: brightPhase ? opacity.bright : opacity.dim,
    dashArray: pulse.kind === 'proactive' ? '10 6' : undefined,
  }
}

export function causeCategoryChipClass(category: CauseCategory): string {
  return `forecast-pulse-popup__chip forecast-pulse-popup__chip--cause-${category}`
}

export const LEGEND_CAUSE_CATEGORIES: CauseCategory[] = [
  'accident',
  'congestion',
  'roadworks',
  'weather',
]

export function causeLegendDotColor(category: CauseCategory): string {
  return CAUSE_PALETTE[category].bright
}
