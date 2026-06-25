import { useMemo } from 'react'
import { useTranslation } from 'react-i18next'
import type { PortConfig } from '../../constants/ports'
import type {
  BottlenecksResponse,
  CorridorsResponse,
  DelayForecastResponse,
  EngineEventsResponse,
} from '../../types/engine'
import { buildPortComparison } from '../../utils/portComparison'
import { MetricLabel } from '../MetricHint'

interface PortComparePanelProps {
  ports: PortConfig[]
  corridors: CorridorsResponse | null
  engineEvents: EngineEventsResponse | null
  bottlenecks: BottlenecksResponse | null
  delayForecasts: DelayForecastResponse | null | undefined
  forecastHorizon: number
  selectedPortId: string
  onPortSelect?: (portId: string) => void
}

export function PortComparePanel({
  ports,
  corridors,
  engineEvents,
  bottlenecks,
  delayForecasts,
  forecastHorizon,
  selectedPortId,
  onPortSelect,
}: PortComparePanelProps) {
  const { t } = useTranslation()

  const rows = useMemo(
    () =>
      buildPortComparison(ports, {
        corridors,
        engineEvents,
        bottlenecks,
        delayForecasts,
        forecastHorizon,
      }),
    [ports, corridors, engineEvents, bottlenecks, delayForecasts, forecastHorizon],
  )

  if (rows.length === 0) {
    return null
  }

  const leader = rows[0]

  return (
    <section className="dash-section port-compare">
      <div className="dash-section__heading">
        <span className="dash-section__count">{rows.length}</span>
        <h3 className="dash-section__title">{t('portCompare.title')}</h3>
      </div>
      <p className="port-compare__hint">
        {t('portCompare.leader', { port: leader.portName })}
      </p>
      <div className="port-compare__grid">
        {rows.map((row, index) => {
          const isSelected = row.portId === selectedPortId
          const isWorst = index === 0 && row.score > 0
          return (
            <button
              key={row.portId}
              type="button"
              className={`port-compare__card${isSelected ? ' port-compare__card--selected' : ''}${isWorst ? ' port-compare__card--hot' : ''}`}
              onClick={() => onPortSelect?.(row.portId)}
            >
              <header className="port-compare__card-head">
                <span className="port-compare__rank">#{index + 1}</span>
                <strong>{row.portName}</strong>
                {row.activeAlerts > 0 ? (
                  <span className="port-compare__alerts">{row.activeAlerts}</span>
                ) : null}
              </header>
              <dl className="port-compare__metrics">
                <div>
                  <dt>
                    <MetricLabel metric="maxDelay">{t('portCompare.maxDelay')}</MetricLabel>
                  </dt>
                  <dd>{row.maxDelaySec}s</dd>
                </div>
                <div>
                  <dt>
                    <MetricLabel metric="forecast">{t('portCompare.forecast')}</MetricLabel>
                  </dt>
                  <dd>{row.maxForecastSec !== null ? `${row.maxForecastSec}s` : '—'}</dd>
                </div>
                <div>
                  <dt>
                    <MetricLabel metric="stress60min">{t('portCompare.stress')}</MetricLabel>
                  </dt>
                  <dd>{row.bottleneckStress}</dd>
                </div>
              </dl>
              {row.worstCorridorName ? (
                <p className="port-compare__worst">{row.worstCorridorName}</p>
              ) : null}
            </button>
          )
        })}
      </div>
    </section>
  )
}
