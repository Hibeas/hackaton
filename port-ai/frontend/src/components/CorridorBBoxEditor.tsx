import { useCallback, useEffect, useMemo, useState } from 'react'
import {
  CircleMarker,
  MapContainer,
  Polygon,
  Polyline,
  Rectangle,
  TileLayer,
  useMap,
  useMapEvents,
} from 'react-leaflet'
import { useTranslation } from 'react-i18next'
import type { BusinessPriority, CorridorConfig, GeofenceType } from '../constants/ports'
import { MAP_DEFAULT_CENTER, MAP_DEFAULT_ZOOM } from '../constants/traffic'
import {
  createCorridor,
  deleteCorridor,
  fetchCorridorConfig,
  patchCorridorGeometry,
  patchCorridorMetadata,
} from '../services/trafficApi'
import type { CorridorConfigResponse } from '../types/corridorConfig'
import {
  bboxFromPoints,
  bboxToPolygon,
  formatGeometrySnippet,
  type LatLng,
} from '../utils/corridorGeometry'
import { filterUiPorts } from '../utils/corridorConfigHelpers'

const PORT_CENTERS: Record<string, [number, number]> = {
  gdynia: [54.52, 18.53],
  gdansk: [54.36, 18.65],
  szczecin: [53.43, 14.55],
  swinoujscie: [53.91, 14.25],
}

const GEOFENCE_TYPES: GeofenceType[] = [
  'APPROACH_CORRIDOR',
  'BOTTLENECK',
  'BUFFER_ZONE',
  'GATE_ZONE',
  'PORT_ACCESS',
  'CRITICAL_INFRASTRUCTURE',
]

const BUSINESS_PRIORITIES: BusinessPriority[] = ['CRITICAL', 'HIGH']

interface MapClickCaptureProps {
  enabled: boolean
  onAddPoint: (point: LatLng) => void
  onClose: () => void
}

function MapClickCapture({ enabled, onAddPoint, onClose }: MapClickCaptureProps) {
  useMapEvents({
    click(event) {
      if (!enabled) {
        return
      }
      onAddPoint([event.latlng.lat, event.latlng.lng])
    },
    dblclick(event) {
      if (!enabled) {
        return
      }
      event.originalEvent.preventDefault()
      onClose()
    },
  })
  return null
}

function FlyToTarget({ target }: { target: [number, number] | null }) {
  const map = useMap()
  useEffect(() => {
    if (!target) {
      return
    }
    map.flyTo(target, 14, { duration: 0.8 })
  }, [map, target])
  return null
}

function slugify(value: string): string {
  return value
    .toLowerCase()
    .normalize('NFD')
    .replace(/[\u0300-\u036f]/g, '')
    .replace(/[^a-z0-9]+/g, '_')
    .replace(/^_|_$/g, '')
}

function corridorPolygon(corridor: CorridorConfig): LatLng[] {
  if (corridor.polygon && corridor.polygon.length >= 3) {
    return corridor.polygon
  }
  return bboxToPolygon(corridor.bbox)
}

function SavedCorridorLayer({
  corridor,
  isSelected,
}: {
  corridor: CorridorConfig
  isSelected: boolean
}) {
  const savedPolygon = corridorPolygon(corridor)

  return (
    <>
      <Polygon
        positions={savedPolygon}
        pathOptions={{
          color: isSelected ? '#3b82f6' : '#64748b',
          weight: isSelected ? 2 : 1,
          fillOpacity: isSelected ? 0.08 : 0.03,
          dashArray: isSelected ? undefined : '4 6',
        }}
      />
      {!corridor.polygon ? (
        <Rectangle
          bounds={[
            [corridor.bbox.min_lat, corridor.bbox.min_lon],
            [corridor.bbox.max_lat, corridor.bbox.max_lon],
          ]}
          pathOptions={{
            color: isSelected ? '#3b82f6' : '#64748b',
            weight: 1,
            fillOpacity: 0,
            dashArray: '2 4',
          }}
        />
      ) : null}
    </>
  )
}

interface CorridorBBoxEditorProps {
  onBack: () => void
}

export function CorridorBBoxEditor({ onBack }: CorridorBBoxEditorProps) {
  const { t } = useTranslation()
  const [config, setConfig] = useState<CorridorConfigResponse | null>(null)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [selectedPortId, setSelectedPortId] = useState('gdynia')
  const [selectedCorridorId, setSelectedCorridorId] = useState<string | null>(null)
  const [draftPoints, setDraftPoints] = useState<LatLng[]>([])
  const [isClosed, setIsClosed] = useState(false)
  const [statusMessage, setStatusMessage] = useState<string | null>(null)
  const [isSaving, setIsSaving] = useState(false)
  const [flyTarget, setFlyTarget] = useState<[number, number] | null>(null)
  const [isNewCorridor, setIsNewCorridor] = useState(false)

  const [metaName, setMetaName] = useState('')
  const [metaCity, setMetaCity] = useState('')
  const [metaType, setMetaType] = useState<GeofenceType>('APPROACH_CORRIDOR')
  const [metaPriority, setMetaPriority] = useState<BusinessPriority>('HIGH')
  const [metaWeight, setMetaWeight] = useState(7)

  const visiblePorts = useMemo(
    () => filterUiPorts(config?.ports ?? []),
    [config],
  )

  const loadConfig = useCallback(async () => {
    try {
      const data = await fetchCorridorConfig()
      setConfig(data)
      setLoadError(null)
    } catch (error) {
      setLoadError(error instanceof Error ? error.message : String(error))
    }
  }, [])

  useEffect(() => {
    void loadConfig()
  }, [loadConfig])

  useEffect(() => {
    if (visiblePorts.length === 0 || selectedCorridorId) {
      return
    }
    const port = visiblePorts.find((item) => item.id === selectedPortId) ?? visiblePorts[0]
    setSelectedPortId(port.id)
    setSelectedCorridorId(port.corridors[0]?.id ?? null)
    setFlyTarget(PORT_CENTERS[port.id] ?? MAP_DEFAULT_CENTER)
  }, [selectedCorridorId, selectedPortId, visiblePorts])

  const selectedPort = useMemo(
    () => visiblePorts.find((port) => port.id === selectedPortId) ?? null,
    [visiblePorts, selectedPortId],
  )

  const selectedCorridor = useMemo(() => {
    if (!selectedPort || !selectedCorridorId || isNewCorridor) {
      return null
    }
    return selectedPort.corridors.find((corridor) => corridor.id === selectedCorridorId) ?? null
  }, [isNewCorridor, selectedCorridorId, selectedPort])

  useEffect(() => {
    if (!selectedCorridor) {
      return
    }
    setMetaName(selectedCorridor.name)
    setMetaCity(selectedCorridor.city)
    setMetaType(selectedCorridor.geofence_type)
    setMetaPriority(selectedCorridor.business_priority)
    setMetaWeight(selectedCorridor.logistics_weight)
  }, [selectedCorridor])

  const draftBbox = useMemo(() => {
    if (!isClosed || draftPoints.length < 3) {
      return null
    }
    return bboxFromPoints(draftPoints)
  }, [draftPoints, isClosed])

  const jsonSnippet = useMemo(() => {
    if (!selectedCorridorId || !draftBbox || draftPoints.length < 3) {
      return null
    }
    return formatGeometrySnippet(selectedCorridorId, draftBbox, draftPoints)
  }, [draftBbox, draftPoints, selectedCorridorId])

  const resetDraft = () => {
    setDraftPoints([])
    setIsClosed(false)
    setStatusMessage(null)
  }

  const handlePortChange = (portId: string) => {
    setSelectedPortId(portId)
    setIsNewCorridor(false)
    const port = visiblePorts.find((item) => item.id === portId)
    setSelectedCorridorId(port?.corridors[0]?.id ?? null)
    resetDraft()
    setFlyTarget(PORT_CENTERS[portId] ?? MAP_DEFAULT_CENTER)
  }

  const handleCorridorChange = (corridorId: string) => {
    setIsNewCorridor(false)
    setSelectedCorridorId(corridorId)
    resetDraft()
    const corridor = selectedPort?.corridors.find((item) => item.id === corridorId)
    if (corridor) {
      const centerLat = (corridor.bbox.min_lat + corridor.bbox.max_lat) / 2
      const centerLon = (corridor.bbox.min_lon + corridor.bbox.max_lon) / 2
      setFlyTarget([centerLat, centerLon])
    }
  }

  const handleAddCorridor = () => {
    setIsNewCorridor(true)
    setSelectedCorridorId(`new_${Date.now()}`)
    setMetaName(t('corridorEditor.newGeofenceName'))
    setMetaCity(selectedPort?.name.replace('Port ', '') ?? '')
    setMetaType('APPROACH_CORRIDOR')
    setMetaPriority('HIGH')
    setMetaWeight(7)
    resetDraft()
  }

  const handleLoadSaved = () => {
    if (!selectedCorridor) {
      return
    }
    setDraftPoints(corridorPolygon(selectedCorridor))
    setIsClosed(true)
    setStatusMessage(t('corridorEditor.loadedSaved'))
  }

  const handleSaveGeometry = async () => {
    if (!draftBbox || draftPoints.length < 3) {
      setStatusMessage(t('corridorEditor.needClosedPolygon'))
      return
    }

    setIsSaving(true)
    try {
      if (isNewCorridor) {
        const corridorId = slugify(metaName) || `geofence_${Date.now()}`
        await createCorridor(selectedPortId, {
          id: corridorId,
          name: metaName,
          city: metaCity,
          geofence_type: metaType,
          business_priority: metaPriority,
          logistics_weight: metaWeight,
          impacts_port_access: true,
          bbox: draftBbox,
          polygon: draftPoints,
          terminals: selectedPort?.terminals ?? [],
        })
        setIsNewCorridor(false)
        setSelectedCorridorId(corridorId)
      } else if (selectedCorridorId) {
        await patchCorridorGeometry(selectedCorridorId, {
          bbox: draftBbox,
          polygon: draftPoints,
        })
      }

      await loadConfig()
      setStatusMessage(t('corridorEditor.saved'))
    } catch (error) {
      setStatusMessage(error instanceof Error ? error.message : String(error))
    } finally {
      setIsSaving(false)
    }
  }

  const handleSaveMetadata = async () => {
    if (!selectedCorridorId || isNewCorridor) {
      return
    }
    setIsSaving(true)
    try {
      await patchCorridorMetadata(selectedCorridorId, {
        name: metaName,
        city: metaCity,
        geofence_type: metaType,
        business_priority: metaPriority,
        logistics_weight: metaWeight,
      })
      await loadConfig()
      setStatusMessage(t('corridorEditor.metadataSaved'))
    } catch (error) {
      setStatusMessage(error instanceof Error ? error.message : String(error))
    } finally {
      setIsSaving(false)
    }
  }

  const handleDeleteCorridor = async () => {
    if (!selectedCorridorId || isNewCorridor) {
      return
    }
    if (!window.confirm(t('corridorEditor.deleteConfirm'))) {
      return
    }
    setIsSaving(true)
    try {
      await deleteCorridor(selectedCorridorId)
      await loadConfig()
      setSelectedCorridorId(null)
      resetDraft()
      setStatusMessage(t('corridorEditor.deleted'))
    } catch (error) {
      setStatusMessage(error instanceof Error ? error.message : String(error))
    } finally {
      setIsSaving(false)
    }
  }

  const handleCopyJson = async () => {
    if (!jsonSnippet) {
      return
    }
    await navigator.clipboard.writeText(jsonSnippet)
    setStatusMessage(t('corridorEditor.copied'))
  }

  return (
    <div className="editor-shell">
      <aside className="editor-sidebar">
        <div className="editor-sidebar__header">
          <button type="button" className="editor-back-btn" onClick={onBack}>
            {t('corridorEditor.back')}
          </button>
          <span className="editor-badge">{t('corridorEditor.devTool')}</span>
        </div>

        <h1 className="editor-title">{t('corridorEditor.title')}</h1>
        <p className="editor-subtitle">{t('corridorEditor.subtitle')}</p>

        {loadError ? <p className="editor-error">{loadError}</p> : null}

        <label className="editor-field">
          <span>{t('corridorEditor.port')}</span>
          <select
            value={selectedPortId}
            onChange={(event) => handlePortChange(event.target.value)}
            disabled={visiblePorts.length === 0}
          >
            {visiblePorts.map((port) => (
              <option key={port.id} value={port.id}>
                {port.name}
              </option>
            ))}
          </select>
        </label>

        <label className="editor-field">
          <span>{t('corridorEditor.corridor')}</span>
          <select
            value={isNewCorridor ? '__new__' : (selectedCorridorId ?? '')}
            onChange={(event) => {
              if (event.target.value === '__new__') {
                handleAddCorridor()
                return
              }
              handleCorridorChange(event.target.value)
            }}
            disabled={!selectedPort}
          >
            {(selectedPort?.corridors ?? []).map((corridor) => (
              <option key={corridor.id} value={corridor.id}>
                {corridor.name} [{corridor.geofence_type}] W{corridor.logistics_weight}
              </option>
            ))}
            <option value="__new__">{t('corridorEditor.addGeofence')}</option>
          </select>
        </label>

        <div className="editor-meta-panel">
          <h3 className="editor-meta-title">{t('corridorEditor.metadata')}</h3>
          <label className="editor-field">
            <span>{t('corridorEditor.metaName')}</span>
            <input value={metaName} onChange={(event) => setMetaName(event.target.value)} />
          </label>
          <label className="editor-field">
            <span>{t('corridorEditor.metaCity')}</span>
            <input value={metaCity} onChange={(event) => setMetaCity(event.target.value)} />
          </label>
          <label className="editor-field">
            <span>{t('geofence.label')}</span>
            <select
              value={metaType}
              onChange={(event) => setMetaType(event.target.value as GeofenceType)}
            >
              {GEOFENCE_TYPES.map((type) => (
                <option key={type} value={type}>
                  {t(`geofence.type.${type}`)}
                </option>
              ))}
            </select>
          </label>
          <label className="editor-field">
            <span>{t('corridorEditor.metaPriority')}</span>
            <select
              value={metaPriority}
              onChange={(event) => setMetaPriority(event.target.value as BusinessPriority)}
            >
              {BUSINESS_PRIORITIES.map((priority) => (
                <option key={priority} value={priority}>
                  {priority}
                </option>
              ))}
            </select>
          </label>
          <label className="editor-field">
            <span>{t('corridorEditor.metaWeight')}</span>
            <input
              type="number"
              min={1}
              max={10}
              value={metaWeight}
              onChange={(event) => setMetaWeight(Number(event.target.value))}
            />
          </label>
          <div className="editor-actions">
            <button
              type="button"
              onClick={() => void handleSaveMetadata()}
              disabled={isNewCorridor || isSaving || !selectedCorridorId}
            >
              {t('corridorEditor.saveMetadata')}
            </button>
            <button
              type="button"
              className="editor-danger-btn"
              onClick={() => void handleDeleteCorridor()}
              disabled={isNewCorridor || isSaving || !selectedCorridorId}
            >
              {t('corridorEditor.deleteGeofence')}
            </button>
          </div>
        </div>

        <div className="editor-help">
          <p>{t('corridorEditor.helpClick')}</p>
          <p>{t('corridorEditor.helpClose')}</p>
        </div>

        <div className="editor-actions">
          <button type="button" onClick={() => setDraftPoints((c) => c.slice(0, -1))} disabled={draftPoints.length === 0}>
            {t('corridorEditor.undoPoint')}
          </button>
          <button type="button" onClick={resetDraft} disabled={draftPoints.length === 0}>
            {t('corridorEditor.clear')}
          </button>
          <button
            type="button"
            onClick={() => {
              if (draftPoints.length < 3) {
                setStatusMessage(t('corridorEditor.needThreePoints'))
                return
              }
              setIsClosed(true)
            }}
            disabled={draftPoints.length < 3 || isClosed}
          >
            {t('corridorEditor.closePolygon')}
          </button>
          <button type="button" onClick={handleLoadSaved} disabled={!selectedCorridor}>
            {t('corridorEditor.loadSaved')}
          </button>
        </div>

        <div className="editor-stats">
          <span>{t('corridorEditor.pointCount', { count: draftPoints.length })}</span>
          <span>{isClosed ? t('corridorEditor.closed') : t('corridorEditor.open')}</span>
        </div>

        {draftBbox ? (
          <pre className="editor-json">
            {JSON.stringify({ bbox: draftBbox, polygon: draftPoints }, null, 2)}
          </pre>
        ) : (
          <p className="editor-muted">{t('corridorEditor.noBboxYet')}</p>
        )}

        <div className="editor-actions editor-actions--primary">
          <button type="button" onClick={() => void handleCopyJson()} disabled={!jsonSnippet}>
            {t('corridorEditor.copyJson')}
          </button>
          <button type="button" onClick={() => void handleSaveGeometry()} disabled={!jsonSnippet || isSaving}>
            {isSaving ? t('corridorEditor.saving') : t('corridorEditor.saveApi')}
          </button>
        </div>

        {statusMessage ? <p className="editor-status">{statusMessage}</p> : null}
      </aside>

      <div className="editor-map">
        <MapContainer
          center={MAP_DEFAULT_CENTER}
          zoom={MAP_DEFAULT_ZOOM}
          className="traffic-map"
          scrollWheelZoom
          doubleClickZoom={false}
        >
          <TileLayer
            attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OSM</a>'
            url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
          />
          <FlyToTarget target={flyTarget} />
          <MapClickCapture
            enabled={!isClosed}
            onAddPoint={(point) => {
              setDraftPoints((current) => [...current, point])
              setStatusMessage(null)
            }}
            onClose={() => {
              if (draftPoints.length >= 3) {
                setIsClosed(true)
              }
            }}
          />

          {selectedPort?.corridors.map((corridor) => (
            <SavedCorridorLayer
              key={corridor.id}
              corridor={corridor}
              isSelected={corridor.id === selectedCorridorId}
            />
          ))}

          {draftPoints.length >= 2 ? (
            <Polyline
              positions={draftPoints}
              pathOptions={{ color: '#f59e0b', weight: 3, dashArray: isClosed ? undefined : '6 4' }}
            />
          ) : null}

          {isClosed && draftPoints.length >= 3 ? (
            <Polygon
              positions={draftPoints}
              pathOptions={{ color: '#f59e0b', weight: 3, fillOpacity: 0.2 }}
            />
          ) : null}

          {draftPoints.map((point, index) => (
            <CircleMarker
              key={`${point[0]}-${point[1]}-${index}`}
              center={point}
              radius={6}
              pathOptions={{
                color: '#b45309',
                fillColor: '#f59e0b',
                fillOpacity: 0.9,
                weight: 2,
              }}
            />
          ))}
        </MapContainer>
      </div>
    </div>
  )
}
