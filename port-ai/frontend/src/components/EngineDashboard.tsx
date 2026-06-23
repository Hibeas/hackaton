import { useMemo } from 'react'
import { useTranslation } from 'react-i18next'
import type { PortConfig } from '../constants/ports'
import type {
  BottlenecksResponse,
  CorridorsResponse,
  EngineEvent,
  EngineEventsResponse,
} from '../types/engine'
import { filterUiPorts, UI_VISIBLE_PORT_IDS } from '../utils/corridorConfigHelpers'
import { formatDateTime } from '../utils/trafficFormat'
import type { PortOperationsPayload } from '../types/portOps'
import { BottleneckList } from './BottleneckList'
import { CorridorCard } from './CorridorCard'
import { EngineEventCard } from './EngineEventCard'
import { PortOpsPanel } from './PortOpsPanel'
import { PortTabs } from './PortTabs'

interface EngineDashboardProps {
  ports: PortConfig[]
  engineEvents: EngineEventsResponse | null
  corridors: CorridorsResponse | null
  bottlenecks: BottlenecksResponse | null
  portOperations: PortOperationsPayload | null | undefined
  selectedPortId: string
  selectedCorridorId: string | null
  onPortSelect: (portId: string) => void
  onCorridorSelect: (corridorId: string) => void
}

export function EngineDashboard({
  ports,
  engineEvents,
  corridors,
  bottlenecks,
  portOperations,
  selectedPortId,
  selectedCorridorId,
  onPortSelect,
  onCorridorSelect,
}: EngineDashboardProps) {
  const { t, i18n } = useTranslation()

  const sortedPorts = useMemo(() => filterUiPorts(ports), [ports])

  const eventCounts = useMemo(() => {
    const counts: Record<string, number> = {}
    for (const port of sortedPorts) {
      counts[port.id] = 0
    }
    for (const event of engineEvents?.events ?? []) {
      counts[event.port_id] = (counts[event.port_id] ?? 0) + 1
    }
    return counts
  }, [engineEvents, sortedPorts])

  const portCorridors = useMemo(
    () => (corridors?.corridors ?? []).filter((item) => item.port_id === selectedPortId),
    [corridors, selectedPortId],
  )

  const portEvents = useMemo(
    () => (engineEvents?.events ?? []).filter((event) => event.port_id === selectedPortId),
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

  const selectedEvent = selectedCorridorId
    ? eventsByCorridor.get(selectedCorridorId)
    : portEvents[0]

  return (
    <aside className="sidebar sidebar--engine">
      <header className="sidebar__header">
        <h1>{t('engine.title')}</h1>
        <p>{t('engine.subtitle')}</p>
        {engineEvents?.evaluated_at ? (
          <p className="sidebar__meta">
            {t('engine.evaluatedAt')}: {formatDateTime(engineEvents.evaluated_at, i18n.language)}
          </p>
        ) : null}
        <p className="sidebar__meta">
          {t('engine.observations')}: {engineEvents?.observation_count ?? 0}
          {' · '}
          {t('engine.activeEvents')}: {engineEvents?.active_count ?? 0}
        </p>
      </header>

      <PortOpsPanel portOperations={portOperations} selectedPortId={selectedPortId} />

      <PortTabs
        ports={sortedPorts}
        selectedPortId={selectedPortId}
        onSelect={onPortSelect}
        eventCounts={eventCounts}
      />

      <section className="sidebar__section">
        <h2>{t('engine.corridors')}</h2>
        <div className="corridor-list">
          {portCorridors.map((snapshot) => (
            <CorridorCard
              key={snapshot.corridor_id}
              snapshot={snapshot}
              event={eventsByCorridor.get(snapshot.corridor_id)}
              isSelected={selectedCorridorId === snapshot.corridor_id}
              onSelect={() => onCorridorSelect(snapshot.corridor_id)}
            />
          ))}
        </div>
      </section>

      <section className="sidebar__section">
        <h2>{t('engine.events')}</h2>
        <div className="engine-event-list">
          {portEvents.length === 0 ? (
            <p className="sidebar__meta">{t('engine.noEvents')}</p>
          ) : (
            portEvents.map((event) => (
              <EngineEventCard
                key={event.id}
                event={event}
                isSelected={selectedCorridorId === event.corridor_id}
                onSelect={() => onCorridorSelect(event.corridor_id)}
              />
            ))
          )}
        </div>
      </section>

      {selectedEvent ? (
        <section className="sidebar__section sidebar__section--highlight">
          <h2>{t('engine.selectedEvent')}</h2>
          <EngineEventCard
            event={selectedEvent}
            isSelected
            onSelect={() => onCorridorSelect(selectedEvent.corridor_id)}
          />
        </section>
      ) : null}

      <section className="sidebar__section">
        <h2>{t('engine.bottlenecks')}</h2>
        <BottleneckList
          items={(bottlenecks?.bottlenecks ?? []).filter((item) =>
            UI_VISIBLE_PORT_IDS.has(item.port_id),
          )}
          selectedCorridorId={selectedCorridorId}
          onSelect={onCorridorSelect}
        />
      </section>
    </aside>
  )
}
