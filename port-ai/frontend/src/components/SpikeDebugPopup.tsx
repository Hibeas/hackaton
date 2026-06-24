import type { CorridorSpikeDemoResponse } from '../services/trafficApi'

interface SpikeDebugPopupProps {
  open: boolean
  title: string
  payload: unknown
  error: string | null
  onClose: () => void
}

export function SpikeDebugPopup({ open, title, payload, error, onClose }: SpikeDebugPopupProps) {
  if (!open) {
    return null
  }

  const text = error ?? JSON.stringify(payload, null, 2)

  return (
    <div className="spike-debug-backdrop" role="presentation" onClick={onClose}>
      <div
        className="spike-debug-popup"
        role="dialog"
        aria-labelledby="spike-debug-title"
        onClick={(event) => event.stopPropagation()}
      >
        <header className="spike-debug-popup__header">
          <h2 id="spike-debug-title">{title}</h2>
          <button type="button" className="spike-debug-popup__close" onClick={onClose}>
            ×
          </button>
        </header>
        <pre className="spike-debug-popup__body">{text}</pre>
      </div>
    </div>
  )
}

export function buildSpikeDebugPayload(
  response: CorridorSpikeDemoResponse | null,
  extras: {
    corridorId: string
    userPhone: string | null
    healthVoice?: unknown
  },
): Record<string, unknown> {
  return {
    request: {
      corridor_id: extras.corridorId,
      user_phone_e164: extras.userPhone,
      note: 'Spike używa VOICE_CALL_DEMO_TO z backend/.env (nie telefonu z profilu)',
      dry_run_sent: false,
    },
    response,
    health_voice: extras.healthVoice ?? null,
    call_summary: summarizeCalls(response),
  }
}

function summarizeCalls(response: CorridorSpikeDemoResponse | null): string {
  const calls = response?.dispatch?.calls ?? []
  if (calls.length === 0) {
    return 'Brak wpisów calls — sprawdź alert_count i slot at_risk'
  }
  return calls
    .map((call) => {
      const parts = [call.status ?? '?']
      if (call.phone) parts.push(String(call.phone))
      if (call.booking_ref) parts.push(String(call.booking_ref))
      if (call.error) {
        const err = String(call.error)
        if (err.includes('unverified') || err.includes('Trial accounts')) {
          parts.push('TWILIO TRIAL: zweryfikuj numer w console.twilio.com → Verified Caller IDs')
        } else {
          parts.push(err)
        }
      }
      if (call.call_sid) parts.push(String(call.call_sid))
      return parts.join(' | ')
    })
    .join('\n')
}
