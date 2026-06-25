import { useTranslation } from 'react-i18next'
import { useSlotRecommendations } from '../../hooks/useSlotRecommendations'
import type { SlotRecommendation } from '../../types/tms'

interface SlotRecommendationPanelProps {
  corridorId: string | null
  corridorName?: string | null
  predictedDelaySec: number | null
  enabled?: boolean
  compact?: boolean
  onApplySlot?: (recommendation: SlotRecommendation) => void
}

export function SlotRecommendationPanel({
  corridorId,
  corridorName,
  predictedDelaySec,
  enabled = true,
  compact = false,
  onApplySlot,
}: SlotRecommendationPanelProps) {
  const { t } = useTranslation()
  const { data, isLoading, error } = useSlotRecommendations(
    corridorId,
    predictedDelaySec,
    enabled && Boolean(corridorId),
  )

  if (!corridorId) {
    return compact ? null : (
      <p className="slot-rec__hint">{t('slotRecommend.selectCorridor')}</p>
    )
  }

  return (
    <section className={`slot-rec${compact ? ' slot-rec--compact' : ''}`}>
      <header className="slot-rec__head">
        <h4>{t('slotRecommend.title')}</h4>
        {!compact && corridorName ? (
          <span className="slot-rec__context">{corridorName}</span>
        ) : null}
      </header>

      {isLoading ? <p className="slot-rec__hint">{t('slotRecommend.loading')}</p> : null}
      {error ? <p className="slot-rec__error">{t('slotRecommend.error')}</p> : null}

      {!isLoading && !error && data?.recommendations.length === 0 ? (
        <p className="slot-rec__hint">{t('slotRecommend.empty')}</p>
      ) : null}

      {data?.recommendations.length ? (
        <ul className="slot-rec__list">
          {data.recommendations.map((item) => (
            <li key={`${item.provider_id}-${item.slot_id}`} className="slot-rec__item">
              <div className="slot-rec__item-main">
                <strong>
                  {item.terminal_label} · {item.window_local}
                </strong>
                <span className="slot-rec__meta">
                  {t(`slotRecommend.reason.${item.reason_key}`)} ·{' '}
                  {t('slotRecommend.slack', { minutes: item.slack_minutes })}
                </span>
              </div>
              {onApplySlot ? (
                <button
                  type="button"
                  className="slot-rec__apply"
                  onClick={() => onApplySlot(item)}
                >
                  {t('slotRecommend.apply')}
                </button>
              ) : null}
            </li>
          ))}
        </ul>
      ) : null}
    </section>
  )
}
