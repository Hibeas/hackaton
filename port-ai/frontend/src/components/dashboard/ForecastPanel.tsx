import { useMemo } from 'react'
import { useTranslation } from 'react-i18next'
import type { CorridorSnapshot, DelayForecastItem, DelayForecastResponse } from '../../types/engine'
import { isMlOnlyHorizon } from '../../constants/forecast'
import { formatDateTime, formatDuration } from '../../utils/trafficFormat'

interface ForecastPanelProps {
  corridors: CorridorSnapshot[]
  delayForecasts: DelayForecastResponse | null | undefined
  forecastHorizon: number
  selectedCorridorId: string | null
  onCorridorSelect: (corridorId: string) => void
}

function methodLabelKey(method: DelayForecastItem['method']): string {
  return `engine.forecast.method.${method}`
}

function confidenceLabelKey(confidence: DelayForecastItem['confidence']): string {
  return `engine.forecast.confidence.${confidence}`
}

export function ForecastPanel({
  corridors,
  delayForecasts,
  forecastHorizon,
  selectedCorridorId,
  onCorridorSelect,
}: ForecastPanelProps) {
  const { t, i18n } = useTranslation()

  const forecastByCorridor = useMemo(() => {
    const map = new Map<string, DelayForecastItem>()
    for (const item of delayForecasts?.forecasts ?? []) {
      if (item.horizon_minutes === forecastHorizon) {
        map.set(item.corridor_id, item)
      }
    }
    return map
  }, [delayForecasts, forecastHorizon])

  const sortedCorridors = useMemo(() => {
    return [...corridors].sort((a, b) => {
      const predA = forecastByCorridor.get(a.corridor_id)?.predicted_delay_sec ?? -1
      const predB = forecastByCorridor.get(b.corridor_id)?.predicted_delay_sec ?? -1
      return predB - predA
    })
  }, [corridors, forecastByCorridor])

  const withForecastCount = sortedCorridors.filter((item) =>
    forecastByCorridor.has(item.corridor_id),
  ).length

  return (
    <div className="dash-panel">
      <section className="dash-section">
        <div className="dash-section__heading">
          <span className="dash-section__count">{withForecastCount}</span>
          <h3 className="dash-section__title">{t('engine.forecast.panelTitle')}</h3>
        </div>

        {delayForecasts?.generated_at ? (
          <p className="forecast-panel__meta">
            {t('engine.forecast.updatedAt')}:{' '}
            {formatDateTime(delayForecasts.generated_at, i18n.language)}
          </p>
        ) : null}

        <p className="forecast-panel__hint">
          {isMlOnlyHorizon(forecastHorizon)
            ? t('engine.forecast.panelHintMl', {
                horizon: t(
                  forecastHorizon === 120
                    ? 'engine.forecast.horizon2h'
                    : forecastHorizon === 180
                      ? 'engine.forecast.horizon3h'
                      : 'engine.forecast.horizonMinutes',
                  { count: forecastHorizon },
                ),
              })
            : t('engine.forecast.panelHint', { minutes: forecastHorizon })}
        </p>

        <div className="corridor-list">
          {sortedCorridors.length === 0 ? (
            <p className="dash-empty">{t('engine.forecast.noCorridors')}</p>
          ) : (
            sortedCorridors.map((snapshot) => {
              const forecast = forecastByCorridor.get(snapshot.corridor_id)
              const isSelected = selectedCorridorId === snapshot.corridor_id
              const currentDelay = snapshot.metrics.total_delay_sec

              return (
                <article
                  key={snapshot.corridor_id}
                  className={`forecast-card${isSelected ? ' forecast-card--selected' : ''}`}
                >
                  <button
                    type="button"
                    className="forecast-card__trigger"
                    onClick={() => onCorridorSelect(snapshot.corridor_id)}
                    aria-pressed={isSelected}
                  >
                    <div className="forecast-card__header">
                      <span className="forecast-card__name">{snapshot.corridor_name}</span>
                      {forecast ? (
                        <span className={`forecast-card__method forecast-card__method--${forecast.method}`}>
                          {t(`engine.forecast.methodShort.${forecast.method}`)}
                        </span>
                      ) : null}
                    </div>

                    <div className="forecast-card__metrics">
                      <span className="forecast-card__metric">
                        <span className="forecast-card__label">{t('engine.forecast.now')}</span>
                        <strong>{formatDuration(currentDelay)}</strong>
                      </span>
                      <span className="forecast-card__arrow" aria-hidden>
                        →
                      </span>
                      <span className="forecast-card__metric forecast-card__metric--predicted">
                        <span className="forecast-card__label">
                          {forecastHorizon === 120
                            ? t('engine.forecast.horizon2h')
                            : forecastHorizon === 180
                              ? t('engine.forecast.horizon3h')
                              : t('engine.forecast.inMinutes', { count: forecastHorizon })}
                        </span>
                        <strong>
                          {forecast
                            ? formatDuration(forecast.predicted_delay_sec)
                            : '—'}
                        </strong>
                      </span>
                    </div>

                    {forecast ? (
                      <div className="forecast-card__footer">
                        <span title={t(methodLabelKey(forecast.method))}>
                          {t(confidenceLabelKey(forecast.confidence))}
                        </span>
                        {forecast.samples_in_buffer !== undefined ? (
                          <span>
                            {t('engine.forecast.samples', { count: forecast.samples_in_buffer })}
                          </span>
                        ) : null}
                      </div>
                    ) : (
                      <p className="forecast-card__empty">{t('engine.forecast.noData')}</p>
                    )}
                  </button>
                </article>
              )
            })
          )}
        </div>
      </section>

      {delayForecasts ? (
        <section className="dash-section forecast-panel__status">
          <h3 className="dash-section__title">{t('engine.forecast.engineStatus')}</h3>
          <dl className="forecast-panel__status-grid">
            <div>
              <dt>{t('engine.forecast.mlEnabled')}</dt>
              <dd>{delayForecasts.ml_enabled ? t('corridor.yes') : t('corridor.no')}</dd>
            </div>
            <div>
              <dt>{t('engine.forecast.kafkaSamples')}</dt>
              <dd>{delayForecasts.kafka_buffer.samples_total}</dd>
            </div>
            <div>
              <dt>{t('engine.forecast.kafkaCorridors')}</dt>
              <dd>{delayForecasts.kafka_buffer.corridors_tracked}</dd>
            </div>
          </dl>
        </section>
      ) : null}
    </div>
  )
}
