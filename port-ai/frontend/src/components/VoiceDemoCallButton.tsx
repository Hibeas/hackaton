import { useCallback, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { triggerVoiceDemoCall } from '../services/trafficApi'

type VoiceCallStatus = 'idle' | 'calling' | 'success' | 'error'

function voiceErrorMessage(code: string, t: (key: string) => string): string {
  if (code === 'voice_not_configured') {
    return t('voice.errorNotConfigured')
  }
  if (code === 'voice_demo_to_missing') {
    return t('voice.errorNoNumber')
  }
  if (code.includes('ElevenLabs') || code.includes('Twilio') || code === 'voice_call_failed') {
    return t('voice.errorProvider')
  }
  return code
}

export function VoiceDemoCallButton() {
  const { t } = useTranslation()
  const [status, setStatus] = useState<VoiceCallStatus>('idle')
  const [detail, setDetail] = useState<string | null>(null)

  const handleClick = useCallback(async () => {
    if (status === 'calling') {
      return
    }
    setStatus('calling')
    setDetail(null)
    try {
      const result = await triggerVoiceDemoCall({ message: t('voice.demoMessage') })
      setStatus('success')
      setDetail(result.call_sid)
      window.setTimeout(() => {
        setStatus('idle')
        setDetail(null)
      }, 8000)
    } catch (error) {
      setStatus('error')
      setDetail(error instanceof Error ? voiceErrorMessage(error.message, t) : t('voice.callError'))
      window.setTimeout(() => {
        setStatus('idle')
        setDetail(null)
      }, 8000)
    }
  }, [status, t])

  const label =
    status === 'calling'
      ? t('voice.calling')
      : status === 'success'
        ? t('voice.callOk')
        : status === 'error'
          ? t('voice.callError')
          : t('voice.demoCall')

  return (
    <div className="voice-demo">
      <button
        type="button"
        className={`voice-demo__btn${status === 'calling' ? ' voice-demo__btn--busy' : ''}${status === 'error' ? ' voice-demo__btn--error' : ''}${status === 'success' ? ' voice-demo__btn--ok' : ''}`}
        onClick={() => void handleClick()}
        disabled={status === 'calling'}
        title={detail ?? t('voice.demoCallHint')}
      >
        {label}
      </button>
    </div>
  )
}
