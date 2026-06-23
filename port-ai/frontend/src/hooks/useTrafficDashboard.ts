import { useCallback, useEffect, useRef, useState } from 'react'
import { REFRESH_INTERVAL_MS } from '../constants/traffic'
import {
  fetchBottlenecks,
  fetchCorridorConfig,
  fetchCorridors,
  fetchEngineEvents,
  fetchMapData,
} from '../services/trafficApi'
import type { CorridorConfigResponse } from '../types/corridorConfig'
import type {
  BottlenecksResponse,
  CorridorsResponse,
  EngineEventsResponse,
} from '../types/engine'
import type { MapDataResponse } from '../types/traffic'

export function useTrafficDashboard() {
  const [mapData, setMapData] = useState<MapDataResponse | null>(null)
  const [engineEvents, setEngineEvents] = useState<EngineEventsResponse | null>(null)
  const [corridors, setCorridors] = useState<CorridorsResponse | null>(null)
  const [bottlenecks, setBottlenecks] = useState<BottlenecksResponse | null>(null)
  const [corridorConfig, setCorridorConfig] = useState<CorridorConfigResponse | null>(null)
  const [isLoading, setIsLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [lastUpdatedAt, setLastUpdatedAt] = useState<number | null>(null)
  const isFetchingRef = useRef(false)
  const hasLoadedRef = useRef(false)

  const loadCorridorConfig = useCallback(async () => {
    try {
      const nextConfig = await fetchCorridorConfig()
      setCorridorConfig(nextConfig)
    } catch (fetchError) {
      setError(fetchError instanceof Error ? fetchError.message : 'unknown_error')
    }
  }, [])

  const refresh = useCallback(async () => {
    if (isFetchingRef.current) {
      return
    }
    isFetchingRef.current = true
    setError(null)

    try {
      const [nextMapData, nextEngine, nextCorridors, nextBottlenecks] = await Promise.all([
        fetchMapData(),
        fetchEngineEvents(),
        fetchCorridors(),
        fetchBottlenecks(),
      ])
      setMapData(nextMapData)
      setEngineEvents(nextEngine)
      setCorridors(nextCorridors)
      setBottlenecks(nextBottlenecks)
      setLastUpdatedAt(Date.now())
      hasLoadedRef.current = true
      setIsLoading(false)
    } catch (fetchError) {
      setError(fetchError instanceof Error ? fetchError.message : 'unknown_error')
      setIsLoading((prev) => prev && !hasLoadedRef.current)
    } finally {
      isFetchingRef.current = false
    }
  }, [])

  useEffect(() => {
    void loadCorridorConfig()
    void refresh()
    const intervalId = window.setInterval(() => {
      void refresh()
    }, REFRESH_INTERVAL_MS)
    return () => window.clearInterval(intervalId)
  }, [loadCorridorConfig, refresh])

  return {
    mapData,
    engineEvents,
    corridors,
    bottlenecks,
    corridorConfig,
    isLoading,
    error,
    lastUpdatedAt,
    refreshIntervalMs: REFRESH_INTERVAL_MS,
    refresh,
    reloadCorridorConfig: loadCorridorConfig,
  }
}
