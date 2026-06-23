import { useTranslation } from 'react-i18next'
import type { AnomaliesResponse } from '../types/traffic'
import { formatDateTime } from '../utils/trafficFormat'
import { CityVerdictCard } from './CityVerdictCard'

interface AnomalyPanelProps {
  anomalies: AnomaliesResponse | null
}

export function AnomalyPanel({ anomalies }: AnomalyPanelProps) {
  const { t, i18n } = useTranslation()

  const baselineText =
    anomalies?.baseline.loaded &&
    anomalies.baseline.date_range &&
    anomalies.baseline.total_moves
      ? t('anomalies.baselineRange', {
          from: anomalies.baseline.date_range.from,
          to: anomalies.baseline.date_range.to,
          days: anomalies.baseline.date_range.days_observed,
          moves: anomalies.baseline.total_moves,
        })
      : t('anomalies.baselineMissing')

  return (
    <aside className="sidebar">
      <header className="sidebar__header">
        <h1>{t('app.title')}</h1>
        <p>{t('app.subtitle')}</p>
      </header>

      <section className="sidebar__section">
        <h2>{t('anomalies.title')}</h2>
        <p className="sidebar__meta sidebar__meta--sources">
          {t('anomalies.primarySource')}: TomTom · {t('anomalies.contextSource')}: ZTM
        </p>
        {anomalies ? (
          <p className="sidebar__meta">
            {t('anomalies.evaluatedAt')}:{' '}
            {formatDateTime(anomalies.evaluated_at, i18n.language)}
          </p>
        ) : null}
        <p className="sidebar__meta sidebar__meta--baseline">
          {t('anomalies.baseline')}: {baselineText}
        </p>

        <div className="verdict-list">
          {anomalies?.cities.map((city) => (
            <CityVerdictCard key={city.city} city={city} />
          ))}
        </div>
      </section>

      <section className="sidebar__section">
        <h2>{t('legend.title')}</h2>
        <ul className="legend">
          <li>
            <span className="legend__swatch legend__swatch--critical" />
            {t('legend.tomtomIncidents')}
          </li>
          <li>
            <span className="legend__swatch legend__swatch--congestion legend__swatch--faded" />
            {t('legend.contextSegments')}
          </li>
          <li>
            <span className="legend__swatch legend__swatch--clear legend__swatch--faded" />
            {t('legend.contextVehicles')}
          </li>
        </ul>
      </section>
    </aside>
  )
}
