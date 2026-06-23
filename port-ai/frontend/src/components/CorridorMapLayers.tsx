import { useEffect, useMemo, useRef } from 'react'
import { CircleMarker, Polygon, Popup, Rectangle } from 'react-leaflet'
import { useTranslation } from 'react-i18next'
import type { CircleMarker as LeafletCircleMarker } from 'leaflet'
import type { CorridorBbox, LatLng, PortConfig } from '../constants/ports'
import { corridorMapBounds } from '../utils/corridorConfigHelpers'
import type { OperationalReport } from '../utils/operationalReport'

interface PortCorridorsLayerProps {
  port: PortConfig | undefined
  selectedCorridorId: string | null
  onCorridorSelect: (corridorId: string) => void
}

function corridorBounds(corridor: PortConfig['corridors'][number]): LatLng[] {
  if (corridor.polygon && corridor.polygon.length >= 3) {
    return corridor.polygon
  }
  const bbox = corridorMapBounds(corridor)
  return [
    [bbox.min_lat, bbox.min_lon],
    [bbox.min_lat, bbox.max_lon],
    [bbox.max_lat, bbox.max_lon],
    [bbox.max_lat, bbox.min_lon],
  ]
}

export function PortCorridorsLayer({
  port,
  selectedCorridorId,
  onCorridorSelect,
}: PortCorridorsLayerProps) {
  if (!port) {
    return null
  }

  return (
    <>
      {port.corridors.map((corridor) => {
        const isSelected = corridor.id === selectedCorridorId
        const positions = corridorBounds(corridor)
        const hasPolygon = Boolean(corridor.polygon && corridor.polygon.length >= 3)

        const pathOptions = {
          color: isSelected ? '#2563eb' : '#64748b',
          weight: isSelected ? 2.5 : 1,
          fillColor: isSelected ? '#3b82f6' : '#94a3b8',
          fillOpacity: isSelected ? 0.14 : 0.05,
          dashArray: isSelected ? undefined : ('4 6' as const),
        }

        if (hasPolygon) {
          return (
            <Polygon
              key={corridor.id}
              positions={positions}
              pathOptions={pathOptions}
              eventHandlers={{
                click: () => onCorridorSelect(corridor.id),
              }}
            />
          )
        }

        const bbox = corridorMapBounds(corridor)
        return (
          <Rectangle
            key={corridor.id}
            bounds={[
              [bbox.min_lat, bbox.min_lon],
              [bbox.max_lat, bbox.max_lon],
            ]}
            pathOptions={pathOptions}
            eventHandlers={{
              click: () => onCorridorSelect(corridor.id),
            }}
          />
        )
      })}
    </>
  )
}

interface CorridorReportPopupProps {
  position: [number, number] | null
  report: OperationalReport | null
}

export function CorridorReportPopup({ position, report }: CorridorReportPopupProps) {
  const { t } = useTranslation()
  const markerRef = useRef<LeafletCircleMarker>(null)

  useEffect(() => {
    if (position && report && markerRef.current) {
      markerRef.current.openPopup()
    }
  }, [position, report])

  if (!position || !report) {
    return null
  }

  const dispatchColor =
    report.dispatchImpact === 'HOLD_DISPATCH'
      ? 'var(--color-verdict-anomaly)'
      : report.dispatchImpact === 'CAUTION'
        ? 'var(--color-verdict-watch)'
        : 'var(--color-verdict-calm)'

  return (
    <CircleMarker
      ref={markerRef}
      center={position}
      radius={1}
      pathOptions={{ opacity: 0, fillOpacity: 0, weight: 0 }}
    >
      <Popup className="corridor-report-popup" minWidth={300} maxWidth={380}>
        <article className="corridor-report">
          <header className="corridor-report__header">
            <div>
              <h3 className="corridor-report__title">{report.corridorName}</h3>
              <p className="corridor-report__meta">{report.portName}</p>
            </div>
            {report.hasAlert ? (
              <span
                className="corridor-report__badge corridor-report__badge--alert"
                style={{ backgroundColor: dispatchColor }}
              >
                {t('map.report.alertBadge', { severity: report.severity ?? 0 })}
              </span>
            ) : (
              <span className="corridor-report__badge corridor-report__badge--clear">
                {t('map.report.clearBadge')}
              </span>
            )}
          </header>

          <section className="corridor-report__block">
            <h4>{t('map.report.what')}</h4>
            <p>{report.what}</p>
          </section>

          <section className="corridor-report__block">
            <h4>{t('map.report.why')}</h4>
            <p>{report.why}</p>
          </section>

          <section className="corridor-report__block corridor-report__block--action">
            <h4>{t('map.report.recommendation')}</h4>
            <p>{report.recommendation}</p>
          </section>

          <footer className="corridor-report__metrics">
            <span>
              {t('engine.incidents')}: <strong>{report.incidentCount}</strong>
            </span>
            <span>
              {t('corridor.totalDelay')}: <strong>{Math.round(report.totalDelaySec)} s</strong>
            </span>
            {report.predictedDelaySec !== null && report.forecastHorizon !== null ? (
              <span>
                {t('map.report.forecastShort', {
                  horizon: report.forecastHorizon,
                  delay: Math.round(report.predictedDelaySec),
                })}
              </span>
            ) : null}
          </footer>
        </article>
      </Popup>
    </CircleMarker>
  )
}

export function CorridorHighlight({
  bbox,
  polygon,
}: {
  bbox?: CorridorBbox | null
  polygon?: LatLng[] | null
}) {
  const highlightStyle = useMemo(
    () => ({
      color: '#1d4ed8',
      weight: 3,
      fillOpacity: 0.06,
      dashArray: '8 4' as const,
    }),
    [],
  )

  if (polygon && polygon.length >= 3) {
    return <Polygon positions={polygon} pathOptions={highlightStyle} />
  }

  if (!bbox) {
    return null
  }

  return (
    <Rectangle
      bounds={[
        [bbox.min_lat, bbox.min_lon],
        [bbox.max_lat, bbox.max_lon],
      ]}
      pathOptions={highlightStyle}
    />
  )
}
