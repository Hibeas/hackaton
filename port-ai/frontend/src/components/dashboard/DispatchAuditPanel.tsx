import { useTranslation } from 'react-i18next'
import { useDispatchAudit } from '../../hooks/useDispatchAudit'
import { formatDateTime } from '../../utils/trafficFormat'

interface DispatchAuditPanelProps {
  enabled?: boolean
}

function eventLabelKey(event: string): string {
  return `dispatchAudit.events.${event}`
}

export function DispatchAuditPanel({ enabled = true }: DispatchAuditPanelProps) {
  const { t, i18n } = useTranslation()
  const { entries, isLoading, error, refresh } = useDispatchAudit(enabled)

  return (
    <details className="dispatch-audit">
      <summary className="dispatch-audit__summary">
        {t('dispatchAudit.title')}
        {entries.length > 0 ? (
          <span className="dispatch-audit__count">{entries.length}</span>
        ) : null}
      </summary>

      <div className="dispatch-audit__body">
        <div className="dispatch-audit__toolbar">
          <p className="dispatch-audit__hint">{t('dispatchAudit.hint')}</p>
          <button type="button" className="dispatch-audit__refresh" onClick={() => void refresh()}>
            {t('dispatchAudit.refresh')}
          </button>
        </div>

        {isLoading ? <p className="dispatch-audit__empty">{t('dispatchAudit.loading')}</p> : null}
        {error ? <p className="dispatch-audit__error">{t('dispatchAudit.error')}</p> : null}

        {!isLoading && !error && entries.length === 0 ? (
          <p className="dispatch-audit__empty">{t('dispatchAudit.empty')}</p>
        ) : null}

        <ol className="dispatch-audit__list">
          {entries.map((entry, index) => {
            const label = t(eventLabelKey(entry.event), {
              defaultValue: entry.event,
            })
            const corridor = typeof entry.corridor_id === 'string' ? entry.corridor_id : null
            const slotId = typeof entry.slot_id === 'string' ? entry.slot_id : null
            const phone = typeof entry.phone === 'string' ? entry.phone : null

            return (
              <li key={`${entry.at}-${index}`} className={`dispatch-audit__item dispatch-audit__item--${entry.event}`}>
                <time dateTime={entry.at}>{formatDateTime(entry.at, i18n.language)}</time>
                <strong>{label}</strong>
                <span className="dispatch-audit__meta">
                  {[corridor, slotId, phone].filter(Boolean).join(' · ')}
                </span>
              </li>
            )
          })}
        </ol>
      </div>
    </details>
  )
}
