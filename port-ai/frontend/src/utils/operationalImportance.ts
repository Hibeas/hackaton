import type { GeofenceType } from '../types/engine'

/** Composite operational tier — distinct from forecast confidence or engine severity. */
export type OperationalImportance = 'monitor' | 'caution' | 'action' | 'critical'

const DELAY_MONITOR_MAX_SEC = 300
const DELAY_CAUTION_MAX_SEC = 480
const DELAY_ACTION_MAX_SEC = 720

const IMPROVING_TREND_MIN_SEC = 60

export interface OperationalImportanceInput {
  predictedDelaySec: number
  currentDelaySec: number
  horizonMinutes: number
  geofenceType?: GeofenceType | string | null
  impactsPortAccess?: boolean
}

function delayScore(effectiveDelaySec: number): number {
  if (effectiveDelaySec < DELAY_MONITOR_MAX_SEC) {
    return 0
  }
  if (effectiveDelaySec < DELAY_CAUTION_MAX_SEC) {
    return 1
  }
  if (effectiveDelaySec < DELAY_ACTION_MAX_SEC) {
    return 2
  }
  return 3
}

function urgencyScore(horizonMinutes: number): number {
  if (horizonMinutes <= 15) {
    return 2
  }
  if (horizonMinutes <= 30) {
    return 1
  }
  if (horizonMinutes <= 60) {
    return 0
  }
  return -1
}

function accessScore(geofenceType: string | null | undefined, impactsPortAccess: boolean): number {
  if (!impactsPortAccess) {
    return 0
  }

  switch (geofenceType) {
    case 'GATE_ZONE':
    case 'PORT_ACCESS':
      return 3
    case 'APPROACH_CORRIDOR':
    case 'BOTTLENECK':
    case 'CRITICAL_INFRASTRUCTURE':
      return 2
    case 'BUFFER_ZONE':
      return 0
    default:
      return 1
  }
}

function trendAdjustment(predictedDelaySec: number, currentDelaySec: number): number {
  if (predictedDelaySec < currentDelaySec - IMPROVING_TREND_MIN_SEC) {
    return -1
  }
  return 0
}

export function computeOperationalImportanceScore(input: OperationalImportanceInput): number {
  const effectiveDelaySec = Math.max(input.predictedDelaySec, input.currentDelaySec)
  return (
    delayScore(effectiveDelaySec) +
    urgencyScore(input.horizonMinutes) +
    accessScore(input.geofenceType, input.impactsPortAccess ?? true) +
    trendAdjustment(input.predictedDelaySec, input.currentDelaySec)
  )
}

export function scoreToOperationalImportance(score: number): OperationalImportance {
  if (score <= 3) {
    return 'monitor'
  }
  if (score <= 5) {
    return 'caution'
  }
  if (score <= 6) {
    return 'action'
  }
  return 'critical'
}

export function computeOperationalImportance(
  input: OperationalImportanceInput,
): OperationalImportance {
  return scoreToOperationalImportance(computeOperationalImportanceScore(input))
}

/** Map blink / popup on the map only for dispatch-relevant tiers. */
export function qualifiesForMapPulse(importance: OperationalImportance): boolean {
  return importance === 'action' || importance === 'critical'
}

export function qualifiesForValidatedPan(importance: OperationalImportance): boolean {
  return qualifiesForMapPulse(importance)
}
