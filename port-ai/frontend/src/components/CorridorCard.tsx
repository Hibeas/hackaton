import { useTranslation } from 'react-i18next'
import type { BottleneckItem, CorridorSnapshot, EngineEvent } from '../types/engine'
import { formatDateTime, formatDuration, formatPercent, formatRatio } from '../utils/trafficFormat'

const DISPATCH_COLORS: Record<string, string> = {
  HOLD_DISPATCH: 'var(--color-verdict-anomaly)',
  CAUTION: 'var(--color-verdict-watch)',
  MONITOR: 'var(--color-verdict-calm)',
}

interface CorridorCardProps {
  snapshot: CorridorSnapshot
  event?: EngineEvent
  bottleneck?: BottleneckItem
  isSelected: boolean
  onSelect: () => void
}

function formatSpeed(value: number | null | undefined): string {
  if (value === null || value === undefined) {
    return '—'
  }
  return `${Math.round(value)} km/h`
}

export function CorridorCard({
  snapshot,
  event,
  bottleneck,
  isSelected,
  onSelect,
}: CorridorCardProps) {
  const { t, i18n } = useTranslation()
  const metrics = snapshot.metrics
  const severity = event?.severity ?? 0
  const dispatchColor = event
    ? (DISPATCH_COLORS[event.dispatch_impact] ?? DISPATCH_COLORS.MONITOR)
    : undefined
  const incidentCauses = metrics.top_incident_causes?.length
    ? metrics.top_incident_causes
    : event?.details.top_incident_causes

  return (
    <article
      className={`corridor-card${isSelected ? ' corridor-card--expanded corridor-card--selected' : ''}${event ? ' corridor-card--alert' : ''}`}
    >
      <button
        type="button"
        className="corridor-card__trigger"
        onClick={onSelect}
        aria-expanded={isSelected}
      >
        <div className="corridor-card__header">
          <span className="corridor-card__name">{snapshot.corridor_name}</span>
          <span className="corridor-card__meta">
            {event ? (
              <span className="corridor-card__severity">{severity}</span>
            ) : (
              <span className="corridor-card__ok">{t('engine.clear')}</span>
            )}
            <span className="corridor-card__chevron" aria-hidden />
          </span>
        </div>

        <div className="corridor-card__metrics">
          <span>
            {formatDuration(metrics.total_delay_sec)} {t('engine.delayShort')}
          </span>
        </div>
      </button>

      {isSelected ? (
        <div className="corridor-card__panel">
          {event ? (
            <section className="corridor-card__section">
              <h4 className="corridor-card__section-title">{t('corridor.anomalySection')}</h4>
              <p className="corridor-card__event-headline">{event.eventType}</p>
              <div className="severity-bar corridor-card__severity-bar">
                <div
                  className="severity-bar__fill"
                  style={{ width: `${event.severity}%`, backgroundColor: dispatchColor }}
                />
              </div>
              <p className="corridor-card__summary">{event.summary}</p>
              <dl className="corridor-card__details">
                <div>
                  <dt>{t('engine.dispatch')}</dt>
                  <dd style={{ color: dispatchColor }}>
                    {t(`engine.dispatchImpact.${event.dispatch_impact}`)}
                  </dd>
                </div>
                <div>
                  <dt>{t('engine.confidence')}</dt>
                  <dd>{Math.round(event.confidence * 100)}%</dd>
                </div>
                <div>
                  <dt>{t('engine.portContext')}</dt>
                  <dd>{t(`engine.portContextLabel.${event.port_context}`)}</dd>
                </div>
                {event.details.window_minutes !== null ? (
                  <div>
                    <dt>{t('corridor.windowMinutes')}</dt>
                    <dd>{event.details.window_minutes} min</dd>
                  </div>
                ) : null}
                {event.details.duration_minutes !== null ? (
                  <div>
                    <dt>{t('corridor.durationMinutes')}</dt>
                    <dd>{event.details.duration_minutes} min</dd>
                  </div>
                ) : null}
                {event.details.delta_speed_pct !== null ? (
                  <div>
                    <dt>{t('corridor.deltaSpeed')}</dt>
                    <dd>{Math.round(event.details.delta_speed_pct)}%</dd>
                  </div>
                ) : null}
                {event.details.delta_delay_sec !== null ? (
                  <div>
                    <dt>{t('corridor.deltaDelay')}</dt>
                    <dd>{formatDuration(event.details.delta_delay_sec)}</dd>
                  </div>
                ) : null}
                {event.details.delta_congestion !== null ? (
                  <div>
                    <dt>{t('corridor.deltaCongestion')}</dt>
                    <dd>{formatPercent(event.details.delta_congestion)}</dd>
                  </div>
                ) : null}
              </dl>
            </section>
          ) : (
            <p className="corridor-card__calm">{t('corridor.noAnomaly')}</p>
          )}

          <section className="corridor-card__section">
            <h4 className="corridor-card__section-title">{t('corridor.metricsSection')}</h4>
            <dl className="corridor-card__details">
              <div>
                <dt>{t('engine.incidents')}</dt>
                <dd>{metrics.incident_count}</dd>
              </div>
              <div>
                <dt>{t('corridor.totalDelay')}</dt>
                <dd>{formatDuration(metrics.total_delay_sec)}</dd>
              </div>
              <div>
                <dt>{t('corridor.maxDelay')}</dt>
                <dd>{formatDuration(metrics.max_delay_sec)}</dd>
              </div>
              <div>
                <dt>{t('corridor.avgSpeed')}</dt>
                <dd>{formatSpeed(metrics.avg_speed_kmh)}</dd>
              </div>
              <div>
                <dt>{t('corridor.ztmCongestion')}</dt>
                <dd>{formatPercent(metrics.congestion_ratio)}</dd>
              </div>
              <div>
                <dt>{t('corridor.avgIntensity')}</dt>
                <dd>
                  {metrics.avg_intensity_vph !== null
                    ? `${Math.round(metrics.avg_intensity_vph)} vph`
                    : '—'}
                </dd>
              </div>
              <div>
                <dt>{t('corridor.demandRatio')}</dt>
                <dd>{formatRatio(metrics.demand_ratio)}</dd>
              </div>
            </dl>
          </section>

          {bottleneck ? (
            <section className="corridor-card__section">
              <h4 className="corridor-card__section-title">{t('corridor.bottleneckSection')}</h4>
              <dl className="corridor-card__details">
                <div>
                  <dt>{t('corridor.bottleneckWindow')}</dt>
                  <dd>{bottleneck.window_minutes} min</dd>
                </div>
                <div>
                  <dt>{t('corridor.avgDelayWindow')}</dt>
                  <dd>{formatDuration(bottleneck.avg_delay_sec)}</dd>
                </div>
                <div>
                  <dt>{t('corridor.minSpeedWindow')}</dt>
                  <dd>{formatSpeed(bottleneck.min_speed_kmh)}</dd>
                </div>
              </dl>
            </section>
          ) : null}

          <section className="corridor-card__section">
            <h4 className="corridor-card__section-title">{t('corridor.metaSection')}</h4>
            <dl className="corridor-card__details">
              {snapshot.geofence_type ? (
                <div>
                  <dt>{t('geofence.label')}</dt>
                  <dd>{t(`geofence.type.${snapshot.geofence_type}`)}</dd>
                </div>
              ) : null}
              {snapshot.city ? (
                <div>
                  <dt>{t('corridor.city')}</dt>
                  <dd>{snapshot.city}</dd>
                </div>
              ) : null}
              {snapshot.terminals.length > 0 ? (
                <div>
                  <dt>{t('corridor.terminals')}</dt>
                  <dd>{snapshot.terminals.join(', ')}</dd>
                </div>
              ) : null}
              {snapshot.impacts_port_access !== undefined ? (
                <div>
                  <dt>{t('corridor.portAccess')}</dt>
                  <dd>
                    {snapshot.impacts_port_access ? t('corridor.yes') : t('corridor.no')}
                  </dd>
                </div>
              ) : null}
              <div>
                <dt>{t('corridor.updatedAt')}</dt>
                <dd>{formatDateTime(snapshot.timestamp, i18n.language)}</dd>
              </div>
            </dl>
          </section>

          {incidentCauses && incidentCauses.length > 0 ? (
            <section className="corridor-card__section">
              <h4 className="corridor-card__section-title">{t('corridor.incidentCauses')}</h4>
              <ul className="corridor-card__causes">
                {incidentCauses.map((cause) => (
                  <li key={cause}>{cause}</li>
                ))}
              </ul>
            </section>
          ) : null}
        </div>
      ) : null}
    </article>
  )
}
