export type DashboardMode = 'live' | 'forecast' | 'bookings'

export const DASHBOARD_MODES: DashboardMode[] = ['live', 'forecast', 'bookings']

/** Minutes; 120/180 are ML-only (2h / 3h). */
export const FORECAST_HORIZONS = [10, 15, 20, 30, 45, 60, 120, 180] as const

export type ForecastHorizon = (typeof FORECAST_HORIZONS)[number]

export const DEFAULT_FORECAST_HORIZON: ForecastHorizon = 30

export const ML_ONLY_MIN_HORIZON = 31

export function isMlOnlyHorizon(horizon: number): boolean {
  return horizon >= ML_ONLY_MIN_HORIZON
}

export function forecastHorizonLabelKey(horizon: number): string {
  if (horizon === 120) {
    return 'engine.forecast.horizon2h'
  }
  if (horizon === 180) {
    return 'engine.forecast.horizon3h'
  }
  return 'engine.forecast.horizonMinutes'
}

export function forecastHorizonLabelParams(horizon: number): { count: number } {
  return { count: horizon }
}
