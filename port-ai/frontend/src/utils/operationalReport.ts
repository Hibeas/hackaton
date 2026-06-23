import type {
  BottlenecksResponse,
  CorridorsResponse,
  DelayForecastItem,
  DelayForecastResponse,
  EngineEvent,
  EngineEventsResponse,
} from '../types/engine'
import { formatDuration } from './trafficFormat'

export interface OperationalReport {
  corridorId: string
  corridorName: string
  portName: string
  hasAlert: boolean
  severity: number | null
  dispatchImpact: EngineEvent['dispatch_impact'] | null
  what: string
  why: string
  recommendation: string
  forecastHorizon: number | null
  predictedDelaySec: number | null
  incidentCount: number
  totalDelaySec: number
}

function pickAlert(events: EngineEvent[], corridorId: string): EngineEvent | null {
  const matches = events.filter((event) => event.corridor_id === corridorId)
  if (matches.length === 0) {
    return null
  }
  return [...matches].sort((a, b) => b.severity - a.severity)[0] ?? null
}

function pickForecast(
  forecasts: DelayForecastItem[] | undefined,
  corridorId: string,
  horizonMinutes: number,
): DelayForecastItem | null {
  if (!forecasts?.length) {
    return null
  }
  const exact = forecasts.find(
    (item) => item.corridor_id === corridorId && item.horizon_minutes === horizonMinutes,
  )
  if (exact) {
    return exact
  }
  const forCorridor = forecasts
    .filter((item) => item.corridor_id === corridorId)
    .sort((a, b) => a.horizon_minutes - b.horizon_minutes)
  return forCorridor[0] ?? null
}

function buildWhy(alert: EngineEvent | null, causes: string[]): string {
  const fromAlert = alert?.details.top_incident_causes ?? []
  const merged = [...new Set([...fromAlert, ...causes])].filter(Boolean)
  if (merged.length > 0) {
    return merged.slice(0, 4).join('; ')
  }
  if (alert?.reason_code) {
    return alert.reason_code
  }
  return ''
}

function buildRecommendation(
  alert: EngineEvent | null,
  hasAlert: boolean,
  predictedDelaySec: number | null,
  t: (key: string, opts?: Record<string, unknown>) => string,
): string {
  if (alert) {
    const impact = alert.dispatch_impact
    if (impact === 'HOLD_DISPATCH') {
      return t('map.report.recommendHold', {
        dispatch: t(`engine.dispatchImpact.${impact}`),
      })
    }
    if (impact === 'CAUTION') {
      return t('map.report.recommendCaution', {
        dispatch: t(`engine.dispatchImpact.${impact}`),
      })
    }
    return t('map.report.recommendMonitor', {
      dispatch: t(`engine.dispatchImpact.${impact}`),
    })
  }

  if (predictedDelaySec !== null && predictedDelaySec >= 600) {
    return t('map.report.recommendForecastHigh', {
      delay: formatDuration(predictedDelaySec),
    })
  }

  if (hasAlert) {
    return t('map.report.recommendMonitor', { dispatch: t('engine.dispatchImpact.MONITOR') })
  }

  return t('map.report.recommendClear')
}

export function buildOperationalReport(
  corridorId: string,
  options: {
    corridorName: string
    portName: string
    engineEvents: EngineEventsResponse | null
    corridors: CorridorsResponse | null
    bottlenecks: BottlenecksResponse | null
    delayForecasts: DelayForecastResponse | null | undefined
    forecastHorizon: number
    t: (key: string, opts?: Record<string, unknown>) => string
  },
): OperationalReport {
  const {
    corridorName,
    portName,
    engineEvents,
    corridors,
    bottlenecks,
    delayForecasts,
    forecastHorizon,
    t,
  } = options

  const alert = pickAlert(engineEvents?.events ?? [], corridorId)
  const snapshot = corridors?.corridors.find((item) => item.corridor_id === corridorId)
  const bottleneck = bottlenecks?.bottlenecks.find((item) => item.corridor_id === corridorId)
  const forecast = pickForecast(delayForecasts?.forecasts, corridorId, forecastHorizon)

  const metrics = alert?.details.current_metrics ?? snapshot?.metrics
  const incidentCount = metrics?.incident_count ?? 0
  const totalDelaySec = metrics?.total_delay_sec ?? 0
  const causes = metrics?.top_incident_causes ?? []
  const why = buildWhy(alert, causes)

  const hasAlert = alert !== null
  const predictedDelaySec = forecast?.predicted_delay_sec ?? null

  let what: string
  if (alert) {
    what = alert.summary
  } else if (totalDelaySec >= 120 || incidentCount >= 2) {
    what = t('map.report.whatElevated', {
      corridor: corridorName,
      incidents: incidentCount,
      delay: formatDuration(totalDelaySec),
    })
  } else {
    what = t('map.report.whatClear', { corridor: corridorName })
  }

  if (forecast && predictedDelaySec !== null) {
    what += ` ${t('map.report.forecastLine', {
      horizon: forecast.horizon_minutes,
      delay: formatDuration(predictedDelaySec),
    })}`
  }

  if (bottleneck && !alert && bottlenecks?.bottlenecks) {
    const rank = bottlenecks.bottlenecks.findIndex((item) => item.corridor_id === corridorId) + 1
    if (rank > 0) {
      what += ` ${t('map.report.bottleneckLine', {
        rank,
        stress: Math.round(bottleneck.stress_score),
      })}`
    }
  }

  const recommendation = buildRecommendation(alert, hasAlert, predictedDelaySec, t)

  return {
    corridorId,
    corridorName,
    portName,
    hasAlert,
    severity: alert?.severity ?? null,
    dispatchImpact: alert?.dispatch_impact ?? null,
    what,
    why: why || t('map.report.whyUnknown'),
    recommendation,
    forecastHorizon: forecast?.horizon_minutes ?? null,
    predictedDelaySec,
    incidentCount,
    totalDelaySec,
  }
}

export function resolveCorridorMapCenter(
  bbox: { min_lat: number; max_lat: number; min_lon: number; max_lon: number } | null | undefined,
  polygon?: [number, number][] | null,
): [number, number] | null {
  if (polygon && polygon.length >= 3) {
    const latSum = polygon.reduce((sum, point) => sum + point[0], 0)
    const lonSum = polygon.reduce((sum, point) => sum + point[1], 0)
    return [latSum / polygon.length, lonSum / polygon.length]
  }
  if (!bbox) {
    return null
  }
  return [(bbox.min_lat + bbox.max_lat) / 2, (bbox.min_lon + bbox.max_lon) / 2]
}
