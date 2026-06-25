import { createPortal } from 'react-dom'
import { useTranslation } from 'react-i18next'
import type {
  DecayValidation,
  DemoReport,
  MethodComparison,
  OperationalActions,
  PredictionValidation,
} from '../services/trafficApi'
import type { SlotRecommendation } from '../types/tms'

type DemoScenario = 'incident' | 'stress' | 'ml_kafka' | 'decay'

interface DemoActionPlanProps {
  open: boolean
  onClose: () => void
  corridorName: string
  scenario: DemoScenario
  voiceRequested?: boolean
  operationalActions: OperationalActions | null
  slotRecommendations?: SlotRecommendation[]
  callSummary?: string | null
  demoReport?: DemoReport | null
  predictionValidation?: PredictionValidation | null
  methodComparison?: MethodComparison | null
  decayValidation?: DecayValidation | null
  technicalPayload?: unknown
  technicalError?: string | null
}

function formatDelaySec(
  sec: number | null | undefined,
  t: (key: string, opts?: Record<string, unknown>) => string,
  available = true,
): string {
  if (!available || sec == null) {
    return t('demoAction.delayUnavailable')
  }
  if (sec < 60) {
    return t('demoAction.delaySeconds', { sec })
  }
  const minutes = Math.round(sec / 60)
  return t('demoAction.delayMinutes', { min: minutes })
}

function scenarioTitleKey(scenario: DemoScenario): string {
  switch (scenario) {
    case 'stress':
      return 'demoAction.stressTitle'
    case 'ml_kafka':
      return 'demoAction.mlKafkaTitle'
    case 'decay':
      return 'demoAction.decayTitle'
    default:
      return 'demoAction.title'
  }
}

function validationBadgeLabel(
  scenario: DemoScenario,
  passed: boolean | undefined,
  t: (key: string) => string,
): string {
  if (scenario === 'ml_kafka') {
    return passed ? t('demoAction.mlKafkaPassed') : t('demoAction.mlKafkaFailed')
  }
  if (scenario === 'decay') {
    return passed ? t('demoAction.decayPassedBadge') : t('demoAction.decayFailedBadge')
  }
  return passed ? t('demoAction.stressPassed') : t('demoAction.stressFailed')
}

function validationSectionTitle(scenario: DemoScenario): string {
  switch (scenario) {
    case 'ml_kafka':
      return 'demoAction.mlKafkaValidationTitle'
    case 'decay':
      return 'demoAction.decayValidationTitle'
    default:
      return 'demoAction.stressValidationTitle'
  }
}

export function DemoActionPlan({
  open,
  onClose,
  corridorName,
  scenario,
  voiceRequested = false,
  operationalActions,
  slotRecommendations = [],
  callSummary,
  demoReport,
  predictionValidation,
  methodComparison,
  decayValidation,
  technicalPayload,
  technicalError,
}: DemoActionPlanProps) {
  const { t } = useTranslation()

  if (!open || !operationalActions) {
    return null
  }

  const altSlots =
    slotRecommendations.length > 0
      ? slotRecommendations
      : operationalActions.slot_recommendations ?? []

  const validationPassed =
    scenario === 'ml_kafka'
      ? methodComparison?.passed
      : scenario === 'decay'
        ? decayValidation?.passed
        : predictionValidation?.passed

  const showValidationBadge = scenario === 'stress' || scenario === 'ml_kafka' || scenario === 'decay'
  const validationChecks =
    scenario === 'ml_kafka'
      ? methodComparison?.checks
      : scenario === 'decay'
        ? decayValidation?.checks
        : predictionValidation?.checks

  const content = (
    <div className="demo-action-backdrop" role="presentation" onClick={onClose}>
      <div
        className="demo-action-plan"
        role="dialog"
        aria-labelledby="demo-action-title"
        onClick={(event) => event.stopPropagation()}
      >
        <header className="demo-action-plan__header">
          <div className="demo-action-plan__title-row">
            <h2 id="demo-action-title">
              {corridorName} · {t(scenarioTitleKey(scenario))}
            </h2>
            {showValidationBadge ? (
              <span
                className={`demo-action-plan__badge demo-action-plan__badge--stress${
                  validationPassed
                    ? scenario === 'ml_kafka'
                      ? ' demo-action-plan__badge--ml-kafka-ok'
                      : ' demo-action-plan__badge--stress-ok'
                    : ' demo-action-plan__badge--stress-fail'
                }`}
              >
                {validationBadgeLabel(scenario, validationPassed, t)}
              </span>
            ) : (
              <span className="demo-action-plan__badge demo-action-plan__badge--backtest">
                {voiceRequested ? t('demoAction.incidentVoiceBadge') : t('demoAction.incidentBadge')}
              </span>
            )}
          </div>
          <button type="button" className="demo-action-plan__close" onClick={onClose}>
            ×
          </button>
        </header>

        {methodComparison ? (
          <section className="demo-action-plan__comparison">
            <h3>{t('demoAction.mlKafkaTableTitle')}</h3>
            <p className="demo-action-plan__comparison-hint">{t('demoAction.mlKafkaExplain')}</p>
            <p className="demo-action-plan__validation-summary">
              {t('demoAction.mlKafkaSummary', {
                threshold: methodComparison.divergence_threshold_pct,
                diverged: methodComparison.diverged_horizons.join(', ') || '—',
              })}
            </p>
            <table className="demo-action-plan__compare-table">
              <thead>
                <tr>
                  <th>{t('demoAction.horizonCol')}</th>
                  <th>kafka_trend</th>
                  <th>ml_historical</th>
                  <th>{t('demoAction.divergenceCol')}</th>
                </tr>
              </thead>
              <tbody>
                {methodComparison.comparisons.map((row) => {
                  const expected = row.divergence_expected ?? (row.diverged && scenario === 'ml_kafka')
                  const rowClass = row.diverged
                    ? expected
                      ? 'demo-action-plan__compare-row--expected'
                      : 'demo-action-plan__compare-row--diverged'
                    : undefined
                  return (
                    <tr key={row.horizon_minutes} className={rowClass}>
                      <td>{row.horizon_minutes} min</td>
                      <td>{formatDelaySec(row.kafka_trend_sec, t, row.kafka_available ?? row.kafka_trend_sec != null)}</td>
                      <td>{formatDelaySec(row.ml_historical_sec, t, row.ml_available ?? row.ml_historical_sec != null)}</td>
                      <td>
                        {row.divergence_pct != null ? `${row.divergence_pct}%` : '—'}
                        {row.diverged ? (
                          <span
                            className={
                              expected
                                ? 'demo-action-plan__divergence-tag demo-action-plan__divergence-tag--expected'
                                : 'demo-action-plan__divergence-tag demo-action-plan__divergence-tag--warn'
                            }
                            title={
                              expected
                                ? t('demoAction.divergenceExpectedHint')
                                : t('demoAction.divergenceUnexpectedHint')
                            }
                          >
                            {expected ? t('demoAction.divergenceExpected') : '⚠'}
                          </span>
                        ) : null}
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </section>
        ) : null}

        {decayValidation ? (
          <section className="demo-action-plan__decay-phases">
            <h3>{t('demoAction.decayPhasesTitle')}</h3>
            <div className="demo-action-plan__decay-grid">
              <div className="demo-action-plan__decay-card">
                <h4>{t('demoAction.decayPhaseSpike')}</h4>
                <ul>
                  <li>
                    {t('demoAction.decayImportance')}: {decayValidation.phase_spike.operational_importance}
                  </li>
                  <li>
                    {t('demoAction.decayPulse')}:{' '}
                    {decayValidation.phase_spike.pulse_eligible ? t('demoAction.yes') : t('demoAction.no')}
                  </li>
                  <li>
                    30 min: {formatDelaySec(decayValidation.phase_spike.predicted_at_horizon_30_sec, t)}
                  </li>
                </ul>
              </div>
              <div className="demo-action-plan__decay-arrow">→</div>
              <div className="demo-action-plan__decay-card">
                <h4>{t('demoAction.decayPhaseRecovery')}</h4>
                <ul>
                  <li>
                    {t('demoAction.decayImportance')}: {decayValidation.phase_recovery.operational_importance}
                  </li>
                  <li>
                    {t('demoAction.decayPulse')}:{' '}
                    {decayValidation.phase_recovery.pulse_eligible ? t('demoAction.yes') : t('demoAction.no')}
                  </li>
                  <li>
                    30 min: {formatDelaySec(decayValidation.phase_recovery.predicted_at_horizon_30_sec, t)}
                  </li>
                </ul>
              </div>
            </div>
          </section>
        ) : null}

        {validationChecks && validationChecks.length > 0 ? (
          <section className="demo-action-plan__validation">
            <h3>{t(validationSectionTitle(scenario))}</h3>
            {predictionValidation && scenario === 'stress' ? (
              <p className="demo-action-plan__validation-summary">
                {t('demoAction.stressValidationSummary', {
                  peak: Math.round(predictionValidation.peak_injected_delay_sec / 60),
                  max: Math.round(predictionValidation.max_predicted_delay_sec / 60),
                  importance: predictionValidation.operational_importance,
                })}
              </p>
            ) : null}
            <ul className="demo-action-plan__check-list">
              {validationChecks.map((check) => (
                <li
                  key={check.id}
                  className={check.ok ? 'demo-action-plan__check--ok' : 'demo-action-plan__check--fail'}
                >
                  <span className="demo-action-plan__check-mark">{check.ok ? '✓' : '✗'}</span>
                  <span>
                    <strong>{check.label}</strong> — {check.detail}
                  </span>
                </li>
              ))}
            </ul>
          </section>
        ) : null}

        {demoReport ? (
          <section className="demo-action-plan__report">
            <p className="demo-action-plan__report-headline">{demoReport.headline}</p>
            <p className="demo-action-plan__report-summary">{demoReport.summary}</p>
          </section>
        ) : null}

        <div className="demo-action-plan__columns">
          <section className="demo-action-plan__column">
            <h3>{t('demoAction.driver')}</h3>
            <ul>
              {operationalActions.driver.map((item) => (
                <li key={item}>{item}</li>
              ))}
            </ul>
          </section>
          <section className="demo-action-plan__column">
            <h3>{t('demoAction.dispatcher')}</h3>
            <ul>
              {operationalActions.dispatcher.map((item) => (
                <li key={item}>{item}</li>
              ))}
            </ul>
          </section>
        </div>

        {altSlots.length > 0 ? (
          <section className="demo-action-plan__slots">
            <h3>{t('demoAction.altSlots')}</h3>
            <ul className="demo-action-plan__slot-list">
              {altSlots.slice(0, 3).map((slot) => (
                <li key={slot.slot_id}>
                  <strong>{slot.terminal_label}</strong> {slot.window_local}
                  <span className="demo-action-plan__slack">
                    +{slot.slack_minutes} {t('demoAction.minSlack')}
                  </span>
                </li>
              ))}
            </ul>
          </section>
        ) : null}

        {scenario === 'incident' && voiceRequested && callSummary ? (
          <section className="demo-action-plan__voice">
            <h3>{t('demoAction.voiceStatus')}</h3>
            <pre className="demo-action-plan__voice-text">{callSummary}</pre>
          </section>
        ) : null}

        <details className="demo-action-plan__details">
          <summary>{t('demoAction.technicalDetails')}</summary>
          <pre className="demo-action-plan__debug">
            {technicalError ?? JSON.stringify(technicalPayload, null, 2)}
          </pre>
        </details>
      </div>
    </div>
  )

  return createPortal(content, document.body)
}
