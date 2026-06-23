import { useEffect, useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { PORTS } from './constants/ports'
import { CorridorBBoxEditor } from './components/CorridorBBoxEditor'
import { AppHeader } from './components/AppHeader'
import { DashboardSidebar } from './components/DashboardSidebar'
import { StatusBar } from './components/StatusBar'
import { TrafficMap } from './components/TrafficMap'
import { MapErrorBoundary } from './components/MapErrorBoundary'
import { useTrafficDashboard } from './hooks/useTrafficDashboard'
import { filterUiPorts, resolveFocusGeometry } from './utils/corridorConfigHelpers'
import { DEFAULT_FORECAST_HORIZON, type DashboardMode } from './constants/forecast'
import './App.css'

type AppView = 'dashboard' | 'editor'

function useAppView(): AppView {
  const [view, setView] = useState<AppView>(() =>
    window.location.hash === '#/corridor-editor' ? 'editor' : 'dashboard',
  )

  useEffect(() => {
    const onHashChange = () => {
      setView(window.location.hash === '#/corridor-editor' ? 'editor' : 'dashboard')
    }
    window.addEventListener('hashchange', onHashChange)
    return () => window.removeEventListener('hashchange', onHashChange)
  }, [])

  return view
}

function DashboardView() {
  const { t } = useTranslation()
  const {
    mapData,
    engineEvents,
    corridors,
    bottlenecks,
    corridorConfig,
    isLoading,
    error,
    lastUpdatedAt,
    refreshIntervalMs,
  } = useTrafficDashboard()

  const ports = useMemo(
    () => filterUiPorts(corridorConfig?.ports ?? PORTS),
    [corridorConfig],
  )

  const [selectedPortId, setSelectedPortId] = useState('gdynia')
  const [selectedCorridorId, setSelectedCorridorId] = useState<string | null>(null)
  const [dashboardMode, setDashboardMode] = useState<DashboardMode>('live')
  const [forecastHorizon, setForecastHorizon] = useState(DEFAULT_FORECAST_HORIZON)

  const focusGeometry = useMemo(
    () => resolveFocusGeometry(ports, selectedPortId, selectedCorridorId),
    [ports, selectedCorridorId, selectedPortId],
  )

  const portAlertCount = useMemo(
    () =>
      (engineEvents?.events ?? []).filter((event) => event.port_id === selectedPortId).length,
    [engineEvents, selectedPortId],
  )

  const handlePortSelect = (portId: string) => {
    setSelectedPortId(portId)
    setSelectedCorridorId(null)
  }

  const handleCorridorSelect = (corridorId: string) => {
    setSelectedCorridorId((current) => (current === corridorId ? null : corridorId))
  }

  return (
    <>
      <AppHeader
        ports={ports}
        selectedPortId={selectedPortId}
        onPortSelect={handlePortSelect}
        dashboardMode={dashboardMode}
        onDashboardModeChange={setDashboardMode}
        forecastHorizon={forecastHorizon}
        onForecastHorizonChange={(horizon) => setForecastHorizon(horizon as typeof DEFAULT_FORECAST_HORIZON)}
        activeAlertCount={portAlertCount}
        tomtomCount={mapData?.primary.incident_count ?? 0}
        isLive={!isLoading && !error}
      />

      <main className="app-main">
        <DashboardSidebar
          engineEvents={engineEvents}
          corridors={corridors}
          bottlenecks={bottlenecks}
          delayForecasts={mapData?.delay_forecasts}
          dashboardMode={dashboardMode}
          forecastHorizon={forecastHorizon}
          selectedPortId={selectedPortId}
          selectedCorridorId={selectedCorridorId}
          onCorridorSelect={handleCorridorSelect}
        />

        <div className="map-panel">
          {mapData?.primary ? (
            <MapErrorBoundary fallback={<div className="map-placeholder">{t('map.renderError')}</div>}>
              <TrafficMap
                primary={mapData.primary}
                context={mapData.context}
                heatmapPoints={mapData.heatmap?.points ?? []}
                flowTileUrl={mapData.heatmap?.flow_tile_url}
                terminals={mapData.port_operations?.terminals_catalog ?? []}
                focusBbox={focusGeometry.bbox}
                focusPolygon={focusGeometry.polygon}
              />
            </MapErrorBoundary>
          ) : (
            <div className="map-placeholder">
              <div className="map-placeholder__inner">
                <span className="map-placeholder__spinner" />
                <p>{t('status.loading')}</p>
              </div>
            </div>
          )}
        </div>
      </main>

      <StatusBar
        primaryCount={mapData?.primary.incident_count ?? 0}
        contextCount={mapData?.context.events.length ?? 0}
        engineEventCount={engineEvents?.active_count ?? 0}
        dataAgeSeconds={mapData?.age_seconds ?? null}
        lastUpdatedAt={lastUpdatedAt}
        refreshIntervalMs={refreshIntervalMs}
        isLoading={isLoading}
        error={error}
      />
    </>
  )
}

function App() {
  const view = useAppView()

  if (view === 'editor') {
    return (
      <CorridorBBoxEditor
        onBack={() => {
          window.location.hash = ''
        }}
      />
    )
  }

  return (
    <div className="app-shell">
      <DashboardView />
    </div>
  )
}

export default App
