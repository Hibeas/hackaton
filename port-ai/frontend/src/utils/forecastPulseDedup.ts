import {
  FORECAST_PULSE_DEDUP_STORAGE_KEY,
  FORECAST_PULSE_SEEN_TTL_MS,
} from '../constants/forecast'
import type { CorridorPulseDetail } from './forecastPulseReport'

interface PulseSeenRecord {
  fingerprint: string
  seenAt: number
  expiresAt: number
}

function readRecords(): PulseSeenRecord[] {
  try {
    const raw = window.localStorage.getItem(FORECAST_PULSE_DEDUP_STORAGE_KEY)
    if (!raw) {
      return []
    }
    const parsed = JSON.parse(raw) as PulseSeenRecord[]
    if (!Array.isArray(parsed)) {
      return []
    }
    const now = Date.now()
    return parsed.filter((item) => item.expiresAt > now)
  } catch {
    return []
  }
}

function writeRecords(records: PulseSeenRecord[]) {
  try {
    window.localStorage.setItem(FORECAST_PULSE_DEDUP_STORAGE_KEY, JSON.stringify(records))
  } catch {
    /* ignore quota / private mode */
  }
}

export function delayBucketSec(predictedDelaySec: number, currentDelaySec: number): number {
  const effective = Math.max(predictedDelaySec, currentDelaySec)
  return Math.round(effective / 60)
}

export function buildPulseFingerprint(
  detail: CorridorPulseDetail,
  eventId?: string | null,
): string {
  const bucket = delayBucketSec(detail.predictedDelaySec, detail.currentDelaySec)
  const parts = [
    detail.corridorId,
    detail.kind,
    String(detail.horizonMinutes),
    detail.operationalImportance,
    String(bucket),
    detail.causeCategory,
  ]
  if (detail.kind === 'validated' && eventId) {
    parts.push(eventId)
  }
  return parts.join('|')
}

export function isPulseRecentlySeen(fingerprint: string): boolean {
  return readRecords().some((item) => item.fingerprint === fingerprint)
}

export function markPulseSeen(fingerprint: string, now = Date.now()) {
  const records = readRecords().filter((item) => item.fingerprint !== fingerprint)
  records.push({
    fingerprint,
    seenAt: now,
    expiresAt: now + FORECAST_PULSE_SEEN_TTL_MS,
  })
  writeRecords(records)
}
