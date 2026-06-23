import { useTranslation } from 'react-i18next'
import type { EngineEvent } from '../types/engine'

const DISPATCH_COLORS: Record<string, string> = {
  HOLD_DISPATCH: 'var(--color-verdict-anomaly)',
  CAUTION: 'var(--color-verdict-watch)',
  MONITOR: 'var(--color-verdict-calm)',
}

interface EngineEventCardProps {
  event: EngineEvent
  isSelected: boolean
  onSelect: () => void
  variant?: 'full' | 'compact'
}

export function EngineEventCard({
  event,
  isSelected,
  onSelect,
  variant = 'full',
}: EngineEventCardProps) {
  const { t } = useTranslation()
  const dispatchColor = DISPATCH_COLORS[event.dispatch_impact] ?? DISPATCH_COLORS.MONITOR

  if (variant === 'compact') {
    return (
      <button
        type="button"
        className={`alert-row${isSelected ? ' alert-row--selected' : ''}`}
        onClick={onSelect}
      >
        <span className="alert-row__severity" style={{ color: dispatchColor }}>
          {event.severity}
        </span>
        <span className="alert-row__body">
          <strong>{event.roadSegment}</strong>
          <span>{event.eventType}</span>
        </span>
        <span
          className="alert-row__dispatch"
          style={{ backgroundColor: `${dispatchColor}22`, color: dispatchColor }}
        >
          {t(`engine.dispatchImpact.${event.dispatch_impact}`)}
        </span>
      </button>
    )
  }

  return (
    <article
      className={`engine-event${isSelected ? ' engine-event--selected' : ''}`}
      onClick={onSelect}
      onKeyDown={(keydown) => {
        if (keydown.key === 'Enter' || keydown.key === ' ') {
          onSelect()
        }
      }}
      role="button"
      tabIndex={0}
    >
      <header className="engine-event__header">
        <div>
          <h3>{event.roadSegment}</h3>
          <p className="engine-event__type">{event.eventType}</p>
        </div>
        <div className="engine-event__severity" style={{ borderColor: dispatchColor }}>
          <span className="engine-event__severity-value">{event.severity}</span>
          <span className="engine-event__severity-label">{t('engine.severity')}</span>
        </div>
      </header>

      <div className="severity-bar">
        <div
          className="severity-bar__fill"
          style={{ width: `${event.severity}%`, backgroundColor: dispatchColor }}
        />
      </div>

      <p className="engine-event__summary">{event.summary}</p>

      <dl className="engine-event__meta">
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
        <div>
          <dt>{t('engine.incidents')}</dt>
          <dd>{event.details.current_metrics.incident_count}</dd>
        </div>
        {event.geofence_type ? (
          <div>
            <dt>{t('geofence.label')}</dt>
            <dd>{t(`geofence.type.${event.geofence_type}`)}</dd>
          </div>
        ) : null}
      </dl>
    </article>
  )
}
