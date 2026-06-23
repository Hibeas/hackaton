import { useTranslation } from 'react-i18next'
import type { PortConfig } from '../constants/ports'
import {
  DASHBOARD_MODES,
  FORECAST_HORIZONS,
  forecastHorizonLabelKey,
  forecastHorizonLabelParams,
  type DashboardMode,
} from '../constants/forecast'
import { LanguageSwitcher } from './LanguageSwitcher'
import { VoiceDemoCallButton } from './VoiceDemoCallButton'

interface AppHeaderProps {
  ports: PortConfig[]
  selectedPortId: string
  onPortSelect: (portId: string) => void
  dashboardMode: DashboardMode
  onDashboardModeChange: (mode: DashboardMode) => void
  forecastHorizon: number
  onForecastHorizonChange: (horizon: number) => void
  activeAlertCount: number
  tomtomCount: number
  isLive: boolean
}

export function AppHeader({
  ports,
  selectedPortId,
  onPortSelect,
  dashboardMode,
  onDashboardModeChange,
  forecastHorizon,
  onForecastHorizonChange,
  activeAlertCount,
  tomtomCount,
  isLive,
}: AppHeaderProps) {
  const { t } = useTranslation()

  return (
    <header className="app-header">
      <nav className="app-header__ports" aria-label={t('engine.ports')}>
        {ports.map((port) => {
          const isActive = port.id === selectedPortId
          return (
            <button
              key={port.id}
              type="button"
              className={`port-pill${isActive ? ' port-pill--active' : ''}`}
              onClick={() => onPortSelect(port.id)}
            >
              {port.name}
            </button>
          )
        })}
      </nav>

      <nav className="app-header__modes" aria-label={t('app.modeNavigation')}>
        {DASHBOARD_MODES.map((mode) => (
          <button
            key={mode}
            type="button"
            className={`mode-pill${dashboardMode === mode ? ' mode-pill--active' : ''}`}
            onClick={() => onDashboardModeChange(mode)}
          >
            {t(`app.mode.${mode}`)}
          </button>
        ))}
      </nav>

      {dashboardMode === 'forecast' ? (
        <nav className="app-header__horizons" aria-label={t('engine.forecast.horizonNavigation')}>
          {FORECAST_HORIZONS.map((horizon) => (
            <button
              key={horizon}
              type="button"
              className={`horizon-pill${forecastHorizon === horizon ? ' horizon-pill--active' : ''}${horizon >= 120 ? ' horizon-pill--ml' : ''}`}
              onClick={() => onForecastHorizonChange(horizon)}
            >
              {t(forecastHorizonLabelKey(horizon), forecastHorizonLabelParams(horizon))}
            </button>
          ))}
        </nav>
      ) : (
        <div className="app-header__horizons app-header__horizons--placeholder" aria-hidden />
      )}

      <div className="app-header__stats">
        <span className={`live-dot${isLive ? ' live-dot--on' : ''}`} title={t('app.liveData')} />
        {dashboardMode === 'live' ? (
          <span className="stat-chip stat-chip--alert">
            {t('app.alerts')}: <strong>{activeAlertCount}</strong>
          </span>
        ) : (
          <span className="stat-chip stat-chip--forecast">
            {t('engine.forecast.modeActive')}:{' '}
            <strong>
              {t(forecastHorizonLabelKey(forecastHorizon), forecastHorizonLabelParams(forecastHorizon))}
            </strong>
          </span>
        )}
        <span className="stat-chip">
          TomTom: <strong>{tomtomCount}</strong>
        </span>
      </div>

      <div className="app-header__actions">
        <VoiceDemoCallButton />
        <a className="app-header__link" href="#/corridor-editor">
          {t('corridorEditor.navLink')}
        </a>
        <LanguageSwitcher />
      </div>
    </header>
  )
}
