import { useCallback, useEffect, useState } from 'react'
import { fetchSlotRecommendations } from '../services/tmsApi'
import type { SlotRecommendationsResponse } from '../types/tms'

export function useSlotRecommendations(
  corridorId: string | null,
  predictedDelaySec: number | null,
  enabled = true,
) {
  const [data, setData] = useState<SlotRecommendationsResponse | null>(null)
  const [isLoading, setIsLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const refresh = useCallback(async () => {
    if (!corridorId || !enabled) {
      setData(null)
      return
    }
    setIsLoading(true)
    setError(null)
    try {
      const result = await fetchSlotRecommendations(
        corridorId,
        predictedDelaySec ?? 0,
      )
      setData(result)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'slot_recommendations_failed')
      setData(null)
    } finally {
      setIsLoading(false)
    }
  }, [corridorId, enabled, predictedDelaySec])

  useEffect(() => {
    void refresh()
  }, [refresh])

  return { data, isLoading, error, refresh }
}
