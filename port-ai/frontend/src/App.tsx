import { useEffect, useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { PORTS } from './constants/ports'
import { CorridorBBoxEditor } from './components/CorridorBBoxEditor'
import { EngineDashboard } from './components/EngineDashboard'
import { LanguageSwitcher } from './components/LanguageSwitcher'
import { StatusBar } from './components/StatusBar'
import { TrafficMap } from './components/TrafficMap'
import { MapErrorBoundary } from './components/MapErrorBoundary'
import { useTrafficDashboard } from './hooks/useTrafficDashboard'
import { filterUiPorts, resolveFocusGeometry } from './utils/corridorConfigHelpers'
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
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false)
  const [mapLayoutRevision, setMapLayoutRevision] = useState(0)
  const [mapFlyRevision, setMapFlyRevision] = useState(0)

  const focusGeometry = useMemo(
    () => resolveFocusGeometry(ports, selectedPortId, selectedCorridorId),
    [ports, selectedCorridorId, selectedPortId],
  )

  const handlePortSelect = (portId: string) => {
    setSelectedPortId(portId)
    setSelectedCorridorId(null)
  }

  const handlePortFlyTo = (portId: string) => {
    setSelectedPortId(portId)
    setSelectedCorridorId(null)
    setMapFlyRevision((value) => value + 1)
  }

  const toggleSidebar = () => {
    setSidebarCollapsed((value) => !value)
    setMapLayoutRevision((value) => value + 1)
  }

  return (
    <>
      <main className="app-main">
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
                layoutRevision={mapLayoutRevision}
                flyRevision={mapFlyRevision}
                onRegionSelect={handlePortSelect}
              />
            </MapErrorBoundary>
          ) : (
            <div className="map-placeholder" />
          )}
          <div className="map-top-bar">
            <a className="editor-nav-link" href="#/corridor-editor">
              {t('corridorEditor.navLink')}
            </a>
            <LanguageSwitcher />
          </div>
        </div>
        <div
          className={`sidebar-shell${sidebarCollapsed ? ' sidebar-shell--collapsed' : ''}`}
        >
          <button
            type="button"
            className="sidebar-shell__toggle"
            onClick={toggleSidebar}
            aria-expanded={!sidebarCollapsed}
            aria-label={sidebarCollapsed ? t('sidebar.expand') : t('sidebar.collapse')}
            title={sidebarCollapsed ? t('sidebar.expand') : t('sidebar.collapse')}
          >
            <span className="sidebar-shell__toggle-icon" aria-hidden>
              {sidebarCollapsed ? '‹' : '›'}
            </span>
          </button>
          {!sidebarCollapsed ? (
            <EngineDashboard
              ports={ports}
              engineEvents={engineEvents}
              corridors={corridors}
              bottlenecks={bottlenecks}
              delayForecasts={mapData?.delay_forecasts}
              portOperations={mapData?.port_operations}
              selectedPortId={selectedPortId}
              selectedCorridorId={selectedCorridorId}
              onPortSelect={handlePortSelect}
              onCorridorSelect={setSelectedCorridorId}
              onPortFlyTo={handlePortFlyTo}
            />
          ) : null}
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
