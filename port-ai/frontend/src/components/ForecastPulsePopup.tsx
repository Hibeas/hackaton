import { useEffect, useRef } from 'react'
import { CircleMarker, Popup } from 'react-leaflet'
import { useTranslation } from 'react-i18next'
import type { CircleMarker as LeafletCircleMarker } from 'leaflet'
import type { CorridorPulseDetail } from '../utils/forecastPulseReport'
import { formatDuration } from '../utils/trafficFormat'
import { causeCategoryChipClass } from '../utils/forecastPulseVisual'

interface ForecastPulsePopupProps {
  pulse: CorridorPulseDetail
}

export function ForecastPulsePopup({ pulse }: ForecastPulsePopupProps) {
  const { t } = useTranslation()
  const markerRef = useRef<LeafletCircleMarker>(null)

  useEffect(() => {
    if (markerRef.current) {
      markerRef.current.openPopup()
    }
  }, [pulse.corridorId, pulse.kind])

  const importanceClass = `forecast-pulse-popup__importance forecast-pulse-popup__importance--${pulse.operationalImportance}`
  const tagLabel =
    pulse.kind === 'validated'
      ? t('map.pulse.popup.validatedTag')
      : t('map.pulse.popup.predictedTag')

  const terminalsLabel =
    pulse.terminals.length > 0 ? pulse.terminals.join(', ') : t('map.pulse.popup.noTerminal')

  return (
    <CircleMarker
      ref={markerRef}
      center={pulse.position}
      radius={1}
      pathOptions={{ opacity: 0, fillOpacity: 0, weight: 0 }}
    >
      <Popup
        className="forecast-pulse-popup"
        minWidth={200}
        maxWidth={236}
        autoPan
        autoPanPadding={[12, 12]}
      >
        <article className="forecast-pulse-popup__card">
          <header className="forecast-pulse-popup__header">
            <span className="forecast-pulse-popup__tag">{tagLabel}</span>
            <span className={importanceClass}>
              {t(`map.pulse.importance.${pulse.operationalImportance}`)}
            </span>
          </header>

          <h3 className="forecast-pulse-popup__title" title={pulse.corridorName}>
            {pulse.corridorName}
          </h3>
          <p className="forecast-pulse-popup__context">
            {t('map.pulse.popup.operationalLine', {
              access: t(`geofence.type.${pulse.geofenceType}`),
              terminals: terminalsLabel,
              horizon: pulse.horizonMinutes,
              current: formatDuration(pulse.currentDelaySec),
            })}
          </p>

          <div className="forecast-pulse-popup__metric">
            <span className="forecast-pulse-popup__delay">
              {formatDuration(pulse.predictedDelaySec)}
            </span>
            <span className="forecast-pulse-popup__horizon">
              {t('map.pulse.popup.inHorizon', { count: pulse.horizonMinutes })}
            </span>
          </div>

          <p
            className="forecast-pulse-popup__cause"
            title={pulse.cause ?? undefined}
          >
            {pulse.cause ?? t('map.pulse.popup.whyUnknown')}
          </p>

          <div className="forecast-pulse-popup__chips">
            <span className={causeCategoryChipClass(pulse.causeCategory)}>
              {t(`map.pulse.cause.${pulse.causeCategory}`)}
            </span>
            <span className="forecast-pulse-popup__chip">
              {t(`map.pulse.popup.confidenceChip.${pulse.confidence}`)}
            </span>
            <span className="forecast-pulse-popup__chip">
              {t(`engine.forecast.methodShort.${pulse.method}`)}
            </span>
          </div>
        </article>
      </Popup>
    </CircleMarker>
  )
}

interface ForecastPulsePopupsProps {
  pulses: CorridorPulseDetail[]
}

export function ForecastPulsePopups({ pulses }: ForecastPulsePopupsProps) {
  if (pulses.length === 0) {
    return null
  }

  return (
    <>
      {pulses.map((pulse) => (
        <ForecastPulsePopup key={`${pulse.corridorId}-${pulse.kind}`} pulse={pulse} />
      ))}
    </>
  )
}
