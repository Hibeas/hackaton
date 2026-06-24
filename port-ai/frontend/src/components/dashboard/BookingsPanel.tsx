import { useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { cancelMyBooking, rescheduleMyBooking } from '../../services/tmsApi'
import type { TmsBooking } from '../../types/tms'

interface BookingsPanelProps {
  bookings: TmsBooking[]
  total: number
  isLoading: boolean
  error: string | null
  onRefresh: () => void
  onSelectCorridor?: (corridorId: string) => void
}

const RESCHEDULE_OFFSETS = [30, 60, 120] as const

function statusClass(status: string): string {
  if (status === 'at_risk') return 'booking-card--at-risk'
  if (status === 'confirmed') return 'booking-card--confirmed'
  if (status === 'completed') return 'booking-card--completed'
  return 'booking-card--default'
}

function toDatetimeLocalValue(iso: string): string {
  const date = new Date(iso)
  const pad = (value: number) => String(value).padStart(2, '0')
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}T${pad(date.getHours())}:${pad(date.getMinutes())}`
}

function formatTimeParts(booking: TmsBooking): { start: string; end: string; date: string } {
  const start = new Date(booking.window_start)
  const end = new Date(booking.window_end)
  const time = { hour: '2-digit', minute: '2-digit' } as const
  return {
    start: start.toLocaleTimeString(undefined, time),
    end: end.toLocaleTimeString(undefined, time),
    date: start.toLocaleDateString(undefined, { weekday: 'short', day: '2-digit', month: 'short' }),
  }
}

function BookingCard({
  booking,
  onSelectCorridor,
  onActionComplete,
}: {
  booking: TmsBooking
  onSelectCorridor?: (corridorId: string) => void
  onActionComplete: () => void
}) {
  const { t } = useTranslation()
  const primaryCorridor = booking.corridor_ids[0]
  const [busyAction, setBusyAction] = useState<string | null>(null)
  const [actionError, setActionError] = useState<string | null>(null)
  const [customOpen, setCustomOpen] = useState(false)
  const [customValue, setCustomValue] = useState(() => toDatetimeLocalValue(booking.window_start))
  const canManage = booking.status === 'confirmed' || booking.status === 'at_risk'
  const timeParts = useMemo(() => formatTimeParts(booking), [booking.window_start, booking.window_end])

  const portLabel = t(`bookings.ports.${booking.port_id}`, { defaultValue: booking.port_id })

  const runAction = async (key: string, action: () => Promise<void>) => {
    setBusyAction(key)
    setActionError(null)
    try {
      await action()
      onActionComplete()
    } catch (err) {
      setActionError(err instanceof Error ? err.message : 'booking_action_failed')
    } finally {
      setBusyAction(null)
    }
  }

  return (
    <article className={`booking-card ${statusClass(booking.status)}`}>
      <div className="booking-card__main">
        <header className="booking-card__top">
          <div className="booking-card__identity">
            <span className="booking-card__terminal">{booking.terminal_code}</span>
            <h4 className="booking-card__title">{booking.terminal_label}</h4>
          </div>
          <span className={`booking-card__status booking-card__status--${booking.status}`}>
            {t(`bookings.status.${booking.status}`, { defaultValue: booking.status })}
          </span>
        </header>

        <div className="booking-card__schedule">
          <p className="booking-card__time">
            <span className="booking-card__time-start">{timeParts.start}</span>
            <span className="booking-card__time-sep">–</span>
            <span className="booking-card__time-end">{timeParts.end}</span>
          </p>
          <p className="booking-card__date">{timeParts.date}</p>
        </div>

        <ul className="booking-card__meta-list">
          <li>
            <span className="booking-card__meta-label">{t('bookings.ref')}</span>
            <span className="booking-card__meta-value">{booking.booking_ref}</span>
          </li>
          <li>
            <span className="booking-card__meta-label">{t('bookings.port')}</span>
            <span className="booking-card__meta-value">{portLabel}</span>
          </li>
          <li>
            <span className="booking-card__meta-label">{t('bookings.containers')}</span>
            <span className="booking-card__meta-value">{booking.container_count}</span>
          </li>
          {booking.call ? (
            <li>
              <span className="booking-card__meta-label">{t('bookings.call')}</span>
              <span className="booking-card__meta-value booking-card__meta-value--call">
                {t(`bookings.callStatus.${booking.call.status}`, { defaultValue: booking.call.status })}
              </span>
            </li>
          ) : null}
        </ul>
      </div>

      {canManage ? (
        <div className="booking-card__manage">
          <p className="booking-card__manage-title">{t('bookings.rescheduleLabel')}</p>

          <div className="booking-card__presets">
            {RESCHEDULE_OFFSETS.map((minutes) => (
              <button
                key={minutes}
                type="button"
                className="booking-card__preset"
                disabled={busyAction !== null}
                onClick={() => {
                  void runAction(`reschedule-${minutes}`, async () => {
                    await rescheduleMyBooking(booking.provider_id, booking.slot_id, {
                      offset_minutes: minutes,
                    })
                  })
                }}
              >
                {busyAction === `reschedule-${minutes}`
                  ? t('bookings.working')
                  : t(`bookings.reschedule.${minutes}`)}
              </button>
            ))}
            <button
              type="button"
              className={`booking-card__preset booking-card__preset--custom${customOpen ? ' booking-card__preset--active' : ''}`}
              disabled={busyAction !== null}
              onClick={() => setCustomOpen((open) => !open)}
            >
              {t('bookings.customToggle')}
            </button>
          </div>

          {customOpen ? (
            <div className="booking-card__custom">
              <label className="booking-card__custom-label" htmlFor={`custom-time-${booking.slot_id}`}>
                {t('bookings.customLabel')}
              </label>
              <div className="booking-card__custom-row">
                <input
                  id={`custom-time-${booking.slot_id}`}
                  type="datetime-local"
                  className="booking-card__custom-input"
                  value={customValue}
                  disabled={busyAction !== null}
                  onChange={(event) => setCustomValue(event.target.value)}
                />
                <button
                  type="button"
                  className="booking-card__custom-apply"
                  disabled={busyAction !== null || !customValue}
                  onClick={() => {
                    void runAction('reschedule-custom', async () => {
                      const parsed = new Date(customValue)
                      if (Number.isNaN(parsed.getTime())) {
                        throw new Error('invalid_custom_datetime')
                      }
                      await rescheduleMyBooking(booking.provider_id, booking.slot_id, {
                        window_start_at: parsed.toISOString(),
                      })
                      setCustomOpen(false)
                    })
                  }}
                >
                  {busyAction === 'reschedule-custom' ? t('bookings.working') : t('bookings.customApply')}
                </button>
              </div>
            </div>
          ) : null}

          {actionError ? (
            <p className="booking-card__error">
              {t(`bookings.errors.${actionError}`, { defaultValue: actionError })}
            </p>
          ) : null}
        </div>
      ) : null}

      <footer className="booking-card__footer">
        {primaryCorridor && onSelectCorridor ? (
          <button
            type="button"
            className="booking-card__map-btn"
            onClick={() => onSelectCorridor(primaryCorridor)}
          >
            {t('bookings.showOnMap')}
          </button>
        ) : (
          <span />
        )}
        {canManage ? (
          <button
            type="button"
            className="booking-card__cancel-btn"
            disabled={busyAction !== null}
            onClick={() => {
              void runAction('cancel', async () => {
                await cancelMyBooking(booking.provider_id, booking.slot_id)
              })
            }}
          >
            {busyAction === 'cancel' ? t('bookings.working') : t('bookings.cancel')}
          </button>
        ) : null}
      </footer>
    </article>
  )
}

export function BookingsPanel({
  bookings,
  total,
  isLoading,
  error,
  onRefresh,
  onSelectCorridor,
}: BookingsPanelProps) {
  const { t } = useTranslation()
  const atRiskCount = bookings.filter((item) => item.status === 'at_risk').length

  return (
    <div className="dash-panel bookings-panel">
      <section className="dash-section">
        <div className="bookings-panel__header">
          <div className="bookings-panel__title-block">
            <span
              className={`dash-section__count${atRiskCount > 0 ? ' dash-section__count--alert' : ''}`}
            >
              {total}
            </span>
            <div>
              <h3 className="dash-section__title">{t('bookings.title')}</h3>
              <p className="bookings-panel__subtitle">{t('bookings.summary')}</p>
            </div>
          </div>
          <button type="button" className="bookings-panel__refresh" onClick={onRefresh} disabled={isLoading}>
            {isLoading ? t('bookings.refreshing') : t('bookings.refresh')}
          </button>
        </div>

        {atRiskCount > 0 ? (
          <p className="bookings-panel__alert">{t('bookings.atRiskSummary', { count: atRiskCount })}</p>
        ) : null}

        {error ? (
          <p className="bookings-panel__error">{t(`bookings.errors.${error}`, { defaultValue: error })}</p>
        ) : null}

        <div className="booking-list">
          {bookings.length === 0 && !isLoading ? (
            <p className="dash-empty">{t('bookings.empty')}</p>
          ) : (
            bookings.map((booking) => (
              <BookingCard
                key={`${booking.slot_id}-${booking.booking_ref}`}
                booking={booking}
                onSelectCorridor={onSelectCorridor}
                onActionComplete={onRefresh}
              />
            ))
          )}
        </div>
      </section>
    </div>
  )
}
