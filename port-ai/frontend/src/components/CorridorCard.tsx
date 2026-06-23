import { useTranslation } from 'react-i18next'
import type { CorridorSnapshot, EngineEvent } from '../types/engine'
import { formatPercent } from '../utils/trafficFormat'

interface CorridorCardProps {
  snapshot: CorridorSnapshot
  event?: EngineEvent
  isSelected: boolean
  onSelect: () => void
}

export function CorridorCard({ snapshot, event, isSelected, onSelect }: CorridorCardProps) {
  const { t } = useTranslation()
  const metrics = snapshot.metrics
  const severity = event?.severity ?? 0

  return (
    <button
      type="button"
      className={`corridor-card${isSelected ? ' corridor-card--selected' : ''}${event ? ' corridor-card--alert' : ''}`}
      onClick={onSelect}
    >
      <div className="corridor-card__header">
        <span className="corridor-card__name">{snapshot.corridor_name}</span>
        <span className="corridor-card__meta">
          {snapshot.geofence_type ? (
            <span className="corridor-card__type" title={t(`geofence.type.${snapshot.geofence_type}`)}>
              {t(`geofence.typeShort.${snapshot.geofence_type}`)}
            </span>
          ) : null}
          {snapshot.business_priority ? (
            <span
              className={`corridor-card__priority corridor-card__priority--${snapshot.business_priority.toLowerCase()}`}
            >
              {snapshot.business_priority}
            </span>
          ) : null}
          {snapshot.logistics_weight !== undefined ? (
            <span className="corridor-card__weight" title={t('engine.logisticsWeight')}>
              W{snapshot.logistics_weight}
            </span>
          ) : null}
          {event ? (
            <span className="corridor-card__severity">{severity}</span>
          ) : (
            <span className="corridor-card__ok">{t('engine.clear')}</span>
          )}
        </span>
      </div>

      <div className="corridor-card__metrics">
        <span>{metrics.incident_count} {t('engine.incidentsShort')}</span>
        <span>{metrics.total_delay_sec}s {t('engine.delayShort')}</span>
        {metrics.avg_speed_kmh !== null ? (
          <span>{Math.round(metrics.avg_speed_kmh)} km/h</span>
        ) : null}
        {metrics.congestion_ratio !== null ? (
          <span>ZTM {formatPercent(metrics.congestion_ratio)}</span>
        ) : null}
      </div>

      {event ? (
        <p className="corridor-card__event-type">{event.eventType}</p>
      ) : null}
    </button>
  )
}
