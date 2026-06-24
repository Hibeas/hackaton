import { useMemo } from 'react'
import type {
  BottlenecksResponse,
  CorridorsResponse,
  DelayForecastResponse,
  EngineEvent,
  EngineEventsResponse,
} from '../types/engine'
import type { DashboardMode } from '../constants/forecast'
import { UI_VISIBLE_PORT_IDS } from '../utils/corridorConfigHelpers'
import { ForecastPanel } from './dashboard/ForecastPanel'
import { OverviewPanel } from './dashboard/OverviewPanel'
import { BookingsPanel } from './dashboard/BookingsPanel'
import { useMyBookings } from '../hooks/useMyBookings'

interface DashboardSidebarProps {
  engineEvents: EngineEventsResponse | null
  corridors: CorridorsResponse | null
  bottlenecks: BottlenecksResponse | null
  delayForecasts: DelayForecastResponse | null | undefined
  dashboardMode: DashboardMode
  forecastHorizon: number
  selectedPortId: string
  selectedCorridorId: string | null
  onCorridorSelect: (corridorId: string) => void
  onSwitchToLive?: () => void
}

export function DashboardSidebar({
  engineEvents,
  corridors,
  bottlenecks,
  delayForecasts,
  dashboardMode,
  forecastHorizon,
  selectedPortId,
  selectedCorridorId,
  onCorridorSelect,
  onSwitchToLive,
}: DashboardSidebarProps) {
  const bookingsEnabled = dashboardMode === 'bookings'
  const { data: bookingsData, isLoading: bookingsLoading, error: bookingsError, refresh: refreshBookings } =
    useMyBookings(bookingsEnabled)
  const portCorridors = useMemo(
    () => (corridors?.corridors ?? []).filter((item) => item.port_id === selectedPortId),
    [corridors, selectedPortId],
  )

  const portEvents = useMemo(
    () =>
      [...(engineEvents?.events ?? [])]
        .filter((event) => event.port_id === selectedPortId)
        .sort((a, b) => b.severity - a.severity),
    [engineEvents, selectedPortId],
  )

  const eventsByCorridor = useMemo(() => {
    const map = new Map<string, EngineEvent>()
    for (const event of engineEvents?.events ?? []) {
      const existing = map.get(event.corridor_id)
      if (!existing || event.severity > existing.severity) {
        map.set(event.corridor_id, event)
      }
    }
    return map
  }, [engineEvents])

  const portBottlenecks = useMemo(
    () =>
      (bottlenecks?.bottlenecks ?? []).filter((item) =>
        UI_VISIBLE_PORT_IDS.has(item.port_id),
      ),
    [bottlenecks],
  )

  const sortedCorridors = useMemo(() => {
    return [...portCorridors].sort((a, b) => {
      const sevA = eventsByCorridor.get(a.corridor_id)?.severity ?? 0
      const sevB = eventsByCorridor.get(b.corridor_id)?.severity ?? 0
      return sevB - sevA
    })
  }, [portCorridors, eventsByCorridor])

  return (
    <aside className="dash-sidebar">
      <div className="dash-sidebar__body">
        {dashboardMode === 'forecast' ? (
          <ForecastPanel
            corridors={sortedCorridors}
            delayForecasts={delayForecasts}
            forecastHorizon={forecastHorizon}
            selectedCorridorId={selectedCorridorId}
            onCorridorSelect={onCorridorSelect}
          />
        ) : dashboardMode === 'bookings' ? (
          <BookingsPanel
            bookings={bookingsData?.bookings ?? []}
            total={bookingsData?.total ?? 0}
            isLoading={bookingsLoading}
            error={bookingsError}
            onRefresh={() => {
              void refreshBookings()
            }}
            onSelectCorridor={(corridorId) => {
              onCorridorSelect(corridorId)
              onSwitchToLive?.()
            }}
          />
        ) : (
          <OverviewPanel
            portEvents={portEvents}
            corridors={sortedCorridors}
            eventsByCorridor={eventsByCorridor}
            bottlenecks={portBottlenecks.filter((b) => b.port_id === selectedPortId)}
            selectedCorridorId={selectedCorridorId}
            onCorridorSelect={onCorridorSelect}
          />
        )}
      </div>
    </aside>
  )
}
