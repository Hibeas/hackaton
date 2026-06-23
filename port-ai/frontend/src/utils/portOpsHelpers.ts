import type { CityPortDashboard, TerminalCatalogEntry } from '../types/portOps'

/** Terminals and TIR zones visible in port-ops panel per selected port tab. */
export const PORT_OPS_CITY_KEYS = new Set(['gdansk', 'gdynia', 'szczecin', 'swinoujscie'])
export const PORT_OPS_CITIES = new Set(['Gdansk', 'Gdynia', 'Szczecin', 'Swinoujscie'])

export function filterPortOpsDashboard(
  dashboard: CityPortDashboard[] | undefined,
): CityPortDashboard[] {
  if (!dashboard) {
    return []
  }
  return dashboard.filter((group) => PORT_OPS_CITY_KEYS.has(group.key))
}

export function filterVisibleTerminals(
  catalog: TerminalCatalogEntry[] | undefined,
): TerminalCatalogEntry[] {
  if (!catalog) {
    return []
  }
  return catalog.filter(
    (entry) => entry.lat != null && entry.lon != null && PORT_OPS_CITIES.has(entry.city),
  )
}

export function demandHintLabel(hint: string | undefined): string {
  switch (hint) {
    case 'high':
      return 'high'
    case 'medium':
      return 'medium'
    case 'low':
      return 'low'
    default:
      return 'idle'
  }
}
