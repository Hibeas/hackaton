import { useCallback, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { fetchHealthVoice, triggerCorridorSpikeDemo } from '../services/trafficApi'
import { useAuth } from '../context/AuthContext'
import { buildSpikeDebugPayload, SpikeDebugPopup } from './SpikeDebugPopup'

type SpikeStatus = 'idle' | 'running' | 'success' | 'error'

function spikeErrorMessage(code: string, t: (key: string) => string): string {
  if (code === 'voice_not_configured') {
    return t('spikeDemo.errorNotConfigured')
  }
  if (code === 'voice_demo_to_missing') {
    return t('spikeDemo.errorNoPhone')
  }
  if (code.startsWith('corridor_not_found')) {
    return t('spikeDemo.errorCorridorNotFound')
  }
  if (code.includes('unverified') || code.includes('Trial accounts')) {
    return t('spikeDemo.errorTwilioTrial')
  }
  return code
}

interface CorridorSpikeDemoButtonProps {
  selectedCorridorId: string | null
  selectedCorridorName: string | null
  onComplete?: () => void
}

export function CorridorSpikeDemoButton({
  selectedCorridorId,
  selectedCorridorName,
  onComplete,
}: CorridorSpikeDemoButtonProps) {
  const { t } = useTranslation()
  const { user } = useAuth()
  const [status, setStatus] = useState<SpikeStatus>('idle')
  const [detail, setDetail] = useState<string | null>(null)
  const [debugOpen, setDebugOpen] = useState(false)
  const [debugPayload, setDebugPayload] = useState<unknown>(null)
  const [debugError, setDebugError] = useState<string | null>(null)

  const handleClick = useCallback(async () => {
    if (!selectedCorridorId || status === 'running') {
      return
    }
    setStatus('running')
    setDetail(null)
    setDebugError(null)
    try {
      const [healthVoice, response] = await Promise.all([
        fetchHealthVoice(),
        triggerCorridorSpikeDemo(selectedCorridorId),
      ])
      setDebugPayload(
        buildSpikeDebugPayload(response, {
          corridorId: selectedCorridorId,
          userPhone: user?.phone_e164 ?? null,
          healthVoice,
        }),
      )
      setDebugOpen(true)
      const called = response.dispatch?.calls?.some((item) => item.status === 'called')
      setStatus(called ? 'success' : 'error')
      setDetail(called ? t('spikeDemo.ok') : t('spikeDemo.noCall'))
      onComplete?.()
    } catch (error) {
      const message =
        error instanceof Error ? spikeErrorMessage(error.message, t) : t('spikeDemo.error')
      setStatus('error')
      setDetail(message)
      setDebugError(
        JSON.stringify(
          {
            error: error instanceof Error ? error.message : String(error),
            corridor_id: selectedCorridorId,
            user_phone_e164: user?.phone_e164 ?? null,
          },
          null,
          2,
        ),
      )
      setDebugOpen(true)
    }
  }, [onComplete, selectedCorridorId, status, t, user?.phone_e164])

  const disabled = !selectedCorridorId || status === 'running'

  const label = !selectedCorridorId
    ? t('spikeDemo.selectCorridor')
    : status === 'running'
      ? t('spikeDemo.running')
      : status === 'success'
        ? t('spikeDemo.ok')
        : status === 'error'
          ? t('spikeDemo.error')
          : t('spikeDemo.button')

  const title = !selectedCorridorId
    ? t('spikeDemo.selectCorridorHint')
    : detail ??
      t('spikeDemo.buttonHint', {
        corridor: selectedCorridorName ?? selectedCorridorId,
      })

  return (
    <div className="voice-demo">
      <button
        type="button"
        className={`voice-demo__btn${status === 'running' ? ' voice-demo__btn--busy' : ''}${status === 'error' ? ' voice-demo__btn--error' : ''}${status === 'success' ? ' voice-demo__btn--ok' : ''}${disabled ? ' voice-demo__btn--disabled' : ''}`}
        onClick={() => void handleClick()}
        disabled={disabled}
        title={title}
      >
        {label}
      </button>
      <SpikeDebugPopup
        open={debugOpen}
        title={t('spikeDemo.debugTitle')}
        payload={debugPayload}
        error={debugError}
        onClose={() => setDebugOpen(false)}
      />
    </div>
  )
}
