import { useTranslation } from 'react-i18next'
import type { CorridorSnapshot, DelayForecastItem, EngineEvent } from '../types/engine'
import { formatPercent } from '../utils/trafficFormat'

interface CorridorCardProps {
  snapshot: CorridorSnapshot
  event?: EngineEvent
  forecasts?: DelayForecastItem[]
  isSelected: boolean
  onSelect: () => void
}

const FORECAST_BADGES = [15, 30, 60] as const

function methodLabelKey(method: DelayForecastItem['method']): string {
  return `engine.forecast.method.${method}`
}

export function CorridorCard({ snapshot, event, forecasts, isSelected, onSelect }: CorridorCardProps) {
  const { t } = useTranslation()
  const metrics = snapshot.metrics
  const severity = event?.severity ?? 0
  const forecastByHorizon = new Map(
    (forecasts ?? []).map((item) => [item.horizon_minutes, item]),
  )

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

      {forecasts && forecasts.length > 0 ? (
        <div className="corridor-card__forecasts" aria-label={t('engine.forecast.title')}>
          {FORECAST_BADGES.map((horizon) => {
            const item = forecastByHorizon.get(horizon)
            if (!item) {
              return null
            }
            return (
              <span
                key={horizon}
                className={`corridor-card__forecast corridor-card__forecast--${item.method}`}
                title={t(methodLabelKey(item.method))}
              >
                <span className="corridor-card__forecast-horizon">
                  {t('engine.forecast.inMinutes', { count: horizon })}
                </span>
                <span className="corridor-card__forecast-delay">
                  {item.predicted_delay_sec}s
                </span>
              </span>
            )
          })}
        </div>
      ) : null}

      {event ? (
        <p className="corridor-card__event-type">{event.eventType}</p>
      ) : null}
    </button>
  )
}
