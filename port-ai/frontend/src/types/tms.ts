export interface TmsBookingCall {
  status: string
  call_sid?: string | null
  phone_e164?: string | null
  created_at?: string | null
  answered_at?: string | null
}

export interface TmsBooking {
  slot_id: string
  booking_ref: string
  provider_id: string
  terminal_code: string
  terminal_label: string
  port_id: string
  window_start: string
  window_end: string
  window_local: string
  status: string
  at_risk_since?: string | null
  container_count: number
  corridor_ids: string[]
  spedition_id?: string | null
  company_name?: string | null
  contact_name?: string | null
  phone_e164?: string | null
  call?: TmsBookingCall | null
}

export interface MyBookingsResponse {
  user_id: string
  generated_at: string
  day: string
  total: number
  at_risk_count: number
  bookings: TmsBooking[]
}

export interface SlotRecommendation {
  slot_id: string
  provider_id: string
  terminal_code: string
  terminal_label: string
  port_id: string
  booking_ref: string
  status: string
  window_start: string
  window_end: string
  window_local: string
  window_date_local: string
  minutes_until: number
  slack_minutes: number
  score: number
  reason_key: 'comfortable' | 'tight' | 'at_risk'
}

export interface SlotRecommendationsResponse {
  corridor_id: string
  generated_at: string
  predicted_delay_sec: number
  buffer_sec: number
  earliest_arrival_at: string
  recommendation_count: number
  recommendations: SlotRecommendation[]
}

export interface DispatchAuditEntry {
  at: string
  event: string
  [key: string]: unknown
}

export interface DispatchAuditResponse {
  entries: DispatchAuditEntry[]
}
