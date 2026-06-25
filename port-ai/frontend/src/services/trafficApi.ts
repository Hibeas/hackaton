import type {
  AnomaliesResponse,
  CrowdMapOverlayResponse,
  MapDataResponse,
} from '../types/traffic'
import { getStoredToken } from './authStorage'
import type {
  BottlenecksResponse,
  CorridorsResponse,
  DelayForecastResponse,
  EngineEventsResponse,
} from '../types/engine'
import type { CorridorConfigResponse } from '../types/corridorConfig'
import type { SlotRecommendation, SlotRecommendationsResponse } from '../types/tms'
import type { CorridorBbox, LatLng } from '../constants/ports'

async function readApiError(response: Response): Promise<string> {
  const body = (await response.json().catch(() => null)) as
    | { detail?: string | Array<{ msg?: string }> }
    | null
  if (typeof body?.detail === 'string') {
    return body.detail
  }
  if (Array.isArray(body?.detail) && body.detail[0]?.msg) {
    return body.detail[0].msg
  }
  return `HTTP ${response.status}`
}

async function fetchJson<T>(url: string): Promise<T> {
  const token = getStoredToken()
  const headers: Record<string, string> = {}
  if (token) {
    headers.Authorization = `Bearer ${token}`
  }
  const response = await fetch(url, { headers })
  if (!response.ok) {
    throw new Error(await readApiError(response))
  }
  return response.json() as Promise<T>
}

export async function fetchCrowdMapOverlay(
  corridorId: string,
  peakDelaySec = 960,
): Promise<CrowdMapOverlayResponse> {
  const search = new URLSearchParams({
    corridor_id: corridorId,
    peak_delay_sec: String(peakDelaySec),
  })
  return fetchJson<CrowdMapOverlayResponse>(`/api/v1/demo/crowd-map?${search}`)
}

export async function fetchMapData(): Promise<MapDataResponse> {
  return fetchJson<MapDataResponse>('/api/v1/map-data')
}

export async function fetchAnomalies(): Promise<AnomaliesResponse> {
  return fetchJson<AnomaliesResponse>('/api/v1/anomalies')
}

export async function fetchEngineEvents(): Promise<EngineEventsResponse> {
  return fetchJson<EngineEventsResponse>('/api/v1/engine/events')
}

export async function fetchBottlenecks(): Promise<BottlenecksResponse> {
  return fetchJson<BottlenecksResponse>('/api/v1/engine/bottlenecks')
}

export async function fetchCorridors(): Promise<CorridorsResponse> {
  return fetchJson<CorridorsResponse>('/api/v1/engine/corridors')
}

export async function fetchEngineForecast(params?: {
  horizons?: number[]
  portId?: string
  corridorId?: string
}): Promise<DelayForecastResponse> {
  const search = new URLSearchParams()
  if (params?.horizons?.length) {
    search.set('horizons', params.horizons.join(','))
  }
  if (params?.portId) {
    search.set('port_id', params.portId)
  }
  if (params?.corridorId) {
    search.set('corridor_id', params.corridorId)
  }
  const query = search.toString()
  return fetchJson<DelayForecastResponse>(
    `/api/v1/engine/forecast${query ? `?${query}` : ''}`,
  )
}

export async function fetchCorridorConfig(): Promise<CorridorConfigResponse> {
  return fetchJson<CorridorConfigResponse>('/api/v1/engine/corridor-config')
}

export async function patchPortGeometry(
  portId: string,
  payload: { bbox: CorridorBbox; polygon: LatLng[] },
): Promise<{ ok: boolean; port_id: string }> {
  const response = await fetch(`/api/v1/engine/ports/${portId}/geometry`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
  if (!response.ok) {
    throw new Error(`HTTP ${response.status} saving port geometry`)
  }
  return response.json() as Promise<{ ok: boolean; port_id: string }>
}

export async function patchCorridorGeometry(
  corridorId: string,
  payload: { bbox: CorridorBbox; polygon: LatLng[] },
): Promise<{ ok: boolean; corridor_id: string }> {
  const response = await fetch(`/api/v1/engine/corridors/${corridorId}/geometry`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
  if (!response.ok) {
    throw new Error(`HTTP ${response.status} saving corridor geometry`)
  }
  return response.json() as Promise<{ ok: boolean; corridor_id: string }>
}

export interface CorridorMetadataPayload {
  name?: string
  city?: string
  geofence_type?: string
  business_priority?: string
  logistics_weight?: number
  impacts_port_access?: boolean
  terminals?: string[]
}

export async function patchCorridorMetadata(
  corridorId: string,
  payload: CorridorMetadataPayload,
): Promise<{ ok: boolean; corridor_id: string }> {
  const response = await fetch(`/api/v1/engine/corridors/${corridorId}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
  if (!response.ok) {
    throw new Error(`HTTP ${response.status} saving corridor metadata`)
  }
  return response.json() as Promise<{ ok: boolean; corridor_id: string }>
}

export interface CorridorCreatePayload {
  id: string
  name: string
  city?: string
  geofence_type: string
  business_priority: string
  logistics_weight: number
  impacts_port_access: boolean
  bbox: CorridorBbox
  polygon?: LatLng[]
  terminals?: string[]
}

export async function createCorridor(
  portId: string,
  payload: CorridorCreatePayload,
): Promise<{ ok: boolean; port_id: string; corridor_id: string }> {
  const response = await fetch(`/api/v1/engine/ports/${portId}/corridors`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
  if (!response.ok) {
    throw new Error(`HTTP ${response.status} creating corridor`)
  }
  return response.json() as Promise<{ ok: boolean; port_id: string; corridor_id: string }>
}

export async function deleteCorridor(
  corridorId: string,
): Promise<{ ok: boolean; corridor_id: string }> {
  const response = await fetch(`/api/v1/engine/corridors/${corridorId}`, {
    method: 'DELETE',
  })
  if (!response.ok) {
    throw new Error(`HTTP ${response.status} deleting corridor`)
  }
  return response.json() as Promise<{ ok: boolean; corridor_id: string }>
}

export interface OperationalActions {
  scenario: string
  operational_importance: string
  driver: string[]
  dispatcher: string[]
  voice_summary?: string
  slot_recommendations?: SlotRecommendation[]
}

export interface CorridorSpikeDemoResponse {
  ok: boolean
  corridor_id: string
  corridor_name?: string
  phone_e164?: string
  dry_run?: boolean
  max_predicted_delay_sec?: number
  operational_actions?: OperationalActions
  slot_recommendations?: SlotRecommendationsResponse
  voice?: {
    enabled?: boolean
    skipped?: boolean
    reason?: string | null
  }
  slot?: {
    slot_id?: string
    phone_e164?: string
    spedition_id?: string
  }
  dispatch?: {
    alert_count?: number
    dry_run?: boolean
    calls?: Array<{
      status?: string
      call_sid?: string
      phone?: string
      booking_ref?: string
      slot_id?: string
      error?: string
      fingerprint?: string
    }>
    alerts?: Array<{
      slot_id?: string
      phones?: string[]
      corridor_name?: string
    }>
  }
}

export interface CrowdScenarioResponse {
  ok: boolean
  corridor_id: string
  corridor_name?: string
  map_overlay: CrowdMapOverlayResponse
  operational_actions: OperationalActions
  slot_recommendations?: SlotRecommendationsResponse
  corridor_forecasts?: Array<Record<string, unknown>>
  at_risk_slot?: Record<string, unknown> | null
  max_predicted_delay_sec?: number
}

export interface CorridorIncidentResponse {
  ok: boolean
  corridor_id: string
  corridor_name?: string
  port_id?: string
  enable_voice?: boolean
  map_overlay: CrowdMapOverlayResponse
  operational_actions: OperationalActions
  slot_recommendations?: SlotRecommendationsResponse
  corridor_forecasts?: Array<Record<string, unknown>>
  at_risk_slot?: Record<string, unknown> | null
  max_predicted_delay_sec?: number
  voice?: {
    requested?: boolean
    enabled?: boolean
    skipped?: boolean
    reason?: string | null
  }
  dispatch?: CorridorSpikeDemoResponse['dispatch']
}

export async function triggerCorridorIncident(
  corridorId: string,
  payload?: { enable_voice?: boolean; peak_delay_sec?: number; mark_slots_at_risk?: boolean },
): Promise<CorridorIncidentResponse> {
  const token = getStoredToken()
  const headers: Record<string, string> = { 'Content-Type': 'application/json' }
  if (token) {
    headers.Authorization = `Bearer ${token}`
  }
  const response = await fetch('/api/v1/demo/corridor-incident', {
    method: 'POST',
    headers,
    body: JSON.stringify({
      corridor_id: corridorId,
      enable_voice: payload?.enable_voice ?? false,
      peak_delay_sec: payload?.peak_delay_sec ?? 960,
      mark_slots_at_risk: payload?.mark_slots_at_risk ?? true,
    }),
  })
  if (!response.ok) {
    const body = (await response.json().catch(() => null)) as { detail?: string } | null
    throw new Error(body?.detail ?? `HTTP ${response.status}`)
  }
  return response.json() as Promise<CorridorIncidentResponse>
}

export interface DemoReportSection {
  title: string
  body?: string
  items?: string[]
}

export interface DemoReport {
  report_id: string
  is_test: boolean
  generated_at: string
  headline: string
  corridor_id: string
  corridor_name: string
  port_name: string
  summary: string
  sections: DemoReportSection[]
  operational_importance?: string
  predicted_delay_sec?: number
  slot_recommendation_count?: number
  validation_passed?: boolean
}

export interface PredictionCheck {
  id: string
  label: string
  ok: boolean
  detail: string
}

export interface PredictionValidation {
  passed: boolean
  checks: PredictionCheck[]
  forecast_count: number
  peak_injected_delay_sec: number
  max_predicted_delay_sec: number
  predicted_at_horizon_30_sec: number
  operational_importance: string
  pulse_eligible: boolean
  horizons: Array<{
    horizon_minutes: number
    predicted_delay_sec: number
    method: string
    confidence: string
  }>
}

export interface PredictionStressResponse {
  ok: boolean
  corridor_id: string
  corridor_name?: string
  port_id?: string
  port_name?: string
  incident_cause?: string
  map_overlay: CrowdMapOverlayResponse
  operational_actions: OperationalActions
  slot_recommendations?: SlotRecommendationsResponse
  demo_report: DemoReport
  prediction_validation: PredictionValidation
  corridor_forecasts?: Array<Record<string, unknown>>
  at_risk_slot?: Record<string, unknown> | null
  max_predicted_delay_sec?: number
}

export interface MethodComparisonRow {
  horizon_minutes: number
  kafka_trend_sec: number | null
  ml_historical_sec: number | null
  kafka_available?: boolean
  ml_available?: boolean
  divergence_pct: number | null
  diverged: boolean
  divergence_expected?: boolean
}

export interface MethodComparison {
  passed: boolean
  checks: PredictionCheck[]
  comparisons: MethodComparisonRow[]
  divergence_threshold_pct: number
  diverged_horizons: number[]
  kafka_at_horizon_30_sec: number
}

export interface DecayPhase {
  operational_importance: string
  pulse_eligible: boolean
  predicted_at_horizon_30_sec: number
  max_predicted_delay_sec: number
  current_delay_sec: number
}

export interface DecayValidation {
  passed: boolean
  checks: PredictionCheck[]
  phase_spike: DecayPhase
  phase_recovery: DecayPhase
  pulse_min_delay_sec: number
}

export interface MlKafkaCompareResponse {
  ok: boolean
  corridor_id: string
  corridor_name?: string
  port_id?: string
  port_name?: string
  map_overlay: CrowdMapOverlayResponse
  operational_actions: OperationalActions
  slot_recommendations?: SlotRecommendationsResponse
  method_comparison: MethodComparison
  prediction_validation: PredictionValidation
}

export interface DecayRecoveryResponse {
  ok: boolean
  corridor_id: string
  corridor_name?: string
  port_id?: string
  port_name?: string
  map_overlay: CrowdMapOverlayResponse
  operational_actions: OperationalActions
  slot_recommendations?: SlotRecommendationsResponse
  decay_validation: DecayValidation
  demo_report: DemoReport
  prediction_validation: PredictionValidation
}

export async function triggerMlKafkaCompare(
  payload?: { port_id?: string; corridor_id?: string; peak_delay_sec?: number },
): Promise<MlKafkaCompareResponse> {
  const token = getStoredToken()
  const headers: Record<string, string> = { 'Content-Type': 'application/json' }
  if (token) {
    headers.Authorization = `Bearer ${token}`
  }
  const response = await fetch('/api/v1/demo/ml-kafka-compare', {
    method: 'POST',
    headers,
    body: JSON.stringify({
      ...(payload?.port_id ? { port_id: payload.port_id } : {}),
      ...(payload?.corridor_id ? { corridor_id: payload.corridor_id } : {}),
      peak_delay_sec: payload?.peak_delay_sec ?? 960,
    }),
  })
  if (!response.ok) {
    const body = (await response.json().catch(() => null)) as { detail?: string } | null
    throw new Error(body?.detail ?? `HTTP ${response.status}`)
  }
  return response.json() as Promise<MlKafkaCompareResponse>
}

export async function triggerDecayRecovery(
  payload?: { port_id?: string; corridor_id?: string; peak_delay_sec?: number },
): Promise<DecayRecoveryResponse> {
  const token = getStoredToken()
  const headers: Record<string, string> = { 'Content-Type': 'application/json' }
  if (token) {
    headers.Authorization = `Bearer ${token}`
  }
  const response = await fetch('/api/v1/demo/decay-recovery', {
    method: 'POST',
    headers,
    body: JSON.stringify({
      ...(payload?.port_id ? { port_id: payload.port_id } : {}),
      ...(payload?.corridor_id ? { corridor_id: payload.corridor_id } : {}),
      peak_delay_sec: payload?.peak_delay_sec ?? 960,
    }),
  })
  if (!response.ok) {
    const body = (await response.json().catch(() => null)) as { detail?: string } | null
    throw new Error(body?.detail ?? `HTTP ${response.status}`)
  }
  return response.json() as Promise<DecayRecoveryResponse>
}

export async function triggerPredictionStress(
  payload?: { port_id?: string; peak_delay_sec?: number; mark_slots_at_risk?: boolean },
): Promise<PredictionStressResponse> {
  const token = getStoredToken()
  const headers: Record<string, string> = { 'Content-Type': 'application/json' }
  if (token) {
    headers.Authorization = `Bearer ${token}`
  }
  const response = await fetch('/api/v1/demo/prediction-stress', {
    method: 'POST',
    headers,
    body: JSON.stringify({
      ...(payload?.port_id ? { port_id: payload.port_id } : {}),
      peak_delay_sec: payload?.peak_delay_sec ?? 1800,
      mark_slots_at_risk: payload?.mark_slots_at_risk ?? true,
    }),
  })
  if (!response.ok) {
    const body = (await response.json().catch(() => null)) as { detail?: string } | null
    throw new Error(body?.detail ?? `HTTP ${response.status}`)
  }
  return response.json() as Promise<PredictionStressResponse>
}

export async function fetchHealthVoice(): Promise<unknown> {
  try {
    const response = await fetch('/health')
    const contentType = response.headers.get('content-type') ?? ''
    if (!response.ok || !contentType.includes('application/json')) {
      return {
        error: `health_unavailable HTTP ${response.status}`,
        content_type: contentType,
      }
    }
    const body = (await response.json()) as { voice?: unknown }
    return body.voice ?? body
  } catch (error) {
    return {
      error: error instanceof Error ? error.message : String(error),
    }
  }
}

export async function triggerCorridorSpikeDemo(
  corridorId: string,
  payload?: { dry_run?: boolean; force?: boolean; phone_e164?: string },
): Promise<CorridorSpikeDemoResponse> {
  const token = getStoredToken()
  const headers: Record<string, string> = { 'Content-Type': 'application/json' }
  if (token) {
    headers.Authorization = `Bearer ${token}`
  }
  const response = await fetch('/api/v1/demo/corridor-spike', {
    method: 'POST',
    headers,
    body: JSON.stringify({
      corridor_id: corridorId,
      force: payload?.force ?? true,
      dry_run: payload?.dry_run ?? false,
      ...(payload?.phone_e164 ? { phone_e164: payload.phone_e164 } : {}),
    }),
  })
  if (!response.ok) {
    const body = (await response.json().catch(() => null)) as { detail?: string } | null
    throw new Error(body?.detail ?? `HTTP ${response.status}`)
  }
  return response.json() as Promise<CorridorSpikeDemoResponse>
}

export interface VoiceDemoCallResponse {
  ok: boolean
  call_sid: string
  to_number: string
  from_number: string
}

export async function triggerVoiceDemoCall(
  payload?: { to_number?: string; message?: string },
): Promise<VoiceDemoCallResponse> {
  const response = await fetch('/api/v1/voice/demo-call', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload ?? {}),
  })
  if (!response.ok) {
    const body = (await response.json().catch(() => null)) as { detail?: string } | null
    throw new Error(body?.detail ?? `HTTP ${response.status}`)
  }
  return response.json() as Promise<VoiceDemoCallResponse>
}
