import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import type { PortConfig } from '../constants/ports'
import {
  DEFAULT_FORECAST_HORIZON,
  FORECAST_PULSE_COOLDOWN_MS,
  FORECAST_PULSE_DURATION_MS,
  FORECAST_PULSE_MEMORY_MS,
  FORECAST_PULSE_MIN_DELAY_SEC,
} from '../constants/forecast'
import type { CorridorBbox } from '../constants/ports'
import type { CorridorsResponse, DelayForecastResponse, EngineEventsResponse } from '../types/engine'
import { corridorMapBounds, findCorridor } from '../utils/corridorConfigHelpers'
import {
  buildCorridorPulseDetail,
  type CorridorPulseDetail,
} from '../utils/forecastPulseReport'
import {
  buildPulseFingerprint,
  isPulseRecentlySeen,
  markPulseSeen,
} from '../utils/forecastPulseDedup'
import {
  qualifiesForMapPulse,
  qualifiesForValidatedPan,
} from '../utils/operationalImportance'

const PULSE_ANIMATION_TICK_MS = 50

export interface MapPulseAnnouncement {
  kind: 'proactive' | 'validated'
  corridorId: string
  corridorName: string
}

export function useCorridorMapPulse(
  delayForecasts: DelayForecastResponse | null | undefined,
  engineEvents: EngineEventsResponse | null,
  corridors: CorridorsResponse | null,
  ports: PortConfig[],
  forecastHorizon: number = DEFAULT_FORECAST_HORIZON,
) {
  const prevForecastRef = useRef<Map<string, number>>(new Map())
  const prevEventIdsRef = useRef<Set<string>>(new Set())
  const highForecastMemoryRef = useRef<Map<string, number>>(new Map())
  const lastPulseEndRef = useRef<Map<string, number>>(new Map())
  const pulseTimersRef = useRef<Map<string, number>>(new Map())
  const initializedEventsRef = useRef(false)

  const [activePulses, setActivePulses] = useState<CorridorPulseDetail[]>([])
  const [pulseNow, setPulseNow] = useState(() => Date.now())
  const [pulsePanBbox, setPulsePanBbox] = useState<CorridorBbox | null>(null)
  const [announcement, setAnnouncement] = useState<MapPulseAnnouncement | null>(null)

  const activePulseByCorridor = useMemo(() => {
    const map = new Map<string, CorridorPulseDetail>()
    for (const pulse of activePulses) {
      map.set(pulse.corridorId, pulse)
    }
    return map
  }, [activePulses])

  const canPulse = useCallback((corridorId: string) => {
    const lastEnd = lastPulseEndRef.current.get(corridorId) ?? 0
    return Date.now() - lastEnd >= FORECAST_PULSE_COOLDOWN_MS
  }, [])

  const startPulse = useCallback(
    (corridorId: string, kind: 'proactive' | 'validated') => {
      if (!canPulse(corridorId)) {
        return
      }

      const built = buildCorridorPulseDetail(corridorId, kind, {
        ports,
        delayForecasts,
        corridors,
        engineEvents,
        forecastHorizon,
      })

      if (!built) {
        return
      }

      const detail: CorridorPulseDetail = {
        ...built,
        startedAt: Date.now(),
      }

      if (!qualifiesForMapPulse(detail.operationalImportance)) {
        return
      }

      const eventId =
        kind === 'validated'
          ? (engineEvents?.events ?? [])
              .filter((item) => item.corridor_id === corridorId)
              .sort((a, b) => b.severity - a.severity)[0]?.id
          : null
      const fingerprint = buildPulseFingerprint(detail, eventId)
      if (isPulseRecentlySeen(fingerprint)) {
        return
      }

      const existingTimer = pulseTimersRef.current.get(corridorId)
      if (existingTimer !== undefined) {
        window.clearTimeout(existingTimer)
      }

      setActivePulses((prev) => {
        const without = prev.filter((item) => item.corridorId !== corridorId)
        return [...without, detail]
      })

      setAnnouncement({
        kind,
        corridorId,
        corridorName: detail.corridorName,
      })

      if (kind === 'validated' && qualifiesForValidatedPan(detail.operationalImportance)) {
        const corridor = findCorridor(ports, corridorId)
        if (corridor) {
          setPulsePanBbox(corridorMapBounds(corridor))
        }
      }

      const timer = window.setTimeout(() => {
        setActivePulses((prev) => prev.filter((item) => item.corridorId !== corridorId))
        lastPulseEndRef.current.set(corridorId, Date.now())
        pulseTimersRef.current.delete(corridorId)
        setAnnouncement((current) => (current?.corridorId === corridorId ? null : current))
      }, FORECAST_PULSE_DURATION_MS)

      pulseTimersRef.current.set(corridorId, timer)
      markPulseSeen(fingerprint)
    },
    [canPulse, corridors, delayForecasts, engineEvents, forecastHorizon, ports],
  )

  useEffect(() => {
    if (activePulses.length === 0) {
      return undefined
    }

    const interval = window.setInterval(() => {
      setPulseNow(Date.now())
    }, PULSE_ANIMATION_TICK_MS)

    return () => {
      window.clearInterval(interval)
    }
  }, [activePulses.length])

  useEffect(() => {
    return () => {
      for (const timer of pulseTimersRef.current.values()) {
        window.clearTimeout(timer)
      }
      pulseTimersRef.current.clear()
    }
  }, [])

  useEffect(() => {
    const now = Date.now()
    const forecastMap = new Map<string, number>()

    for (const item of delayForecasts?.forecasts ?? []) {
      if (item.horizon_minutes === forecastHorizon) {
        forecastMap.set(item.corridor_id, item.predicted_delay_sec)
      }
    }

    for (const [corridorId, delay] of forecastMap) {
      if (delay >= FORECAST_PULSE_MIN_DELAY_SEC) {
        highForecastMemoryRef.current.set(corridorId, now)
      }
    }

    for (const [corridorId, timestamp] of highForecastMemoryRef.current) {
      if (now - timestamp > FORECAST_PULSE_MEMORY_MS) {
        highForecastMemoryRef.current.delete(corridorId)
      }
    }

    for (const [corridorId, delay] of forecastMap) {
      const previous = prevForecastRef.current.get(corridorId) ?? 0
      if (previous < FORECAST_PULSE_MIN_DELAY_SEC && delay >= FORECAST_PULSE_MIN_DELAY_SEC) {
        startPulse(corridorId, 'proactive')
      }
    }

    const events = engineEvents?.events ?? []
    const currentEventIds = new Set(events.map((event) => event.id))

    if (initializedEventsRef.current) {
      for (const event of events) {
        if (!prevEventIdsRef.current.has(event.id)) {
          if (highForecastMemoryRef.current.has(event.corridor_id)) {
            startPulse(event.corridor_id, 'validated')
          }
        }
      }
    } else if (events.length > 0) {
      initializedEventsRef.current = true
    }

    prevForecastRef.current = forecastMap
    prevEventIdsRef.current = currentEventIds
  }, [delayForecasts, engineEvents, forecastHorizon, startPulse])

  const clearPulsePanBbox = useCallback(() => {
    setPulsePanBbox(null)
  }, [])

  return {
    activePulses,
    activePulseByCorridor,
    pulseNow,
    pulsePanBbox,
    announcement,
    clearPulsePanBbox,
  }
}
