import { useTranslation } from 'react-i18next'
import { useSlotRecommendations } from '../../hooks/useSlotRecommendations'

interface CorridorSlotSuggestionProps {
  corridorId: string | null
  corridorName: string | null
  predictedDelaySec: number | null
  liveDelaySec: number
  hasActiveAlert: boolean
}

/** Gate-slot ideas shown only under corridors, for elevated / extraordinary traffic. */
export function CorridorSlotSuggestion({
  corridorId,
  corridorName,
  predictedDelaySec,
  liveDelaySec,
  hasActiveAlert,
}: CorridorSlotSuggestionProps) {
  const { t } = useTranslation()

  const isExtraordinary =
    hasActiveAlert ||
    liveDelaySec >= 180 ||
    (predictedDelaySec ?? 0) >= 480

  const { data, isLoading, error } = useSlotRecommendations(
    corridorId,
    predictedDelaySec ?? liveDelaySec,
    Boolean(corridorId && isExtraordinary),
  )

  if (!corridorId) {
    return null
  }

  return (
    <section className="corridor-slot-suggestion" aria-labelledby="corridor-slot-suggestion-title">
      <header className="corridor-slot-suggestion__head">
        <h4 id="corridor-slot-suggestion-title">{t('slotRecommend.suggestionTitle')}</h4>
        <span className="corridor-slot-suggestion__tag">{t('slotRecommend.extraordinaryTag')}</span>
      </header>
      <p className="corridor-slot-suggestion__intro">
        {t('slotRecommend.suggestionIntro', { corridor: corridorName ?? corridorId })}
      </p>

      {!isExtraordinary ? (
        <p className="corridor-slot-suggestion__idle">{t('slotRecommend.suggestionIdle')}</p>
      ) : null}

      {isExtraordinary && isLoading ? (
        <p className="corridor-slot-suggestion__hint">{t('slotRecommend.loading')}</p>
      ) : null}
      {isExtraordinary && error ? (
        <p className="corridor-slot-suggestion__error">{t('slotRecommend.error')}</p>
      ) : null}

      {isExtraordinary && !isLoading && !error && data?.recommendations.length === 0 ? (
        <p className="corridor-slot-suggestion__hint">{t('slotRecommend.empty')}</p>
      ) : null}

      {isExtraordinary && data?.recommendations.length ? (
        <ul className="corridor-slot-suggestion__list">
          {data.recommendations.map((item) => (
            <li key={`${item.provider_id}-${item.slot_id}`}>
              <strong>
                {item.terminal_label} · {item.window_local}
              </strong>
              <span>
                {t(`slotRecommend.reason.${item.reason_key}`)} ·{' '}
                {t('slotRecommend.slack', { minutes: item.slack_minutes })}
              </span>
            </li>
          ))}
        </ul>
      ) : null}
    </section>
  )
}
