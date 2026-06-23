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
  boostIntensity?: boolean
}

export function TomTomHeatmapLayer({ points, enabled, boostIntensity = false }: TomTomHeatmapLayerProps) {
  const map = useMap()

  useEffect(() => {
    if (!enabled || points.length === 0) {
      return
    }

    const latlngs: [number, number, number][] = points.map((point) => [
      point.lat,
      point.lon,
      boostIntensity ? Math.min(1, point.intensity * 1.15) : point.intensity,
    ])

    const layer = L.heatLayer(latlngs, {
      radius: boostIntensity ? 32 : 24,
      blur: boostIntensity ? 26 : 20,
      maxZoom: 15,
      max: 1,
      minOpacity: boostIntensity ? 0.5 : 0.35,
      gradient: HEAT_GRADIENT,
    })
    layer.addTo(map)

    return () => {
      map.removeLayer(layer)
    }
  }, [boostIntensity, enabled, map, points])

  return null
}
