import { useCallback, useEffect, useState } from 'react'
import { fetchDispatchAudit } from '../services/tmsApi'
import type { DispatchAuditEntry } from '../types/tms'

export function useDispatchAudit(enabled = true, pollMs = 30_000) {
  const [entries, setEntries] = useState<DispatchAuditEntry[]>([])
  const [isLoading, setIsLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const refresh = useCallback(async () => {
    if (!enabled) {
      return
    }
    setIsLoading(true)
    setError(null)
    try {
      const result = await fetchDispatchAudit(40)
      setEntries(result.entries)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'audit_fetch_failed')
      setEntries([])
    } finally {
      setIsLoading(false)
    }
  }, [enabled])

  useEffect(() => {
    void refresh()
    if (!enabled || pollMs <= 0) {
      return undefined
    }
    const intervalId = window.setInterval(() => {
      void refresh()
    }, pollMs)
    return () => window.clearInterval(intervalId)
  }, [enabled, pollMs, refresh])

  return { entries, isLoading, error, refresh }
}
