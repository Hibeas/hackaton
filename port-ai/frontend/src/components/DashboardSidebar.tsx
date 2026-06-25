import { useEffect, useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'
import type { PortConfig } from '../constants/ports'
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

const STORAGE_KEY = 'port-ai-dash-sidebar-expanded'

interface DashboardSidebarProps {
  ports: PortConfig[]
  engineEvents: EngineEventsResponse | null
  corridors: CorridorsResponse | null
  bottlenecks: BottlenecksResponse | null
  delayForecasts: DelayForecastResponse | null | undefined
  dashboardMode: DashboardMode
  forecastHorizon: number
  selectedPortId: string
  selectedCorridorId: string | null
  selectedCorridorName: string | null
  onPortSelect: (portId: string) => void
  onCorridorSelect: (corridorId: string) => void
  onSwitchToLive?: () => void
  onExpandedChange?: (expanded: boolean) => void
}

function readExpandedPreference(): boolean {
  try {
    const stored = window.localStorage.getItem(STORAGE_KEY)
    if (stored !== null) {
      return stored === '1'
    }
  } catch {
    /* ignore */
  }
  return window.innerWidth >= 1280
}

function modeLabelKey(mode: DashboardMode): string {
  return `app.mode.${mode}`
}

export function DashboardSidebar({
  ports,
  engineEvents,
  corridors,
  bottlenecks,
  delayForecasts,
  dashboardMode,
  forecastHorizon,
  selectedPortId,
  selectedCorridorId,
  selectedCorridorName,
  onPortSelect,
  onCorridorSelect,
  onSwitchToLive,
  onExpandedChange,
}: DashboardSidebarProps) {
  const { t } = useTranslation()
  const [expanded, setExpanded] = useState(readExpandedPreference)

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

  const toggleExpanded = () => {
    setExpanded((current) => {
      const next = !current
      try {
        window.localStorage.setItem(STORAGE_KEY, next ? '1' : '0')
      } catch {
        /* ignore */
      }
      onExpandedChange?.(next)
      return next
    })
  }

  useEffect(() => {
    onExpandedChange?.(expanded)
  }, [expanded, onExpandedChange])

  const panelBody =
    dashboardMode === 'forecast' ? (
      <ForecastPanel
        corridors={sortedCorridors}
        delayForecasts={delayForecasts}
        forecastHorizon={forecastHorizon}
        selectedCorridorId={selectedCorridorId}
        selectedCorridorName={selectedCorridorName}
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
        ports={ports}
        portEvents={portEvents}
        corridors={sortedCorridors}
        eventsByCorridor={eventsByCorridor}
        bottlenecks={portBottlenecks.filter((b) => b.port_id === selectedPortId)}
        allBottlenecks={bottlenecks}
        allCorridors={corridors}
        engineEvents={engineEvents}
        delayForecasts={delayForecasts}
        forecastHorizon={forecastHorizon}
        selectedPortId={selectedPortId}
        selectedCorridorId={selectedCorridorId}
        selectedCorridorName={selectedCorridorName}
        onPortSelect={onPortSelect}
        onCorridorSelect={onCorridorSelect}
      />
    )

  return (
    <div className="dash-sidebar-wrap">
      <button
        type="button"
        className="dash-sidebar__toggle"
        onClick={toggleExpanded}
        aria-expanded={expanded}
        aria-label={expanded ? t('overview.collapsePanel') : t('overview.expandPanel')}
        title={expanded ? t('overview.collapsePanel') : t('overview.expandPanel')}
      >
        <span className="dash-sidebar__toggle-icon" aria-hidden>
          {expanded ? '›' : '‹'}
        </span>
      </button>

      <aside
        className={`dash-sidebar${expanded ? ' dash-sidebar--expanded' : ' dash-sidebar--collapsed'}`}
        aria-label={t('overview.panelTitle')}
      >
        {expanded ? (
          <div className="dash-sidebar__body">{panelBody}</div>
        ) : (
          <button
            type="button"
            className="dash-sidebar__rail"
            onClick={toggleExpanded}
            aria-label={t('overview.expandPanel')}
          >
            <span className="dash-sidebar__rail-label">{t('overview.panelTitle')}</span>
            <span className="dash-sidebar__rail-mode">{t(modeLabelKey(dashboardMode))}</span>
            {portEvents.length > 0 ? (
              <span className="dash-sidebar__rail-badge" title={t('overview.kpiAlerts')}>
                {portEvents.length}
              </span>
            ) : null}
            <span className="dash-sidebar__rail-count" title={t('engine.corridors')}>
              {sortedCorridors.length}
            </span>
          </button>
        )}
      </aside>
    </div>
  )
}
