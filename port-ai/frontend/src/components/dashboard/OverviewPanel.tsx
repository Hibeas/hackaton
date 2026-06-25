import { useMemo } from 'react'
import { useTranslation } from 'react-i18next'
import type { PortConfig } from '../../constants/ports'
import type {
  BottleneckItem,
  BottlenecksResponse,
  CorridorSnapshot,
  CorridorsResponse,
  DelayForecastResponse,
  EngineEvent,
  EngineEventsResponse,
} from '../../types/engine'
import { BottleneckList } from '../BottleneckList'
import { AlertCard } from '../AlertCard'
import { CorridorCard } from '../CorridorCard'
import { PortComparePanel } from './PortComparePanel'
import { CorridorSlotSuggestion } from './CorridorSlotSuggestion'

interface OverviewPanelProps {
  ports: PortConfig[]
  portEvents: EngineEvent[]
  corridors: CorridorSnapshot[]
  eventsByCorridor: Map<string, EngineEvent>
  bottlenecks: BottleneckItem[]
  allBottlenecks: BottlenecksResponse | null
  allCorridors: CorridorsResponse | null
  engineEvents: EngineEventsResponse | null
  delayForecasts: DelayForecastResponse | null | undefined
  forecastHorizon: number
  selectedPortId: string
  selectedCorridorId: string | null
  selectedCorridorName: string | null
  onPortSelect: (portId: string) => void
  onCorridorSelect: (corridorId: string) => void
}

export function OverviewPanel({
  ports,
  portEvents,
  corridors,
  eventsByCorridor,
  bottlenecks,
  allBottlenecks,
  allCorridors,
  engineEvents,
  delayForecasts,
  forecastHorizon,
  selectedPortId,
  selectedCorridorId,
  selectedCorridorName,
  onPortSelect,
  onCorridorSelect,
}: OverviewPanelProps) {
  const { t } = useTranslation()

  const selectedSnapshot = useMemo(
    () => corridors.find((item) => item.corridor_id === selectedCorridorId) ?? null,
    [corridors, selectedCorridorId],
  )

  const selectedForecastDelay = useMemo(() => {
    if (!selectedCorridorId) {
      return null
    }
    const match = delayForecasts?.forecasts.find(
      (item) =>
        item.corridor_id === selectedCorridorId &&
        item.horizon_minutes === forecastHorizon,
    )
    return match?.predicted_delay_sec ?? null
  }, [delayForecasts, forecastHorizon, selectedCorridorId])

  const topBottlenecks = bottlenecks.slice(0, 4)
  const bottlenecksByCorridor = useMemo(() => {
    const map = new Map<string, BottleneckItem>()
    for (const item of bottlenecks) {
      map.set(item.corridor_id, item)
    }
    return map
  }, [bottlenecks])

  return (
    <div className="dash-panel">
      <PortComparePanel
        ports={ports}
        corridors={allCorridors}
        engineEvents={engineEvents}
        bottlenecks={allBottlenecks}
        delayForecasts={delayForecasts}
        forecastHorizon={forecastHorizon}
        selectedPortId={selectedPortId}
        onPortSelect={onPortSelect}
      />

      <section className="dash-section">
        <div className="dash-section__heading">
          <span className="dash-section__count">{corridors.length}</span>
          <h3 className="dash-section__title">{t('engine.corridors')}</h3>
        </div>
        <div className="corridor-list">
          {corridors.map((snapshot) => (
            <CorridorCard
              key={snapshot.corridor_id}
              snapshot={snapshot}
              event={eventsByCorridor.get(snapshot.corridor_id)}
              bottleneck={bottlenecksByCorridor.get(snapshot.corridor_id)}
              isSelected={selectedCorridorId === snapshot.corridor_id}
              onSelect={() => onCorridorSelect(snapshot.corridor_id)}
            />
          ))}
        </div>

        <CorridorSlotSuggestion
          corridorId={selectedCorridorId}
          corridorName={selectedCorridorName}
          predictedDelaySec={selectedForecastDelay}
          liveDelaySec={selectedSnapshot?.metrics.total_delay_sec ?? 0}
          hasActiveAlert={selectedCorridorId ? eventsByCorridor.has(selectedCorridorId) : false}
        />
      </section>

      <section className="dash-section">
        <div className="dash-section__heading">
          <span
            className={`dash-section__count${portEvents.length > 0 ? ' dash-section__count--alert' : ' dash-section__count--zero'}`}
          >
            {portEvents.length}
          </span>
          <h3 className="dash-section__title">{t('overview.kpiAlerts')}</h3>
        </div>
        <div className="corridor-list">
          {portEvents.length === 0 ? (
            <p className="dash-empty">{t('engine.noEvents')}</p>
          ) : (
            portEvents.map((event) => (
              <AlertCard
                key={event.id}
                event={event}
                isSelected={selectedCorridorId === event.corridor_id}
                onSelect={() => onCorridorSelect(event.corridor_id)}
              />
            ))
          )}
        </div>
      </section>

      {topBottlenecks.length > 0 ? (
        <section className="dash-section">
          <h3 className="dash-section__title">{t('engine.bottlenecks')}</h3>
          <BottleneckList
            items={topBottlenecks}
            selectedCorridorId={selectedCorridorId}
            onSelect={onCorridorSelect}
          />
        </section>
      ) : null}
    </div>
  )
}
