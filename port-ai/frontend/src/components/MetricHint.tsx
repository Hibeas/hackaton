import { useEffect, useId, useRef, useState, type ReactNode } from 'react'
import { useTranslation } from 'react-i18next'

export type MetricHelpKey = 'totalDelay' | 'maxDelay' | 'forecast' | 'stress60min'

interface MetricHintProps {
  metric: MetricHelpKey
}

export function MetricHint({ metric }: MetricHintProps) {
  const { t } = useTranslation()
  const tooltipId = useId()
  const [pinned, setPinned] = useState(false)
  const rootRef = useRef<HTMLSpanElement>(null)

  useEffect(() => {
    if (!pinned) {
      return undefined
    }
    const onPointerDown = (event: MouseEvent) => {
      if (!rootRef.current?.contains(event.target as Node)) {
        setPinned(false)
      }
    }
    document.addEventListener('mousedown', onPointerDown)
    return () => document.removeEventListener('mousedown', onPointerDown)
  }, [pinned])

  return (
    <span
      ref={rootRef}
      className={`metric-hint${pinned ? ' metric-hint--pinned' : ''}`}
    >
      <button
        type="button"
        className="metric-hint__btn"
        aria-expanded={pinned}
        aria-describedby={tooltipId}
        onClick={() => setPinned((current) => !current)}
      >
        <span aria-hidden>i</span>
        <span className="metric-hint__sr">{t(`metricsHelp.${metric}.title`)}</span>
      </button>
      <span id={tooltipId} role="tooltip" className="metric-hint__tooltip">
        <strong className="metric-hint__tooltip-title">{t(`metricsHelp.${metric}.title`)}</strong>
        <span>{t(`metricsHelp.${metric}.body`)}</span>
      </span>
    </span>
  )
}

export function MetricLabel({
  metric,
  children,
}: {
  metric: MetricHelpKey
  children: ReactNode
}) {
  return (
    <span className="metric-label">
      <span className="metric-label__text">{children}</span>
      <MetricHint metric={metric} />
    </span>
  )
}
