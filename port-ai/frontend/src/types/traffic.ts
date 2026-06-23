export type TrafficStatus = 'CRITICAL' | 'CONGESTION' | 'CLEAR'

export type Verdict = 'NORMAL' | 'ANOMALY' | 'WATCH' | 'CALM'

export type Confidence = 'high' | 'medium' | 'low'

export type DataTier = 'primary' | 'context'

export type RecordKind = 'incident' | 'road_segment' | 'vehicle'

export interface LineStringGeometry {
  type: 'LineString'
  coordinates: [number, number][]
}

export interface PointGeometry {
  type: 'Point'
  coordinates: [number, number]
}

export type EventGeometry = LineStringGeometry | PointGeometry | null

export interface TrafficEvent {
  event_id: string
  record_kind: RecordKind
  data_tier?: DataTier
  entity_id: string
  city: string
  source_type: string
  timestamp: string
  location: {
    lat: number
    lon: number
    road_name: string
  }
  geometry: EventGeometry
  metrics: {
    speed_kmh: number
    intensity_vph: number | null
    is_bus_stop?: boolean
    line?: string | null
    direction?: string | null
    headsign?: string | null
    delay_sec?: number
    length_m?: number
    icon_category?: number
    category_label?: string
    primary_reason?: string
    magnitude?: number
    time_validity?: string
  }
  status: TrafficStatus
}

export interface MapDataLayer {
  source: string
  events: TrafficEvent[]
  incident_count?: number
}

export interface HeatmapPoint {
  lat: number
  lon: number
  intensity: number
}

export interface TomTomHeatmapLayer {
  source: string
  points: HeatmapPoint[]
  flow_tile_url: string
}

export interface MapDataResponse {
  primary: MapDataLayer
  context: MapDataLayer
  heatmap?: TomTomHeatmapLayer
  events: TrafficEvent[]
  cached_at: string | null
  age_seconds: number | null
  refresh_interval_seconds: number
  sources: Record<string, unknown>
}

export interface TomTomMetrics {
  incident_count: number
  severe_count: number
  total_delay_sec: number
  severe_ratio: number | null
  is_hot: boolean
  top_causes: string[]
}

export interface ZtmContext {
  considered: number
  congested: number
  congestion_ratio: number | null
  confirms_congestion: boolean
}

export interface ExpectedDemand {
  terminals: string[]
  expected_moves_now: number | null
  city_peak_moves: number | null
  demand_ratio: number | null
}

export interface CityAnalysis {
  city: string
  verdict: Verdict
  reason_code: string
  cause: string
  confidence: Confidence
  tomtom: TomTomMetrics
  ztm_context: ZtmContext
  expected_demand: ExpectedDemand
}

export interface AnomaliesResponse {
  evaluated_at: string
  primary_source: string
  context_source: string
  context: {
    day_of_week: number
    hour: number
  }
  baseline: {
    loaded: boolean
    generated_at?: string
    date_range?: {
      from: string
      to: string
      days_observed: number
    }
    total_moves?: number
  }
  cities: CityAnalysis[]
}
