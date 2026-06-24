import { useCallback, useEffect, useState } from 'react'
import { fetchMyBookings } from '../services/tmsApi'
import type { MyBookingsResponse } from '../types/tms'

const REFRESH_MS = 30_000

export function useMyBookings(enabled: boolean) {
  const [data, setData] = useState<MyBookingsResponse | null>(null)
  const [isLoading, setIsLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const refresh = useCallback(async () => {
    if (!enabled) {
      return
    }
    setIsLoading(true)
    setError(null)
    try {
      const response = await fetchMyBookings()
      setData(response)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'bookings_fetch_failed')
    } finally {
      setIsLoading(false)
    }
  }, [enabled])

  useEffect(() => {
    if (!enabled) {
      return undefined
    }
    void refresh()
    const timer = window.setInterval(() => {
      void refresh()
    }, REFRESH_MS)
    return () => window.clearInterval(timer)
  }, [enabled, refresh])

  return { data, isLoading, error, refresh }
}
