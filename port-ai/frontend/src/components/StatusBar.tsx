import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'

interface StatusBarProps {
  primaryCount: number
  contextCount: number
  engineEventCount: number
  dataAgeSeconds: number | null
  lastUpdatedAt: number | null
  refreshIntervalMs: number
  isLoading: boolean
  error: string | null
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

  const statusText = error
    ? t('status.error')
    : isLoading
      ? t('status.loading')
      : [
          `${t('status.engineEvents')}: ${engineEventCount}`,
          `${t('status.tomtomIncidents')}: ${primaryCount}`,
          `${t('status.ztmContext')}: ${contextCount}`,
          dataAgeSeconds !== null
            ? `${t('status.dataAge')}: ${t('status.seconds', { count: Math.round(dataAgeSeconds) })}`
            : null,
          `${t('status.nextRefresh')}: ${t('status.seconds', { count: nextRefreshSeconds })}`,
        ]
          .filter(Boolean)
          .join(' · ')

  return (
    <footer className={`status-bar${error ? ' status-bar--error' : ''}`}>
      {statusText}
    </footer>
  )
}
