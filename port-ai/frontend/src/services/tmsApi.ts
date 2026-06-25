import { getStoredToken } from './authStorage'
import type {
  DispatchAuditResponse,
  MyBookingsResponse,
  SlotRecommendationsResponse,
} from '../types/tms'

async function readApiError(response: Response): Promise<string> {
  const body = (await response.json().catch(() => null)) as { detail?: string } | null
  return body?.detail ?? `HTTP ${response.status}`
}

export async function fetchMyBookings(): Promise<MyBookingsResponse> {
  const token = getStoredToken()
  const headers: Record<string, string> = {}
  if (token) {
    headers.Authorization = `Bearer ${token}`
  }
  const response = await fetch('/api/v1/tms/my-bookings', { headers })
  if (!response.ok) {
    throw new Error(await readApiError(response))
  }
  return response.json() as Promise<MyBookingsResponse>
}

export async function cancelMyBooking(providerId: string, slotId: string): Promise<{ ok: boolean }> {
  const token = getStoredToken()
  const headers: Record<string, string> = {}
  if (token) {
    headers.Authorization = `Bearer ${token}`
  }
  const response = await fetch(
    `/api/v1/tms/my-bookings/${encodeURIComponent(providerId)}/${encodeURIComponent(slotId)}/cancel`,
    { method: 'POST', headers },
  )
  if (!response.ok) {
    throw new Error(await readApiError(response))
  }
  return response.json() as Promise<{ ok: boolean }>
}

export type RescheduleBookingPayload =
  | { offset_minutes: number }
  | { window_start_at: string }

export async function rescheduleMyBooking(
  providerId: string,
  slotId: string,
  payload: RescheduleBookingPayload,
): Promise<{ ok: boolean; window_local?: string }> {
  const token = getStoredToken()
  const headers: Record<string, string> = { 'Content-Type': 'application/json' }
  if (token) {
    headers.Authorization = `Bearer ${token}`
  }
  const response = await fetch(
    `/api/v1/tms/my-bookings/${encodeURIComponent(providerId)}/${encodeURIComponent(slotId)}/reschedule`,
    {
      method: 'POST',
      headers,
      body: JSON.stringify(payload),
    },
  )
  if (!response.ok) {
    throw new Error(await readApiError(response))
  }
  return response.json() as Promise<{ ok: boolean; window_local?: string }>
}

export async function fetchSlotRecommendations(
  corridorId: string,
  predictedDelaySec: number,
  limit = 3,
): Promise<SlotRecommendationsResponse> {
  const params = new URLSearchParams({
    corridor_id: corridorId,
    predicted_delay_sec: String(predictedDelaySec),
    limit: String(limit),
  })
  const response = await fetch(`/api/v1/tms/recommend-slots?${params}`)
  if (!response.ok) {
    throw new Error(await readApiError(response))
  }
  return response.json() as Promise<SlotRecommendationsResponse>
}

export async function fetchDispatchAudit(limit = 40): Promise<DispatchAuditResponse> {
  const response = await fetch(`/api/v1/tms/dispatch/audit?limit=${limit}`)
  if (!response.ok) {
    throw new Error(await readApiError(response))
  }
  return response.json() as Promise<DispatchAuditResponse>
}
