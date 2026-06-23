export type DispatchImpact = 'HOLD_DISPATCH' | 'CAUTION' | 'MONITOR'

export type PortContext =
  | 'expected_gate_peak'
  | 'low_port_demand'
  | 'moderate_port_demand'
  | 'unknown'

export type GeofenceType =
  | 'APPROACH_CORRIDOR'
  | 'BOTTLENECK'
  | 'BUFFER_ZONE'
  | 'GATE_ZONE'
  | 'PORT_ACCESS'
  | 'CRITICAL_INFRASTRUCTURE'

export type BusinessPriority = 'CRITICAL' | 'HIGH'

export interface CorridorMetrics {
  avg_speed_kmh: number | null
  incident_count: number
  total_delay_sec: number
  max_delay_sec: number
  congestion_ratio: number | null
  avg_intensity_vph: number | null
  demand_ratio: number | null
  top_incident_causes: string[]
}

export interface CorridorSnapshot {
  corridor_id: string
  port_id: string
  port_name: string
  corridor_name: string
  city?: string
  geofence_type?: GeofenceType
  business_priority?: BusinessPriority
  logistics_weight?: number
  impacts_port_access?: boolean
  priority_weight: number
  terminals: string[]
  timestamp: string
  metrics: CorridorMetrics
}

export interface EngineEventDetails {
  window_minutes: number | null
  delta_speed_pct: number | null
  delta_delay_sec: number | null
  delta_congestion: number | null
  duration_minutes: number | null
  current_metrics: CorridorMetrics
  top_incident_causes: string[]
}

export interface EngineEvent {
  id: string
  timestamp: string
  port: string
  port_id: string
  roadSegment: string
  corridor_id: string
  geofence_type?: GeofenceType
  business_priority?: BusinessPriority
  logistics_weight?: number
  eventType: string
  reason_code: string
  severity: number
  confidence: number
  summary: string
  port_context: PortContext
  dispatch_impact: DispatchImpact
  details: EngineEventDetails
}

export interface EngineEventsResponse {
  evaluated_at: string | null
  observation_count: number
  events: EngineEvent[]
  active_count: number
}

export interface BottleneckItem {
  corridor_id: string
  corridor_name: string
  port_id: string
  port_name: string
  window_minutes: number
  stress_score: number
  avg_delay_sec: number
  max_delay_sec: number
  avg_incident_count: number
  min_speed_kmh: number | null
  samples: number
}

export interface BottlenecksResponse {
  window_minutes: number
  evaluated_at: string | null
  bottlenecks: BottleneckItem[]
}

export interface CorridorsResponse {
  evaluated_at: string | null
  corridors: CorridorSnapshot[]
  related_events: EngineEvent[]
}
