import type { PortConfig } from '../constants/ports'
import type {
  BottleneckItem,
  BottlenecksResponse,
  CorridorsResponse,
  DelayForecastResponse,
  EngineEvent,
  EngineEventsResponse,
} from '../types/engine'

export interface PortComparisonRow {
  portId: string
  portName: string
  corridorCount: number
  activeAlerts: number
  maxSeverity: number
  avgDelaySec: number
  maxDelaySec: number
  worstCorridorName: string | null
  avgForecastSec: number | null
  maxForecastSec: number | null
  bottleneckStress: number
  score: number
}

function round(value: number): number {
  return Math.round(value)
}

export function buildPortComparison(
  ports: PortConfig[],
  options: {
    corridors: CorridorsResponse | null
    engineEvents: EngineEventsResponse | null
    bottlenecks: BottlenecksResponse | null
    delayForecasts: DelayForecastResponse | null | undefined
    forecastHorizon: number
  },
): PortComparisonRow[] {
  const { corridors, engineEvents, bottlenecks, delayForecasts, forecastHorizon } = options
  const events = engineEvents?.events ?? []
  const snapshots = corridors?.corridors ?? []
  const bottleneckList = bottlenecks?.bottlenecks ?? []
  const forecasts = (delayForecasts?.forecasts ?? []).filter(
    (item) => item.horizon_minutes === forecastHorizon,
  )

  const rows = ports.map((port) => {
    const portCorridors = snapshots.filter((item) => item.port_id === port.id)
    const portEvents = events.filter((event) => event.port_id === port.id)
    const portBottlenecks = bottleneckList.filter((item) => item.port_id === port.id)

    const delays = portCorridors.map((item) => item.metrics.total_delay_sec)
    const avgDelaySec =
      delays.length > 0 ? delays.reduce((sum, value) => sum + value, 0) / delays.length : 0
    const maxDelaySec = delays.length > 0 ? Math.max(...delays) : 0

    let worstCorridorName: string | null = null
    if (portCorridors.length > 0) {
      const worst = [...portCorridors].sort(
        (a, b) => b.metrics.total_delay_sec - a.metrics.total_delay_sec,
      )[0]
      worstCorridorName = worst?.corridor_name ?? null
    }

    const portForecasts = forecasts.filter((item) => item.port_id === port.id)
    const forecastValues = portForecasts.map((item) => item.predicted_delay_sec)
    const avgForecastSec =
      forecastValues.length > 0
        ? forecastValues.reduce((sum, value) => sum + value, 0) / forecastValues.length
        : null
    const maxForecastSec = forecastValues.length > 0 ? Math.max(...forecastValues) : null

    const maxSeverity = portEvents.reduce(
      (max, event) => Math.max(max, event.severity),
      0,
    )
    const bottleneckStress =
      portBottlenecks.length > 0
        ? portBottlenecks.reduce((max, item) => Math.max(max, item.stress_score), 0)
        : 0

    const score =
      activeAlertsScore(portEvents) +
      maxDelaySec * 0.4 +
      (maxForecastSec ?? 0) * 0.35 +
      bottleneckStress * 2

    return {
      portId: port.id,
      portName: port.name,
      corridorCount: portCorridors.length,
      activeAlerts: portEvents.length,
      maxSeverity,
      avgDelaySec: round(avgDelaySec),
      maxDelaySec: round(maxDelaySec),
      worstCorridorName,
      avgForecastSec: avgForecastSec !== null ? round(avgForecastSec) : null,
      maxForecastSec: maxForecastSec !== null ? round(maxForecastSec) : null,
      bottleneckStress: round(bottleneckStress),
      score: round(score),
    }
  })

  return rows.sort((a, b) => b.score - a.score)
}

function activeAlertsScore(events: EngineEvent[]): number {
  return events.reduce((sum, event) => sum + event.severity * 25, 0)
}

export function worstBottleneckForPort(
  bottlenecks: BottleneckItem[] | undefined,
  portId: string,
): BottleneckItem | null {
  const items = (bottlenecks ?? []).filter((item) => item.port_id === portId)
  if (items.length === 0) {
    return null
  }
  return [...items].sort((a, b) => b.stress_score - a.stress_score)[0] ?? null
}
