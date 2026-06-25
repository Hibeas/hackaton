import { useEffect, type RefObject } from 'react'
import { useMap } from 'react-leaflet'
import type { Map as LeafletMap } from 'leaflet'

const DEBOUNCE_MS = 50
const SIDEBAR_TRANSITION_MS = 220

function invalidate(map: LeafletMap) {
  map.invalidateSize({ animate: false, pan: false })
}

export function MapInvalidateSize({
  containerRef,
  layoutKey,
}: {
  containerRef: RefObject<HTMLElement | null>
  layoutKey?: number | boolean
}) {
  const map = useMap()

  useEffect(() => {
    const container = containerRef.current
    if (!container) {
      return undefined
    }

    let debounceTimer: number | undefined

    const scheduleInvalidate = () => {
      if (debounceTimer !== undefined) {
        window.clearTimeout(debounceTimer)
      }
      debounceTimer = window.setTimeout(() => {
        invalidate(map)
      }, DEBOUNCE_MS)
    }

    const observer = new ResizeObserver(scheduleInvalidate)
    observer.observe(container)
    scheduleInvalidate()

    return () => {
      observer.disconnect()
      if (debounceTimer !== undefined) {
        window.clearTimeout(debounceTimer)
      }
    }
  }, [containerRef, map])

  useEffect(() => {
    if (layoutKey === undefined) {
      return undefined
    }

    const immediate = window.setTimeout(() => invalidate(map), DEBOUNCE_MS)
    const afterTransition = window.setTimeout(() => invalidate(map), SIDEBAR_TRANSITION_MS)

    return () => {
      window.clearTimeout(immediate)
      window.clearTimeout(afterTransition)
    }
  }, [layoutKey, map])

  return null
}
