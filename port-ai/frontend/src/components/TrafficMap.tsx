import { useEffect, useMemo, useState } from 'react'
import {
  CircleMarker,
  GeoJSON,
  MapContainer,
  Polygon,
  Popup,
  Rectangle,
  TileLayer,
  useMap,
} from 'react-leaflet'
import type { Layer } from 'leaflet'
import { useTranslation } from 'react-i18next'
import type { CorridorBbox, LatLng } from '../constants/ports'
import {
  MAP_DEFAULT_CENTER,
  MAP_DEFAULT_ZOOM,
  MAP_REGION_ORDER,
  MAP_REGION_VIEWS,
  TRAFFIC_STATUS_COLORS,
} from '../constants/traffic'
import type { HeatmapPoint, MapDataLayer, TrafficEvent, TrafficStatus } from '../types/traffic'
import {
  buildContextSegmentGeoJson,
  buildIncidentGeoJson,
  splitContextEvents,
  splitPrimaryEvents,
} from '../utils/trafficFormat'
import { TomTomHeatmapLayer } from './TomTomHeatmapLayer'
import { TerminalMarkers } from './TerminalMarkers'
import type { TerminalCatalogEntry } from '../types/portOps'
import { filterVisibleTerminals } from '../utils/portOpsHelpers'

interface TrafficMapProps {
  primary: MapDataLayer
  context: MapDataLayer
  heatmapPoints?: HeatmapPoint[]
  flowTileUrl?: string
  terminals?: TerminalCatalogEntry[]
  focusBbox?: CorridorBbox | null
  focusPolygon?: LatLng[] | null
  layoutRevision?: number
  flyRevision?: number
  onRegionSelect?: (portId: string) => void
}

function MapLayoutRefresh({ revision }: { revision: number }) {
  const map = useMap()

  useEffect(() => {
    const immediate = window.setTimeout(() => map.invalidateSize(), 0)
    const afterTransition = window.setTimeout(() => map.invalidateSize(), 320)
    return () => {
      window.clearTimeout(immediate)
      window.clearTimeout(afterTransition)
    }
  }, [map, revision])

  return null
}

function FlyToBbox({
  bbox,
  flyRevision = 0,
}: {
  bbox?: CorridorBbox | null
  flyRevision?: number
}) {
  const map = useMap()

  useEffect(() => {
    if (!bbox) {
      return
    }
    map.fitBounds(
      [
        [bbox.min_lat, bbox.min_lon],
        [bbox.max_lat, bbox.max_lon],
      ],
      { padding: [48, 48], maxZoom: 14 },
    )
  }, [bbox, flyRevision, map])

  return null
}

function CorridorHighlight({
  bbox,
  polygon,
}: {
  bbox?: CorridorBbox | null
  polygon?: LatLng[] | null
}) {
  if (polygon && polygon.length >= 3) {
    return (
      <Polygon
        positions={polygon}
        pathOptions={{
          color: '#f59e0b',
          weight: 2,
          fillOpacity: 0.1,
          dashArray: '6 4',
        }}
      />
    )
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
      pathOptions={{
        color: '#f59e0b',
        weight: 2,
        fillOpacity: 0.1,
        dashArray: '6 4',
      }}
    />
  )
}

function MapViewControls({ onRegionSelect }: { onRegionSelect?: (portId: string) => void }) {
  const map = useMap()
  const { t } = useTranslation()

  return (
    <div className="map-controls">
      {MAP_REGION_ORDER.map((portId) => {
        const region = MAP_REGION_VIEWS[portId]
        return (
          <button
            key={portId}
            type="button"
            onClick={() => {
              map.setView(region.center, region.zoom)
              onRegionSelect?.(portId)
            }}
          >
            {t(region.labelKey)}
          </button>
        )
      })}
      <button type="button" onClick={() => map.setView(MAP_DEFAULT_CENTER, MAP_DEFAULT_ZOOM)}>
        {t('map.zoomRegion')}
      </button>
    </div>
  )
}

function HeatmapControls({
  showFlowTiles,
  showIncidentHeat,
  showTerminals,
  onToggleFlowTiles,
  onToggleIncidentHeat,
  onToggleTerminals,
  pointCount,
  terminalCount,
}: {
  showFlowTiles: boolean
  showIncidentHeat: boolean
  showTerminals: boolean
  onToggleFlowTiles: () => void
  onToggleIncidentHeat: () => void
  onToggleTerminals: () => void
  pointCount: number
  terminalCount: number
}) {
  const { t } = useTranslation()

  return (
    <div className="heatmap-controls">
      <button
        type="button"
        className={showFlowTiles ? 'heatmap-controls__btn heatmap-controls__btn--active' : 'heatmap-controls__btn'}
        onClick={onToggleFlowTiles}
      >
        {t('map.heatmapFlowTiles')}
      </button>
      <button
        type="button"
        className={
          showIncidentHeat ? 'heatmap-controls__btn heatmap-controls__btn--active' : 'heatmap-controls__btn'
        }
        onClick={onToggleIncidentHeat}
      >
        {t('map.heatmapIncidents', { count: pointCount })}
      </button>
      <button
        type="button"
        className={
          showTerminals ? 'heatmap-controls__btn heatmap-controls__btn--active' : 'heatmap-controls__btn'
        }
        onClick={onToggleTerminals}
      >
        {t('map.terminalsLayer', { count: terminalCount })}
      </button>
    </div>
  )
}

function incidentStyle(feature?: GeoJSON.Feature) {
  const status = (feature?.properties?.status as TrafficStatus) ?? 'CONGESTION'
  return {
    color: TRAFFIC_STATUS_COLORS[status],
    weight: 7,
    opacity: 0.95,
    lineCap: 'round' as const,
    lineJoin: 'round' as const,
  }
}

function contextSegmentStyle(feature?: GeoJSON.Feature) {
  const status = (feature?.properties?.status as TrafficStatus) ?? 'CLEAR'
  return {
    color: TRAFFIC_STATUS_COLORS[status],
    weight: 5,
    opacity: 0.35,
    lineCap: 'round' as const,
    lineJoin: 'round' as const,
  }
}

function IncidentLayer({ incidents }: { incidents: TrafficEvent[] }) {
  const { t } = useTranslation()
  const { lineIncidents, pointIncidents } = useMemo(
    () => splitPrimaryEvents(incidents),
    [incidents],
  )
  const geoJson = useMemo(() => buildIncidentGeoJson(lineIncidents), [lineIncidents])

  const onEachFeature = (feature: GeoJSON.Feature, layer: Layer) => {
    const props = feature.properties as {
      roadName: string
      status: TrafficStatus
      delaySec: number
      reason: string
      category: string
    }
    layer.bindPopup(
      t('map.incidentPopup', {
        road: props.roadName,
        status: props.status,
        reason: props.reason,
        category: props.category,
        delay: props.delaySec,
      }),
    )
  }

  return (
    <>
      {geoJson.features.length > 0 ? (
        <GeoJSON
          key={`lines-${geoJson.features.length}`}
          data={geoJson}
          style={incidentStyle}
          onEachFeature={onEachFeature}
        />
      ) : null}
      {pointIncidents.map((event) => (
        <CircleMarker
          key={event.event_id}
          center={[event.location.lat, event.location.lon]}
          radius={8}
          pathOptions={{
            color: TRAFFIC_STATUS_COLORS[event.status],
            fillColor: TRAFFIC_STATUS_COLORS[event.status],
            fillOpacity: 0.9,
            weight: 2,
          }}
        >
          <Popup>
            <div
              dangerouslySetInnerHTML={{
                __html: t('map.incidentPopup', {
                  road: event.location.road_name,
                  status: event.status,
                  reason: event.metrics.primary_reason ?? '',
                  category: event.metrics.category_label ?? '',
                  delay: event.metrics.delay_sec ?? 0,
                }),
              }}
            />
          </Popup>
        </CircleMarker>
      ))}
    </>
  )
}

function ContextSegmentLayer({ segments }: { segments: TrafficEvent[] }) {
  const { t } = useTranslation()
  const geoJson = useMemo(() => buildContextSegmentGeoJson(segments), [segments])

  const onEachFeature = (feature: GeoJSON.Feature, layer: Layer) => {
    const props = feature.properties as {
      roadName: string
      status: TrafficStatus
      speedKmh: number
      intensityVph: number | null
    }
    const intensity =
      props.intensityVph === null || props.intensityVph === undefined
        ? t('map.intensityUnknown')
        : `${props.intensityVph} veh/h`

    layer.bindPopup(
      t('map.contextSegmentPopup', {
        road: props.roadName,
        status: props.status,
        speed: Math.round(props.speedKmh),
        intensity,
      }),
    )
  }

  if (geoJson.features.length === 0) {
    return null
  }

  return (
    <GeoJSON
      key={`ctx-${geoJson.features.length}`}
      data={geoJson}
      style={contextSegmentStyle}
      onEachFeature={onEachFeature}
    />
  )
}

function ContextVehicleMarkers({ vehicles }: { vehicles: TrafficEvent[] }) {
  const { t } = useTranslation()

  return (
    <>
      {vehicles.map((event) => (
        <CircleMarker
          key={event.event_id}
          center={[event.location.lat, event.location.lon]}
          radius={4}
          pathOptions={{
            color: TRAFFIC_STATUS_COLORS[event.status],
            fillColor: TRAFFIC_STATUS_COLORS[event.status],
            fillOpacity: 0.45,
            weight: 1,
          }}
        >
          <Popup>
            <div
              dangerouslySetInnerHTML={{
                __html: t('map.contextVehiclePopup', {
                  road: event.location.road_name,
                  status: event.status,
                  speed: Math.round(event.metrics.speed_kmh),
                }),
              }}
            />
          </Popup>
        </CircleMarker>
      ))}
    </>
  )
}

export function TrafficMap({
  primary,
  context,
  heatmapPoints = [],
  flowTileUrl = '/api/v1/tomtom/tiles/flow/relative0/{z}/{x}/{y}.png',
  terminals = [],
  focusBbox,
  focusPolygon,
  layoutRevision = 0,
  flyRevision = 0,
  onRegionSelect,
}: TrafficMapProps) {
  const [showFlowTiles, setShowFlowTiles] = useState(true)
  const [showIncidentHeat, setShowIncidentHeat] = useState(true)
  const [showTerminals, setShowTerminals] = useState(true)

  const visibleTerminals = useMemo(() => filterVisibleTerminals(terminals), [terminals])

  const { segments, vehicles } = useMemo(
    () => splitContextEvents(context.events),
    [context.events],
  )

  return (
    <div className="map-shell">
      <MapContainer
        center={MAP_DEFAULT_CENTER}
        zoom={MAP_DEFAULT_ZOOM}
        className="traffic-map"
        scrollWheelZoom
      >
        <TileLayer
          attribution="&copy; OpenStreetMap contributors"
          url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
        />
        {showFlowTiles ? (
          <TileLayer
            url={flowTileUrl}
            opacity={0.62}
            zIndex={450}
            maxNativeZoom={18}
            maxZoom={22}
          />
        ) : null}
        <TomTomHeatmapLayer points={heatmapPoints} enabled={showIncidentHeat} />
        {showTerminals ? <TerminalMarkers terminals={visibleTerminals} /> : null}
        <ContextSegmentLayer segments={segments} />
        <ContextVehicleMarkers vehicles={vehicles} />
        <IncidentLayer incidents={primary.events} />
        <CorridorHighlight bbox={focusBbox} polygon={focusPolygon} />
        <FlyToBbox bbox={focusBbox} flyRevision={flyRevision} />
        <MapLayoutRefresh revision={layoutRevision} />
        <MapViewControls onRegionSelect={onRegionSelect} />
      </MapContainer>
      <HeatmapControls
        showFlowTiles={showFlowTiles}
        showIncidentHeat={showIncidentHeat}
        showTerminals={showTerminals}
        onToggleFlowTiles={() => setShowFlowTiles((value) => !value)}
        onToggleIncidentHeat={() => setShowIncidentHeat((value) => !value)}
        onToggleTerminals={() => setShowTerminals((value) => !value)}
        pointCount={heatmapPoints.length}
        terminalCount={visibleTerminals.length}
      />
    </div>
  )
}
