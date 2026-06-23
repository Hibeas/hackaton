import { useTranslation } from 'react-i18next'
import { VERDICT_COLORS } from '../constants/traffic'
import type { CityAnalysis } from '../types/traffic'
import { formatPercent, formatRatio } from '../utils/trafficFormat'

interface CityVerdictCardProps {
  city: CityAnalysis
}

export function CityVerdictCard({ city }: CityVerdictCardProps) {
  const { t } = useTranslation()
  const verdictColor = VERDICT_COLORS[city.verdict]

  return (
    <article className="verdict-card" style={{ borderLeftColor: verdictColor }}>
      <header className="verdict-card__header">
        <h3>{city.city}</h3>
        <span className="verdict-card__badge" style={{ backgroundColor: verdictColor }}>
          {t(`verdict.${city.verdict}`)}
        </span>
      </header>

      <p className="verdict-card__cause">{city.cause}</p>

      <dl className="verdict-card__metrics">
        <div>
          <dt>{t('anomalies.tomtomIncidents')}</dt>
          <dd>
            {city.tomtom.incident_count}
            {city.tomtom.is_hot ? ` (${t('anomalies.tomtomHot')})` : ''}
          </dd>
        </div>
        <div>
          <dt>{t('anomalies.tomtomDelay')}</dt>
          <dd>{city.tomtom.total_delay_sec}s</dd>
        </div>
        <div>
          <dt>{t('anomalies.ztmContext')}</dt>
          <dd>
            {city.ztm_context.confirms_congestion
              ? t('anomalies.ztmConfirms')
              : formatPercent(city.ztm_context.congestion_ratio)}
          </dd>
        </div>
        <div>
          <dt>{t('anomalies.demandRatio')}</dt>
          <dd>{formatRatio(city.expected_demand.demand_ratio)}</dd>
        </div>
        <div>
          <dt>{t('anomalies.confidence')}</dt>
          <dd>
            {city.confidence === 'high'
              ? t('anomalies.confidenceHigh')
              : city.confidence === 'medium'
                ? t('anomalies.confidenceMedium')
                : t('anomalies.confidenceLow')}
          </dd>
        </div>
      </dl>

      {city.tomtom.top_causes.length > 0 ? (
        <ul className="verdict-card__causes">
          {city.tomtom.top_causes.map((cause) => (
            <li key={cause}>{cause}</li>
          ))}
        </ul>
      ) : null}
    </article>
  )
}
