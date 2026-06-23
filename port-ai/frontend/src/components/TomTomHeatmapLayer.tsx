import { useEffect } from 'react'
import L from 'leaflet'
import 'leaflet.heat'
import { useMap } from 'react-leaflet'
import type { HeatmapPoint } from '../types/traffic'

const HEAT_GRADIENT: Record<number, string> = {
  0.2: '#22c55e',
  0.45: '#eab308',
  0.65: '#f97316',
  0.85: '#ef4444',
  1: '#991b1b',
}

interface TomTomHeatmapLayerProps {
  points: HeatmapPoint[]
  enabled: boolean
}

export function TomTomHeatmapLayer({ points, enabled }: TomTomHeatmapLayerProps) {
  const map = useMap()

  useEffect(() => {
    if (!enabled || points.length === 0) {
      return
    }

    const latlngs: [number, number, number][] = points.map((point) => [
      point.lat,
      point.lon,
      point.intensity,
    ])

    const layer = L.heatLayer(latlngs, {
      radius: 24,
      blur: 20,
      maxZoom: 15,
      max: 1,
      minOpacity: 0.35,
      gradient: HEAT_GRADIENT,
    })
    layer.addTo(map)

    return () => {
      map.removeLayer(layer)
    }
  }, [enabled, map, points])

  return null
}
