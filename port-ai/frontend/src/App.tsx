import { useEffect, useMemo, useState, type ReactNode } from 'react'
import { useTranslation } from 'react-i18next'
import { PORTS, getCorridor } from './constants/ports'
import { CorridorBBoxEditor } from './components/CorridorBBoxEditor'
import { AppHeader } from './components/AppHeader'
import { DashboardSidebar } from './components/DashboardSidebar'
import { StatusBar } from './components/StatusBar'
import { TrafficMap } from './components/TrafficMap'
import { MapErrorBoundary } from './components/MapErrorBoundary'
import { LoginPage } from './components/LoginPage'
import { useAuth } from './context/AuthContext'
import { useTrafficDashboard } from './hooks/useTrafficDashboard'
import { filterUiPorts, findPort, resolveFocusGeometry } from './utils/corridorConfigHelpers'
import {
  buildOperationalReport,
  resolveCorridorMapCenter,
} from './utils/operationalReport'
import { DEFAULT_FORECAST_HORIZON, type DashboardMode } from './constants/forecast'
import type { CrowdMapOverlayResponse } from './types/traffic'
import './App.css'

type AppView = 'dashboard' | 'editor' | 'login'

function resolveViewFromHash(hash: string): AppView {
  if (hash === '#/login') {
    return 'login'
  }
  if (hash === '#/corridor-editor') {
    return 'editor'
  }
  return 'dashboard'
}

function useAppView(): AppView {
  const [view, setView] = useState<AppView>(() => resolveViewFromHash(window.location.hash))

  useEffect(() => {
    const onHashChange = () => {
      setView(resolveViewFromHash(window.location.hash))
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
    refresh,
  } = useTrafficDashboard()

  const ports = useMemo(
    () => filterUiPorts(corridorConfig?.ports ?? PORTS),
    [corridorConfig],
  )

  const [selectedPortId, setSelectedPortId] = useState('gdynia')
  const [selectedCorridorId, setSelectedCorridorId] = useState<string | null>(null)
  const [dashboardMode, setDashboardMode] = useState<DashboardMode>('live')
  const [forecastHorizon, setForecastHorizon] = useState(DEFAULT_FORECAST_HORIZON)
  const [crowdOverlay, setCrowdOverlay] = useState<CrowdMapOverlayResponse | null>(null)

  const mapPrimary = useMemo(() => {
    if (!mapData?.primary) {
      return null
    }
    if (!crowdOverlay) {
      return mapData.primary
    }
    return {
      ...mapData.primary,
      events: [...mapData.primary.events, ...crowdOverlay.primary.events],
      incident_count:
        (mapData.primary.incident_count ?? mapData.primary.events.length) +
        crowdOverlay.primary.events.length,
    }
  }, [mapData?.primary, crowdOverlay])

  const mapHeatmapPoints = useMemo(() => {
    if (crowdOverlay) {
      return crowdOverlay.heatmap.points
    }
    return mapData?.heatmap?.points ?? []
  }, [crowdOverlay, mapData?.heatmap?.points])

  const mapFlowTileUrl = crowdOverlay
    ? undefined
    : mapData?.heatmap?.flow_tile_url

  const handlePortSelect = (portId: string) => {
    setSelectedPortId(portId)
    setSelectedCorridorId(null)
    setCrowdOverlay(null)
  }

  const selectedCorridorName = useMemo(() => {
    if (!selectedCorridorId) {
      return null
    }
    const fromConfig = getCorridor(selectedCorridorId)?.name
    if (fromConfig) {
      return fromConfig
    }
    for (const port of ports) {
      const corridor = port.corridors.find((item) => item.id === selectedCorridorId)
      if (corridor) {
        return corridor.name
      }
    }
    return selectedCorridorId
  }, [ports, selectedCorridorId])

  const focusGeometry = useMemo(
    () => resolveFocusGeometry(ports, selectedPortId, selectedCorridorId),
    [ports, selectedCorridorId, selectedPortId],
  )

  const selectedPort = useMemo(() => findPort(ports, selectedPortId), [ports, selectedPortId])

  const corridorReport = useMemo(() => {
    if (!selectedCorridorId || !selectedCorridorName) {
      return null
    }
    return buildOperationalReport(selectedCorridorId, {
      corridorName: selectedCorridorName,
      portName: selectedPort?.name ?? selectedPortId,
      engineEvents,
      corridors,
      bottlenecks,
      delayForecasts: mapData?.delay_forecasts,
      forecastHorizon,
      t,
    })
  }, [
    selectedCorridorId,
    selectedCorridorName,
    selectedPort,
    selectedPortId,
    engineEvents,
    corridors,
    bottlenecks,
    mapData?.delay_forecasts,
    forecastHorizon,
    t,
  ])

  const reportPopupPosition = useMemo(
    () => resolveCorridorMapCenter(focusGeometry.bbox, focusGeometry.polygon),
    [focusGeometry.bbox, focusGeometry.polygon],
  )

  const handleCorridorSelect = (corridorId: string) => {
    setSelectedCorridorId((current) => (current === corridorId ? null : corridorId))
    setCrowdOverlay(null)
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
        isLive={!isLoading && !error}
        selectedCorridorId={selectedCorridorId}
        selectedCorridorName={selectedCorridorName}
        onSpikeDemoComplete={() => {
          void refresh()
        }}
        crowdOverlay={crowdOverlay}
        onCrowdOverlayChange={setCrowdOverlay}
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
          {mapPrimary ? (
            <MapErrorBoundary fallback={<div className="map-placeholder">{t('map.renderError')}</div>}>
              <TrafficMap
                primary={mapPrimary}
                context={mapData.context}
                heatmapPoints={mapHeatmapPoints}
                flowTileUrl={mapFlowTileUrl}
                crowdDemoActive={crowdOverlay !== null}
                terminals={mapData.port_operations?.terminals_catalog ?? []}
                focusBbox={focusGeometry.bbox}
                focusPolygon={focusGeometry.polygon}
                selectedPort={selectedPort}
                selectedCorridorId={selectedCorridorId}
                corridorReport={corridorReport}
                reportPopupPosition={reportPopupPosition}
                onCorridorSelect={handleCorridorSelect}
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
        primaryCount={mapPrimary?.incident_count ?? mapData?.primary.incident_count ?? 0}
        contextCount={mapData?.context.events.length ?? 0}
        engineEventCount={engineEvents?.active_count ?? 0}
        dataAgeSeconds={mapData?.age_seconds ?? null}
        lastUpdatedAt={lastUpdatedAt}
        refreshIntervalMs={refreshIntervalMs}
        isLoading={isLoading}
        error={error}
        crowdDemoActive={crowdOverlay !== null}
        crowdCorridorName={crowdOverlay?.corridor_name ?? null}
      />
    </>
  )
}

function AuthGate({ children }: { children: ReactNode }) {
  const { isAuthenticated, isLoading } = useAuth()

  useEffect(() => {
    if (!isLoading && !isAuthenticated && window.location.hash !== '#/login') {
      window.location.hash = '#/login'
    }
  }, [isAuthenticated, isLoading])

  if (isLoading) {
    return (
      <div className="auth-loading">
        <span className="map-placeholder__spinner" />
      </div>
    )
  }

  if (!isAuthenticated) {
    return null
  }

  return <>{children}</>
}

function App() {
  const view = useAppView()
  const { isAuthenticated, isLoading } = useAuth()

  if (view === 'login') {
    if (!isLoading && isAuthenticated) {
      window.location.hash = ''
      return null
    }
    return <LoginPage />
  }

  if (view === 'editor') {
    return (
      <AuthGate>
        <CorridorBBoxEditor
          onBack={() => {
            window.location.hash = ''
          }}
        />
      </AuthGate>
    )
  }

  return (
    <AuthGate>
      <div className="app-shell">
        <DashboardView />
      </div>
    </AuthGate>
  )
}

export default App
