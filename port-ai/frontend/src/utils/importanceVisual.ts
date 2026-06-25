import type { OperationalImportance } from './operationalImportance'
import type { ForecastPulseSeverity } from './forecastPulseReport'

export function importanceToPulseSeverity(
  importance: OperationalImportance,
): ForecastPulseSeverity {
  switch (importance) {
    case 'critical':
      return 'critical'
    case 'action':
      return 'high'
    case 'caution':
      return 'medium'
    case 'monitor':
    default:
      return 'low'
  }
}
