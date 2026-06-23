import { useTranslation } from 'react-i18next'
import type { EngineEvent } from '../types/engine'
import { formatDuration, formatPercent } from '../utils/trafficFormat'

const DISPATCH_COLORS: Record<string, string> = {
  HOLD_DISPATCH: 'var(--color-verdict-anomaly)',
  CAUTION: 'var(--color-verdict-watch)',
  MONITOR: 'var(--color-verdict-calm)',
}

interface AlertCardProps {
  event: EngineEvent
  isSelected: boolean
  onSelect: () => void
}

export function AlertCard({ event, isSelected, onSelect }: AlertCardProps) {
  const { t } = useTranslation()
  const metrics = event.details.current_metrics
  const dispatchColor = DISPATCH_COLORS[event.dispatch_impact] ?? DISPATCH_COLORS.MONITOR

  return (
    <article
      className={`corridor-card corridor-card--alert${isSelected ? ' corridor-card--expanded corridor-card--selected' : ''}`}
    >
      <button
        type="button"
        className="corridor-card__trigger"
        onClick={onSelect}
        aria-expanded={isSelected}
      >
        <div className="corridor-card__header">
          <span className="corridor-card__name">{event.roadSegment}</span>
          <span className="corridor-card__meta">
            <span className="corridor-card__severity">{event.severity}</span>
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
                <dt>{t('corridor.ztmCongestion')}</dt>
                <dd>{formatPercent(metrics.congestion_ratio)}</dd>
              </div>
            </dl>
          </section>

          {event.details.top_incident_causes.length > 0 ? (
            <section className="corridor-card__section">
              <h4 className="corridor-card__section-title">{t('corridor.incidentCauses')}</h4>
              <ul className="corridor-card__causes">
                {event.details.top_incident_causes.map((cause) => (
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
