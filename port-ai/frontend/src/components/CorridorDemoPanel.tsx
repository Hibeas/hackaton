import { useCallback, useEffect, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import {
  triggerCorridorIncident,
  triggerDecayRecovery,
  triggerMlKafkaCompare,
  triggerPredictionStress,
  type CorridorIncidentResponse,
  type DecayValidation,
  type DemoReport,
  type MethodComparison,
  type PredictionStressResponse,
  type PredictionValidation,
  type OperationalActions,
} from '../services/trafficApi'
import type { CrowdMapOverlayResponse } from '../types/traffic'
import type { SlotRecommendation } from '../types/tms'
import { DemoActionPlan } from './DemoActionPlan'

type DemoRunState =
  | 'idle'
  | 'incident'
  | 'incident-voice'
  | 'stress'
  | 'ml_kafka'
  | 'decay'
type DemoScenario = 'incident' | 'stress' | 'ml_kafka' | 'decay'

function demoErrorMessage(code: string, t: (key: string) => string): string {
  if (code === 'Not Found' || code.includes('not found')) {
    return t('demoAction.errorEndpointMissing')
  }
  if (code === 'no_approach_corridors') {
    return t('demoAction.errorNoApproachCorridors')
  }
  return code
}

function summarizeCalls(response: CorridorIncidentResponse | null): string {
  const calls = response?.dispatch?.calls ?? []
  if (calls.length === 0) {
    return 'Brak wpisów calls — sprawdź alert_count i slot at_risk'
  }
  return calls
    .map((call) => {
      const parts = [call.status ?? '?']
      if (call.phone) parts.push(String(call.phone))
      if (call.booking_ref) parts.push(String(call.booking_ref))
      if (call.error) parts.push(String(call.error))
      if (call.call_sid) parts.push(String(call.call_sid))
      return parts.join(' | ')
    })
    .join('\n')
}

interface CorridorDemoPanelProps {
  selectedPortId: string
  selectedCorridorId: string | null
  selectedCorridorName: string | null
  onDemoComplete?: () => void
  onCorridorFocus?: (corridorId: string, portId: string) => void
  onCrowdOverlayChange: (overlay: CrowdMapOverlayResponse | null) => void
}

export function CorridorDemoPanel({
  selectedPortId,
  selectedCorridorId,
  selectedCorridorName,
  onDemoComplete,
  onCorridorFocus,
  onCrowdOverlayChange,
}: CorridorDemoPanelProps) {
  const { t } = useTranslation()
  const [runState, setRunState] = useState<DemoRunState>('idle')
  const [menuOpen, setMenuOpen] = useState(false)
  const [planOpen, setPlanOpen] = useState(false)
  const [scenario, setScenario] = useState<DemoScenario>('incident')
  const [voiceRequested, setVoiceRequested] = useState(false)
  const [displayCorridorName, setDisplayCorridorName] = useState('')
  const [operationalActions, setOperationalActions] = useState<OperationalActions | null>(null)
  const [slotRecommendations, setSlotRecommendations] = useState<SlotRecommendation[]>([])
  const [demoReport, setDemoReport] = useState<DemoReport | null>(null)
  const [predictionValidation, setPredictionValidation] = useState<PredictionValidation | null>(null)
  const [methodComparison, setMethodComparison] = useState<MethodComparison | null>(null)
  const [decayValidation, setDecayValidation] = useState<DecayValidation | null>(null)
  const [callSummary, setCallSummary] = useState<string | null>(null)
  const [technicalPayload, setTechnicalPayload] = useState<unknown>(null)
  const [technicalError, setTechnicalError] = useState<string | null>(null)
  const [statusHint, setStatusHint] = useState<string | null>(null)
  const menuRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!menuOpen) {
      return
    }
    const handlePointer = (event: MouseEvent) => {
      if (menuRef.current && !menuRef.current.contains(event.target as Node)) {
        setMenuOpen(false)
      }
    }
    document.addEventListener('mousedown', handlePointer)
    return () => document.removeEventListener('mousedown', handlePointer)
  }, [menuOpen])

  const openPlan = useCallback(
    (
      nextScenario: DemoScenario,
      corridorName: string,
      actions: OperationalActions,
      slots: SlotRecommendation[],
      extras: {
        payload?: unknown
        error?: string | null
        calls?: string | null
        report?: DemoReport | null
        validation?: PredictionValidation | null
        methodComparison?: MethodComparison | null
        decayValidation?: DecayValidation | null
        withVoice?: boolean
      },
    ) => {
      setScenario(nextScenario)
      setVoiceRequested(Boolean(extras.withVoice))
      setDisplayCorridorName(corridorName)
      setOperationalActions(actions)
      setSlotRecommendations(slots)
      setDemoReport(extras.report ?? null)
      setPredictionValidation(extras.validation ?? null)
      setMethodComparison(extras.methodComparison ?? null)
      setDecayValidation(extras.decayValidation ?? null)
      setTechnicalPayload(extras.payload ?? null)
      setTechnicalError(extras.error ?? null)
      setCallSummary(extras.calls ?? null)
      setPlanOpen(true)
    },
    [],
  )

  const runIncident = useCallback(
    async (enableVoice: boolean) => {
      if (!selectedCorridorId || runState !== 'idle') {
        return
      }
      setMenuOpen(false)
      setRunState(enableVoice ? 'incident-voice' : 'incident')
      setStatusHint(null)
      try {
        const response = await triggerCorridorIncident(selectedCorridorId, { enable_voice: enableVoice })
        onCrowdOverlayChange(response.map_overlay)
        const actions = response.operational_actions
        const slots = response.slot_recommendations?.recommendations ?? []
        const called = response.dispatch?.calls?.some((item) => item.status === 'called')
        const voiceSkipped = enableVoice && response.voice?.skipped === true
        if (enableVoice && called) {
          setStatusHint(t('spikeDemo.ok'))
        } else if (voiceSkipped) {
          setStatusHint(t('demoAction.spikeNoVoice'))
        } else if (enableVoice) {
          setStatusHint(t('spikeDemo.noCall'))
        } else {
          setStatusHint(t('demoAction.incidentOk'))
        }
        openPlan('incident', response.corridor_name ?? selectedCorridorId, actions, slots, {
          payload: response,
          withVoice: enableVoice,
          calls: enableVoice
            ? voiceSkipped
              ? t('demoAction.spikeVoiceSkipped')
              : summarizeCalls(response)
            : null,
        })
        onDemoComplete?.()
      } catch (error) {
        const message = error instanceof Error ? demoErrorMessage(error.message, t) : t('crowdDemo.error')
        setStatusHint(message)
        openPlan(
          'incident',
          selectedCorridorName ?? selectedCorridorId,
          {
            scenario: 'incident',
            operational_importance: 'action',
            driver: [message],
            dispatcher: [t('demoAction.errorHint')],
          },
          [],
          { error: JSON.stringify({ error: message }, null, 2), withVoice: enableVoice },
        )
      } finally {
        setRunState('idle')
      }
    },
    [
      onCrowdOverlayChange,
      onDemoComplete,
      openPlan,
      runState,
      selectedCorridorId,
      selectedCorridorName,
      t,
    ],
  )

  const runStress = useCallback(async () => {
    if (runState !== 'idle') {
      return
    }
    setMenuOpen(false)
    setRunState('stress')
    setStatusHint(null)
    try {
      const response: PredictionStressResponse = await triggerPredictionStress()
      onCrowdOverlayChange(response.map_overlay)
      onCorridorFocus?.(response.corridor_id, response.port_id ?? selectedPortId)
      const actions = response.operational_actions
      const slots = response.slot_recommendations?.recommendations ?? []
      const passed = response.prediction_validation?.passed
      setStatusHint(passed ? t('demoAction.stressOk') : t('demoAction.stressPartial'))
      openPlan('stress', response.corridor_name ?? response.corridor_id, actions, slots, {
        payload: response,
        report: response.demo_report,
        validation: response.prediction_validation,
      })
      onDemoComplete?.()
    } catch (error) {
      const message = error instanceof Error ? demoErrorMessage(error.message, t) : t('crowdDemo.error')
      setStatusHint(message)
      openPlan(
        'stress',
        selectedCorridorName ?? t('demoAction.stress'),
        {
          scenario: 'stress',
          operational_importance: 'critical',
          driver: [message],
          dispatcher: [t('demoAction.errorHint')],
        },
        [],
        { error: JSON.stringify({ error: message }, null, 2) },
      )
    } finally {
      setRunState('idle')
    }
  }, [
    onCorridorFocus,
    onCrowdOverlayChange,
    onDemoComplete,
    openPlan,
    runState,
    selectedCorridorName,
    selectedPortId,
    t,
  ])

  const runMlKafka = useCallback(async () => {
    if (runState !== 'idle') {
      return
    }
    setMenuOpen(false)
    setRunState('ml_kafka')
    setStatusHint(null)
    try {
      const response = await triggerMlKafkaCompare(
        selectedCorridorId ? { corridor_id: selectedCorridorId, port_id: selectedPortId } : undefined,
      )
      onCrowdOverlayChange(response.map_overlay)
      onCorridorFocus?.(response.corridor_id, response.port_id ?? selectedPortId)
      const passed = response.method_comparison.passed
      setStatusHint(passed ? t('demoAction.mlKafkaOk') : t('demoAction.mlKafkaPartial'))
      openPlan('ml_kafka', response.corridor_name ?? response.corridor_id, response.operational_actions, response.slot_recommendations?.recommendations ?? [], {
        payload: response,
        validation: response.prediction_validation,
        methodComparison: response.method_comparison,
      })
      onDemoComplete?.()
    } catch (error) {
      const message = error instanceof Error ? demoErrorMessage(error.message, t) : t('crowdDemo.error')
      setStatusHint(message)
      openPlan(
        'ml_kafka',
        selectedCorridorName ?? t('demoAction.mlKafka'),
        {
          scenario: 'ml_kafka',
          operational_importance: 'action',
          driver: [message],
          dispatcher: [t('demoAction.errorHint')],
        },
        [],
        { error: JSON.stringify({ error: message }, null, 2) },
      )
    } finally {
      setRunState('idle')
    }
  }, [
    onCorridorFocus,
    onCrowdOverlayChange,
    onDemoComplete,
    openPlan,
    runState,
    selectedCorridorId,
    selectedCorridorName,
    selectedPortId,
    t,
  ])

  const runDecay = useCallback(async () => {
    if (runState !== 'idle') {
      return
    }
    setMenuOpen(false)
    setRunState('decay')
    setStatusHint(null)
    try {
      const response = await triggerDecayRecovery(
        selectedCorridorId ? { corridor_id: selectedCorridorId, port_id: selectedPortId } : undefined,
      )
      onCrowdOverlayChange(response.map_overlay)
      onCorridorFocus?.(response.corridor_id, response.port_id ?? selectedPortId)
      const passed = response.decay_validation.passed
      setStatusHint(passed ? t('demoAction.decayOk') : t('demoAction.decayPartial'))
      openPlan('decay', response.corridor_name ?? response.corridor_id, response.operational_actions, response.slot_recommendations?.recommendations ?? [], {
        payload: response,
        report: response.demo_report,
        validation: response.prediction_validation,
        decayValidation: response.decay_validation,
      })
      onDemoComplete?.()
    } catch (error) {
      const message = error instanceof Error ? demoErrorMessage(error.message, t) : t('crowdDemo.error')
      setStatusHint(message)
      openPlan(
        'decay',
        selectedCorridorName ?? t('demoAction.decay'),
        {
          scenario: 'decay',
          operational_importance: 'monitor',
          driver: [message],
          dispatcher: [t('demoAction.errorHint')],
        },
        [],
        { error: JSON.stringify({ error: message }, null, 2) },
      )
    } finally {
      setRunState('idle')
    }
  }, [
    onCorridorFocus,
    onCrowdOverlayChange,
    onDemoComplete,
    openPlan,
    runState,
    selectedCorridorId,
    selectedCorridorName,
    selectedPortId,
    t,
  ])

  const isRunning = runState !== 'idle'
  const corridorLabel = selectedCorridorName ?? selectedCorridorId ?? ''

  const runningLabels: Record<Exclude<DemoRunState, 'idle'>, string> = {
    incident: t('demoAction.runningIncident'),
    'incident-voice': t('demoAction.runningIncidentVoice'),
    stress: t('demoAction.runningStress'),
    ml_kafka: t('demoAction.runningMlKafka'),
    decay: t('demoAction.runningDecay'),
  }

  const primaryLabel = isRunning ? runningLabels[runState] : t('demoAction.panel')

  const title = selectedCorridorId
    ? statusHint ?? t('demoAction.panelHint', { corridor: corridorLabel })
    : statusHint ?? t('demoAction.openMenuHint')

  return (
    <div className="corridor-demo-panel" ref={menuRef}>
      <div className="corridor-demo-panel__split">
        <button
          type="button"
          className={`corridor-demo-panel__main${isRunning ? ' corridor-demo-panel__main--busy' : ''}`}
          disabled={isRunning}
          title={title}
          onClick={() => setMenuOpen((open) => !open)}
        >
          {primaryLabel}
        </button>
        <button
          type="button"
          className={`corridor-demo-panel__caret${menuOpen ? ' corridor-demo-panel__caret--open' : ''}`}
          disabled={isRunning}
          aria-expanded={menuOpen}
          aria-haspopup="menu"
          title={t('demoAction.menuHint')}
          onClick={() => setMenuOpen((open) => !open)}
        >
          ▾
        </button>
      </div>

      {menuOpen ? (
        <div className="corridor-demo-panel__menu" role="menu">
          <button
            type="button"
            role="menuitem"
            className={!selectedCorridorId ? 'corridor-demo-panel__menu-item--disabled' : ''}
            disabled={!selectedCorridorId || isRunning}
            title={!selectedCorridorId ? t('demoAction.needsCorridor') : undefined}
            onClick={() => void runIncident(false)}
          >
            <span className="corridor-demo-panel__menu-label">{t('demoAction.incident')}</span>
            <span className="corridor-demo-panel__menu-desc">{t('demoAction.incidentDesc')}</span>
          </button>
          <button
            type="button"
            role="menuitem"
            className={!selectedCorridorId ? 'corridor-demo-panel__menu-item--disabled' : ''}
            disabled={!selectedCorridorId || isRunning}
            title={!selectedCorridorId ? t('demoAction.needsCorridor') : undefined}
            onClick={() => void runIncident(true)}
          >
            <span className="corridor-demo-panel__menu-label">{t('demoAction.incidentVoice')}</span>
            <span className="corridor-demo-panel__menu-desc">{t('demoAction.incidentVoiceDesc')}</span>
          </button>
          <button type="button" role="menuitem" disabled={isRunning} onClick={() => void runStress()}>
            <span className="corridor-demo-panel__menu-label">{t('demoAction.stress')}</span>
            <span className="corridor-demo-panel__menu-desc">{t('demoAction.stressDesc')}</span>
          </button>
          <button type="button" role="menuitem" disabled={isRunning} onClick={() => void runMlKafka()}>
            <span className="corridor-demo-panel__menu-label">{t('demoAction.mlKafka')}</span>
            <span className="corridor-demo-panel__menu-desc">{t('demoAction.mlKafkaDesc')}</span>
          </button>
          <button type="button" role="menuitem" disabled={isRunning} onClick={() => void runDecay()}>
            <span className="corridor-demo-panel__menu-label">{t('demoAction.decay')}</span>
            <span className="corridor-demo-panel__menu-desc">{t('demoAction.decayDesc')}</span>
          </button>
        </div>
      ) : null}

      <DemoActionPlan
        open={planOpen}
        onClose={() => setPlanOpen(false)}
        corridorName={displayCorridorName || corridorLabel}
        scenario={scenario}
        voiceRequested={voiceRequested}
        operationalActions={operationalActions}
        slotRecommendations={slotRecommendations}
        demoReport={demoReport}
        predictionValidation={predictionValidation}
        methodComparison={methodComparison}
        decayValidation={decayValidation}
        callSummary={callSummary}
        technicalPayload={technicalPayload}
        technicalError={technicalError}
      />
    </div>
  )
}
