import { useEffect } from 'react'
import { useTranslation } from 'react-i18next'
import { useDispatchAudit } from '../hooks/useDispatchAudit'
import { formatDateTime } from '../utils/trafficFormat'
import type { DispatchAuditEntry } from '../types/tms'

interface DispatchAuditDrawerProps {
  open: boolean
  onClose: () => void
}

function eventLabelKey(event: string): string {
  return `dispatchAudit.events.${event}`
}

export function DispatchAuditDrawer({ open, onClose }: DispatchAuditDrawerProps) {
  const { t, i18n } = useTranslation()
  const { entries, isLoading, error, refresh } = useDispatchAudit(open)

  useEffect(() => {
    if (!open) {
      return undefined
    }
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        onClose()
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [open, onClose])

  if (!open) {
    return null
  }

  return (
    <div className="audit-drawer-backdrop" role="presentation" onClick={onClose}>
      <aside
        className="audit-drawer"
        role="dialog"
        aria-labelledby="audit-drawer-title"
        onClick={(event) => event.stopPropagation()}
      >
        <header className="audit-drawer__header">
          <div>
            <h2 id="audit-drawer-title">{t('dispatchAudit.title')}</h2>
            <p className="audit-drawer__subtitle">{t('dispatchAudit.subtitle')}</p>
          </div>
          <button type="button" className="audit-drawer__close" onClick={onClose} aria-label={t('dispatchAudit.close')}>
            ×
          </button>
        </header>

        <div className="audit-drawer__toolbar">
          <button type="button" className="audit-drawer__refresh" onClick={() => void refresh()}>
            {t('dispatchAudit.refresh')}
          </button>
        </div>

        {isLoading ? <p className="audit-drawer__empty">{t('dispatchAudit.loading')}</p> : null}
        {error ? <p className="audit-drawer__error">{t('dispatchAudit.error')}</p> : null}
        {!isLoading && !error && entries.length === 0 ? (
          <p className="audit-drawer__empty">{t('dispatchAudit.empty')}</p>
        ) : null}

        <ol className="audit-drawer__list">
          {entries.map((entry: DispatchAuditEntry, index: number) => {
            const label = t(eventLabelKey(entry.event), { defaultValue: entry.event })
            const corridor = typeof entry.corridor_id === 'string' ? entry.corridor_id : null
            const slotId = typeof entry.slot_id === 'string' ? entry.slot_id : null
            const phone = typeof entry.phone === 'string' ? entry.phone : null

            return (
              <li
                key={`${entry.at}-${index}`}
                className={`audit-drawer__item audit-drawer__item--${entry.event}`}
              >
                <time dateTime={entry.at}>{formatDateTime(entry.at, i18n.language)}</time>
                <strong>{label}</strong>
                <span className="audit-drawer__meta">
                  {[corridor, slotId, phone].filter(Boolean).join(' · ')}
                </span>
              </li>
            )
          })}
        </ol>
      </aside>
    </div>
  )
}
