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

export interface CorridorSpikeDemoResponse {
  ok: boolean
  corridor_id: string
  max_predicted_delay_sec?: number
  dispatch?: {
    alert_count?: number
    calls?: Array<{ status?: string; call_sid?: string }>
  }
}

export async function triggerCorridorSpikeDemo(
  corridorId: string,
  payload?: { dry_run?: boolean; force?: boolean },
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
      dry_run: payload?.dry_run ?? true,
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
