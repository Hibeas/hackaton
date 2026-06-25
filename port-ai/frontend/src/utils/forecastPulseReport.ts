import type { PortConfig } from '../constants/ports'
import type {
  CorridorsResponse,
  DelayForecastConfidence,
  DelayForecastItem,
  DelayForecastMethod,
  DelayForecastResponse,
  EngineEventsResponse,
} from '../types/engine'
import { corridorMapBounds, findCorridor } from './corridorConfigHelpers'
import { resolveCorridorMapCenter } from './operationalReport'
import { iconCategoryToCauseCategory, type CauseCategory } from './forecastPulseVisual'
import {
  computeOperationalImportance,
  type OperationalImportance,
} from './operationalImportance'
import { importanceToPulseSeverity } from './importanceVisual'
import type { GeofenceType } from '../types/engine'

export type ForecastPulseSeverity = 'low' | 'medium' | 'high' | 'critical'

export interface CorridorPulseDetail {
  kind: 'proactive' | 'validated'
  corridorId: string
  corridorName: string
  portName: string
  position: [number, number]
  horizonMinutes: number
  predictedDelaySec: number
  currentDelaySec: number
  confidence: DelayForecastConfidence
  method: DelayForecastMethod
  cause: string | null
  causeCategory: CauseCategory
  operationalImportance: OperationalImportance
  geofenceType: GeofenceType
  impactsPortAccess: boolean
  terminals: string[]
  /** Visual blink tier derived from operationalImportance. */
  severity: ForecastPulseSeverity
  startedAt: number
}

function pickForecast(
  forecasts: DelayForecastItem[] | undefined,
  corridorId: string,
  horizonMinutes: number,
): DelayForecastItem | null {
  if (!forecasts?.length) {
    return null
  }
  return (
    forecasts.find(
      (item) => item.corridor_id === corridorId && item.horizon_minutes === horizonMinutes,
    ) ?? null
  )
}

function truncateText(text: string, maxLen: number): string {
  const trimmed = text.trim()
  if (trimmed.length <= maxLen) {
    return trimmed
  }
  return `${trimmed.slice(0, maxLen - 1).trim()}…`
}

function buildCauseText(
  causes: string[],
  kind: 'proactive' | 'validated',
  eventSummary: string | null,
): string | null {
  if (kind === 'validated' && eventSummary) {
    return truncateText(eventSummary, 52)
  }
  if (causes.length > 0) {
    return truncateText(causes[0], 52)
  }
  return null
}

export function buildCorridorPulseDetail(
  corridorId: string,
  kind: 'proactive' | 'validated',
  options: {
    ports: PortConfig[]
    delayForecasts: DelayForecastResponse | null | undefined
    corridors: CorridorsResponse | null
    engineEvents: EngineEventsResponse | null
    forecastHorizon: number
  },
): CorridorPulseDetail | null {
  const { ports, delayForecasts, corridors, engineEvents, forecastHorizon } = options
  const corridorConfig = findCorridor(ports, corridorId)
  if (!corridorConfig) {
    return null
  }

  const forecast = pickForecast(delayForecasts?.forecasts, corridorId, forecastHorizon)
  if (!forecast) {
    return null
  }

  const snapshot = corridors?.corridors.find((item) => item.corridor_id === corridorId)
  const port = ports.find((item) => item.corridors.some((c) => c.id === corridorId))
  const event = (engineEvents?.events ?? [])
    .filter((item) => item.corridor_id === corridorId)
    .sort((a, b) => b.severity - a.severity)[0]

  const causes = snapshot?.metrics.top_incident_causes ?? event?.details.top_incident_causes ?? []
  const iconCategory =
    snapshot?.metrics.primary_incident_category ??
    event?.details.current_metrics?.primary_incident_category ??
    null
  const position = resolveCorridorMapCenter(
    corridorMapBounds(corridorConfig),
    corridorConfig.polygon,
  )

  if (!position) {
    return null
  }

  const geofenceType =
    snapshot?.geofence_type ?? corridorConfig.geofence_type ?? 'APPROACH_CORRIDOR'
  const impactsPortAccess =
    snapshot?.impacts_port_access ?? corridorConfig.impacts_port_access ?? true
  const terminals = snapshot?.terminals ?? corridorConfig.terminals ?? []

  const operationalImportance = computeOperationalImportance({
    predictedDelaySec: forecast.predicted_delay_sec,
    currentDelaySec: snapshot?.metrics.total_delay_sec ?? 0,
    horizonMinutes: forecast.horizon_minutes,
    geofenceType,
    impactsPortAccess,
  })

  return {
    kind,
    corridorId,
    corridorName: snapshot?.corridor_name ?? corridorConfig.name,
    portName: snapshot?.port_name ?? port?.name ?? corridorId,
    position,
    horizonMinutes: forecast.horizon_minutes,
    predictedDelaySec: forecast.predicted_delay_sec,
    currentDelaySec: snapshot?.metrics.total_delay_sec ?? 0,
    confidence: forecast.confidence,
    method: forecast.method,
    cause: buildCauseText(causes, kind, event?.summary ?? null),
    causeCategory: iconCategoryToCauseCategory(iconCategory),
    operationalImportance,
    geofenceType,
    impactsPortAccess,
    terminals,
    severity: importanceToPulseSeverity(operationalImportance),
    startedAt: Date.now(),
  }
}
