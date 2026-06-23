import { useMemo } from 'react'
import { useTranslation } from 'react-i18next'
import type { BottleneckItem, CorridorSnapshot, EngineEvent } from '../../types/engine'
import { BottleneckList } from '../BottleneckList'
import { AlertCard } from '../AlertCard'
import { CorridorCard } from '../CorridorCard'

interface OverviewPanelProps {
  portEvents: EngineEvent[]
  corridors: CorridorSnapshot[]
  eventsByCorridor: Map<string, EngineEvent>
  bottlenecks: BottleneckItem[]
  selectedCorridorId: string | null
  onCorridorSelect: (corridorId: string) => void
}

export function OverviewPanel({
  portEvents,
  corridors,
  eventsByCorridor,
  bottlenecks,
  selectedCorridorId,
  onCorridorSelect,
}: OverviewPanelProps) {
  const { t } = useTranslation()

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
