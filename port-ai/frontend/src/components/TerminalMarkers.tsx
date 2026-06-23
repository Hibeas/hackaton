import { CircleMarker, Popup } from 'react-leaflet'
import { useTranslation } from 'react-i18next'
import type { TerminalCatalogEntry } from '../types/portOps'

interface TerminalMarkersProps {
  terminals: TerminalCatalogEntry[]
}

function markerColor(entry: TerminalCatalogEntry): string {
  if (!entry.active_last_hour) {
    return '#64748b'
  }
  switch (entry.truck_demand_hint) {
    case 'high':
      return '#ef4444'
    case 'medium':
      return '#f97316'
    case 'low':
      return '#eab308'
    default:
      return '#22c55e'
  }
}

export function TerminalMarkers({ terminals }: TerminalMarkersProps) {
  const { t } = useTranslation()

  return (
    <>
      {terminals.map((entry) => {
        if (entry.lat == null || entry.lon == null) {
          return null
        }
        const color = markerColor(entry)
        return (
          <CircleMarker
            key={entry.terminal}
            center={[entry.lat, entry.lon]}
            radius={entry.active_last_hour ? 10 : 7}
            pathOptions={{
              color: '#ffffff',
              fillColor: color,
              fillOpacity: 0.92,
              weight: 2,
            }}
          >
            <Popup>
              <div className="terminal-popup">
                <strong>{entry.label}</strong>
                <div>{entry.terminal}</div>
                <div>
                  {t(`portOps.demand.${entry.truck_demand_hint}`)} ·{' '}
                  {t('portOps.movesLastHour', { count: entry.moves_in_last_hour })}
                </div>
                {entry.description_pl ? <p>{entry.description_pl}</p> : null}
              </div>
            </Popup>
          </CircleMarker>
        )
      })}
    </>
  )
}
