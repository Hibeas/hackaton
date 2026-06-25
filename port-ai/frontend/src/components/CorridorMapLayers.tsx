import { Fragment, useEffect, useMemo, useRef, useState } from 'react'
import { CircleMarker, Polygon, Popup, Rectangle } from 'react-leaflet'
import { useTranslation } from 'react-i18next'
import type { CircleMarker as LeafletCircleMarker, PathOptions } from 'leaflet'
import type { CorridorBbox, LatLng, PortConfig } from '../constants/ports'
import { corridorMapBounds } from '../utils/corridorConfigHelpers'
import type { CorridorPulseDetail } from '../utils/forecastPulseReport'
import {
  buildCorridorPulsePathOptions,
  isPulseBright,
} from '../utils/forecastPulseVisual'
import type { OperationalReport } from '../utils/operationalReport'
import { copyOperationalReport, downloadOperationalReport } from '../utils/reportExport'

interface PortCorridorsLayerProps {
  port: PortConfig | undefined
  selectedCorridorId: string | null
  activePulseByCorridor?: Map<string, CorridorPulseDetail>
  pulseNow?: number
  onCorridorSelect: (corridorId: string) => void
}

function buildIdleCorridorPathOptions(isSelected: boolean) {
  return {
    color: isSelected ? '#2563eb' : '#64748b',
    weight: isSelected ? 2.5 : 1,
    fillColor: isSelected ? '#3b82f6' : '#94a3b8',
    fillOpacity: isSelected ? 0.14 : 0.05,
    dashArray: isSelected ? undefined : ('4 6' as const),
  }
}

const selectionOutlineStyle = {
  color: '#2563eb',
  weight: 2,
  fillOpacity: 0,
  dashArray: undefined as undefined,
}

function CorridorShape({
  corridorId,
  positions,
  bbox,
  hasPolygon,
  pathOptions,
  onCorridorSelect,
}: {
  corridorId: string
  positions: LatLng[]
  bbox: CorridorBbox
  hasPolygon: boolean
  pathOptions: PathOptions
  onCorridorSelect: (corridorId: string) => void
}) {
  const handlers = { click: () => onCorridorSelect(corridorId) }

  if (hasPolygon) {
    return <Polygon positions={positions} pathOptions={pathOptions} eventHandlers={handlers} />
  }

  return (
    <Rectangle
      bounds={[
        [bbox.min_lat, bbox.min_lon],
        [bbox.max_lat, bbox.max_lon],
      ]}
      pathOptions={pathOptions}
      eventHandlers={handlers}
    />
  )
}

export function PortCorridorsLayer({
  port,
  selectedCorridorId,
  activePulseByCorridor,
  pulseNow = 0,
  onCorridorSelect,
}: PortCorridorsLayerProps) {
  if (!port) {
    return null
  }

  return (
    <>
      {port.corridors.map((corridor) => {
        const isSelected = corridor.id === selectedCorridorId
        const pulse = activePulseByCorridor?.get(corridor.id)
        const positions = corridorBounds(corridor)
        const hasPolygon = Boolean(corridor.polygon && corridor.polygon.length >= 3)
        const bbox = corridorMapBounds(corridor)

        const pathOptions = pulse
          ? buildCorridorPulsePathOptions(pulse, isPulseBright(pulse, pulseNow))
          : buildIdleCorridorPathOptions(isSelected)

        return (
          <Fragment key={corridor.id}>
            {isSelected && pulse ? (
              hasPolygon ? (
                <Polygon positions={positions} pathOptions={selectionOutlineStyle} />
              ) : (
                <Rectangle
                  bounds={[
                    [bbox.min_lat, bbox.min_lon],
                    [bbox.max_lat, bbox.max_lon],
                  ]}
                  pathOptions={selectionOutlineStyle}
                />
              )
            ) : null}
            <CorridorShape
              corridorId={corridor.id}
              positions={positions}
              bbox={bbox}
              hasPolygon={hasPolygon}
              pathOptions={pathOptions}
              onCorridorSelect={onCorridorSelect}
            />
          </Fragment>
        )
      })}
    </>
  )
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

interface CorridorReportPopupProps {
  position: [number, number] | null
  report: OperationalReport | null
}

export function CorridorReportPopup({ position, report }: CorridorReportPopupProps) {
  const { t } = useTranslation()
  const markerRef = useRef<LeafletCircleMarker>(null)
  const [exportStatus, setExportStatus] = useState<'idle' | 'copied' | 'error'>('idle')

  useEffect(() => {
    if (position && report && markerRef.current) {
      markerRef.current.openPopup()
    }
  }, [position, report])

  if (!position || !report) {
    return null
  }

  const handleCopy = async () => {
    try {
      await copyOperationalReport(report)
      setExportStatus('copied')
      window.setTimeout(() => setExportStatus('idle'), 2500)
    } catch {
      setExportStatus('error')
      window.setTimeout(() => setExportStatus('idle'), 2500)
    }
  }

  const handleDownload = () => {
    downloadOperationalReport(report)
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
      <Popup
        className="corridor-report-popup"
        minWidth={280}
        maxWidth={340}
        autoPanPadding={[20, 20]}
      >
        <article className="corridor-report">
          <header className="corridor-report__header">
            <div className="corridor-report__header-text">
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

          <div className="corridor-report__body">
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
          </div>

          <footer className="corridor-report__footer">
            <div className="corridor-report__actions">
              <button type="button" className="corridor-report__btn" onClick={() => void handleCopy()}>
                {exportStatus === 'copied'
                  ? t('map.report.copied')
                  : exportStatus === 'error'
                    ? t('map.report.copyError')
                    : t('map.report.copy')}
              </button>
              <button type="button" className="corridor-report__btn" onClick={handleDownload}>
                {t('map.report.download')}
              </button>
            </div>

            <div className="corridor-report__metrics">
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
            </div>
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
