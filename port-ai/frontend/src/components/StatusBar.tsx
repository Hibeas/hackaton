import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import type { MapPulseAnnouncement } from '../hooks/useCorridorMapPulse'

interface StatusBarProps {
  primaryCount: number
  contextCount: number
  engineEventCount: number
  dataAgeSeconds: number | null
  lastUpdatedAt: number | null
  refreshIntervalMs: number
  isLoading: boolean
  error: string | null
  crowdDemoActive?: boolean
  crowdCorridorName?: string | null
  pulseAnnouncement?: MapPulseAnnouncement | null
  onOpenAudit?: () => void
}

export function StatusBar({
  primaryCount,
  contextCount,
  engineEventCount,
  dataAgeSeconds,
  lastUpdatedAt,
  refreshIntervalMs,
  isLoading,
  error,
  crowdDemoActive = false,
  crowdCorridorName = null,
  pulseAnnouncement = null,
  onOpenAudit,
}: StatusBarProps) {
  const { t } = useTranslation()
  const [nextRefreshSeconds, setNextRefreshSeconds] = useState(0)

  useEffect(() => {
    const updateCountdown = () => {
      if (!lastUpdatedAt) {
        setNextRefreshSeconds(Math.ceil(refreshIntervalMs / 1000))
        return
      }
      const elapsed = Date.now() - lastUpdatedAt
      const remaining = Math.max(0, refreshIntervalMs - elapsed)
      setNextRefreshSeconds(Math.ceil(remaining / 1000))
    }

    updateCountdown()
    const tickId = window.setInterval(updateCountdown, 1000)
    return () => window.clearInterval(tickId)
  }, [lastUpdatedAt, refreshIntervalMs])

  if (error) {
    return (
      <footer className="status-bar status-bar--error">
        <span className="status-bar__item">{t('status.error')}</span>
      </footer>
    )
  }

  return (
    <footer className="status-bar">
      <span className="status-bar__sr" aria-live="polite" aria-atomic="true">
        {pulseAnnouncement
          ? t(`map.pulse.${pulseAnnouncement.kind}`, {
              corridor: pulseAnnouncement.corridorName,
            })
          : ''}
      </span>
      <span className={`status-bar__item${isLoading ? ' status-bar__item--pulse' : ''}`}>
        {crowdDemoActive
          ? t('status.crowdDemo', { corridor: crowdCorridorName ?? '—' })
          : isLoading
            ? t('status.loading')
            : t('status.live')}
      </span>
      <span className="status-bar__divider" />
      <span className="status-bar__item">
        {t('status.engineEvents')}: <strong>{engineEventCount}</strong>
      </span>
      <span className="status-bar__item">
        TomTom: <strong>{primaryCount}</strong>
      </span>
      <span className="status-bar__item">
        ZTM: <strong>{contextCount}</strong>
      </span>
      {dataAgeSeconds !== null ? (
        <>
          <span className="status-bar__divider" />
          <span className="status-bar__item">
            {t('status.dataAge')}: {t('status.seconds', { count: Math.round(dataAgeSeconds) })}
          </span>
        </>
      ) : null}
      <span className="status-bar__spacer" />
      {onOpenAudit ? (
        <button type="button" className="status-bar__audit-btn" onClick={onOpenAudit}>
          {t('dispatchAudit.openButton')}
        </button>
      ) : null}
      <span className="status-bar__item status-bar__item--muted">
        {t('status.nextRefresh')}: {t('status.seconds', { count: nextRefreshSeconds })}
      </span>
    </footer>
  )
}
