import { useCallback, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { fetchCrowdMapOverlay } from '../services/trafficApi'
import type { CrowdMapOverlayResponse } from '../types/traffic'

type CrowdStatus = 'idle' | 'loading' | 'active' | 'error'

interface CrowdMapDemoButtonProps {
  selectedCorridorId: string | null
  selectedCorridorName: string | null
  activeOverlay: CrowdMapOverlayResponse | null
  onOverlayChange: (overlay: CrowdMapOverlayResponse | null) => void
}

export function CrowdMapDemoButton({
  selectedCorridorId,
  selectedCorridorName,
  activeOverlay,
  onOverlayChange,
}: CrowdMapDemoButtonProps) {
  const { t } = useTranslation()
  const [status, setStatus] = useState<CrowdStatus>('idle')
  const [detail, setDetail] = useState<string | null>(null)

  const isActive =
    activeOverlay !== null && activeOverlay.corridor_id === selectedCorridorId

  const handleClick = useCallback(async () => {
    if (!selectedCorridorId || status === 'loading') {
      return
    }

    if (isActive) {
      onOverlayChange(null)
      setStatus('idle')
      setDetail(null)
      return
    }

    setStatus('loading')
    setDetail(null)
    try {
      const overlay = await fetchCrowdMapOverlay(selectedCorridorId)
      onOverlayChange(overlay)
      setStatus('active')
    } catch (error) {
      setStatus('error')
      setDetail(error instanceof Error ? error.message : t('crowdDemo.error'))
      window.setTimeout(() => {
        setStatus('idle')
        setDetail(null)
      }, 6000)
    }
  }, [isActive, onOverlayChange, selectedCorridorId, status, t])

  const disabled = !selectedCorridorId || status === 'loading'

  const label = !selectedCorridorId
    ? t('crowdDemo.selectCorridor')
    : status === 'loading'
      ? t('crowdDemo.loading')
      : isActive
        ? t('crowdDemo.hide')
        : status === 'error'
          ? t('crowdDemo.error')
          : t('crowdDemo.show')

  const title = !selectedCorridorId
    ? t('crowdDemo.selectCorridorHint')
    : detail ??
      t('crowdDemo.buttonHint', {
        corridor: selectedCorridorName ?? selectedCorridorId,
      })

  return (
    <div className="voice-demo">
      <button
        type="button"
        className={`voice-demo__btn crowd-demo__btn${status === 'loading' ? ' voice-demo__btn--busy' : ''}${isActive ? ' crowd-demo__btn--active' : ''}${status === 'error' ? ' voice-demo__btn--error' : ''}${disabled ? ' voice-demo__btn--disabled' : ''}`}
        onClick={() => void handleClick()}
        disabled={disabled}
        title={title}
      >
        {label}
      </button>
    </div>
  )
}
