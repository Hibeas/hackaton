import { useEffect, useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { PORTS } from './constants/ports'
import { CorridorBBoxEditor } from './components/CorridorBBoxEditor'
import { EngineDashboard } from './components/EngineDashboard'
import { LanguageSwitcher } from './components/LanguageSwitcher'
import { StatusBar } from './components/StatusBar'
import { TrafficMap } from './components/TrafficMap'
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

  const focusGeometry = useMemo(
    () => resolveFocusGeometry(ports, selectedPortId, selectedCorridorId),
    [ports, selectedCorridorId, selectedPortId],
  )

  const handlePortSelect = (portId: string) => {
    setSelectedPortId(portId)
    setSelectedCorridorId(null)
  }

  return (
    <>
      <main className="app-main">
        <div className="map-panel">
          {mapData?.primary ? (
            <TrafficMap
              primary={mapData.primary}
              context={mapData.context}
              focusBbox={focusGeometry.bbox}
              focusPolygon={focusGeometry.polygon}
            />
          ) : (
            <div className="map-placeholder" />
          )}
          <LanguageSwitcher />
          <a className="editor-nav-link" href="#/corridor-editor">
            {t('corridorEditor.navLink')}
          </a>
        </div>
        <EngineDashboard
          ports={ports}
          engineEvents={engineEvents}
          corridors={corridors}
          bottlenecks={bottlenecks}
          selectedPortId={selectedPortId}
          selectedCorridorId={selectedCorridorId}
          onPortSelect={handlePortSelect}
          onCorridorSelect={setSelectedCorridorId}
        />
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
