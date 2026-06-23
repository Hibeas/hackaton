import { useCallback, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { triggerCorridorSpikeDemo } from '../services/trafficApi'

type SpikeStatus = 'idle' | 'running' | 'success' | 'error'

function spikeErrorMessage(code: string, t: (key: string) => string): string {
  if (code === 'voice_not_configured') {
    return t('spikeDemo.errorNotConfigured')
  }
  if (code.startsWith('corridor_not_found')) {
    return t('spikeDemo.errorCorridorNotFound')
  }
  if (code.includes('ElevenLabs') || code.includes('Twilio') || code === 'voice_call_failed') {
    return t('spikeDemo.errorProvider')
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
  const [status, setStatus] = useState<SpikeStatus>('idle')
  const [detail, setDetail] = useState<string | null>(null)

  const handleClick = useCallback(async () => {
    if (!selectedCorridorId || status === 'running') {
      return
    }
    setStatus('running')
    setDetail(null)
    try {
      await triggerCorridorSpikeDemo(selectedCorridorId)
      setStatus('success')
      onComplete?.()
      window.setTimeout(() => {
        setStatus('idle')
        setDetail(null)
      }, 8000)
    } catch (error) {
      setStatus('error')
      setDetail(
        error instanceof Error ? spikeErrorMessage(error.message, t) : t('spikeDemo.error'),
      )
      window.setTimeout(() => {
        setStatus('idle')
        setDetail(null)
      }, 8000)
    }
  }, [onComplete, selectedCorridorId, status, t])

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
    </div>
  )
}
