import type { TrafficStatus } from './traffic'

export type TruckDemandHint = 'high' | 'medium' | 'low' | 'idle'

export interface TerminalCatalogEntry {
  terminal: string
  label: string
  description_pl?: string | null
  city: string
  lat: number | null
  lon: number | null
  has_codeco_data: boolean
  active_last_hour: boolean
  moves_in_last_hour: number
  moves_last_hour_display: number
  total_moves_24h: number
  truck_demand_hint: TruckDemandHint
  corridor?: string
}

export interface RoadStatusEntry {
  road: string
  status: TrafficStatus | 'unknown'
  status_pl?: string
  delay_sec?: number
  incident_count?: number
}

export interface ApproachZone {
  zone_id: string
  terminal: string
  city: string
  label: string
  priority: string
  roads_pl: string[]
  focus_pl?: string
  active_last_hour?: boolean
  moves_in_last_hour?: number
  truck_demand_hint?: TruckDemandHint
  corridor_status?: TrafficStatus | 'unknown'
  corridor_status_pl?: string
  geometry?: {
    type: 'LineString' | 'MultiLineString'
    coordinates: [number, number][] | [number, number][][]
  }
  reference_geometry?: {
    type: 'LineString'
    coordinates: [number, number][]
  }
  corridor_band?: {
    type: 'Polygon'
    coordinates: [number, number][][]
  }
}

export interface CityPortDashboard {
  key: string
  label: string
  cities: string[]
  active_terminals: number
  total_terminals: number
  corridor_status: TrafficStatus | 'unknown'
  corridor_status_pl: string
  roads_status: RoadStatusEntry[]
  terminals: Array<
    TerminalCatalogEntry & {
      tir_roads?: string[]
    }
  >
  tir_corridors?: ApproachZone[]
}

export interface PortOperationsSummary {
  vessel_count?: number
  port_call_count?: number
  container_move_count?: number
  active_port_calls?: number
  upcoming_port_calls?: number
}

export interface PortOperationsPayload {
  summary: PortOperationsSummary
  terminals_catalog: TerminalCatalogEntry[]
  approach_zones: ApproachZone[]
  city_port_dashboard: CityPortDashboard[]
  updated_at: string | null
}
