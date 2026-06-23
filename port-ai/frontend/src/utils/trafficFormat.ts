import { MAP_BOUNDS } from '../constants/traffic'
import type { LineStringGeometry, TrafficEvent } from '../types/traffic'

export function isValidLocation(lat: number, lon: number): boolean {
  if (!Number.isFinite(lat) || !Number.isFinite(lon)) {
    return false
  }
  if (lat === 0 && lon === 0) {
    return false
  }
  return (
    lat >= MAP_BOUNDS.minLat &&
    lat <= MAP_BOUNDS.maxLat &&
    lon >= MAP_BOUNDS.minLon &&
    lon <= MAP_BOUNDS.maxLon
  )
}

export function normalizeLineGeometry(
  geometry: LineStringGeometry | null,
): LineStringGeometry | null {
  if (!geometry?.coordinates || geometry.coordinates.length < 2) {
    return null
  }

  const coordinates = geometry.coordinates
    .map(([lon, lat]) => {
      if (!isValidLocation(lat, lon)) {
        return null
      }
      return [lon, lat] as [number, number]
    })
    .filter((point): point is [number, number] => point !== null)

  if (coordinates.length < 2) {
    return null
  }

  return { type: 'LineString', coordinates }
}

export function formatPercent(value: number | null | undefined): string {
  if (value === null || value === undefined) {
    return '—'
  }
  return `${Math.round(value * 100)}%`
}

export function formatRatio(value: number | null | undefined): string {
  if (value === null || value === undefined) {
    return '—'
  }
  return value.toFixed(2)
}

export function formatDateTime(value: string | null | undefined, locale: string): string {
  if (!value) {
    return '—'
  }
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) {
    return value
  }
  return date.toLocaleString(locale)
}

export function splitContextEvents(events: TrafficEvent[]) {
  const segments: TrafficEvent[] = []
  const vehicles: TrafficEvent[] = []

  for (const event of events) {
    if (event.record_kind === 'road_segment') {
      segments.push(event)
      continue
    }
    if (event.record_kind === 'vehicle') {
      if (event.metrics.is_bus_stop) {
        continue
      }
      if (!isValidLocation(event.location.lat, event.location.lon)) {
        continue
      }
      vehicles.push(event)
    }
  }

  return { segments, vehicles }
}

export function splitPrimaryEvents(events: TrafficEvent[]) {
  const lineIncidents: TrafficEvent[] = []
  const pointIncidents: TrafficEvent[] = []

  for (const event of events) {
    if (event.geometry?.type === 'LineString') {
      lineIncidents.push(event)
    } else if (event.geometry?.type === 'Point') {
      pointIncidents.push(event)
    }
  }

  return { lineIncidents, pointIncidents }
}

export function buildSegmentGeoJson(segments: TrafficEvent[]) {
  return {
    type: 'FeatureCollection' as const,
    features: segments
      .map((event) => {
        const geometry = normalizeLineGeometry(
          event.geometry?.type === 'LineString' ? event.geometry : null,
        )
        if (!geometry) {
          return null
        }
        return {
          type: 'Feature' as const,
          geometry,
          properties: {
            eventId: event.event_id,
            status: event.status,
            roadName: event.location.road_name,
            speedKmh: event.metrics.speed_kmh,
            intensityVph: event.metrics.intensity_vph,
            context: true,
          },
        }
      })
      .filter((feature) => feature !== null),
  }
}

export function buildIncidentGeoJson(incidents: TrafficEvent[]) {
  return {
    type: 'FeatureCollection' as const,
    features: incidents
      .map((event) => {
        const geometry = normalizeLineGeometry(
          event.geometry?.type === 'LineString' ? event.geometry : null,
        )
        if (!geometry) {
          return null
        }
        return {
          type: 'Feature' as const,
          geometry,
          properties: {
            eventId: event.event_id,
            status: event.status,
            roadName: event.location.road_name,
            delaySec: event.metrics.delay_sec ?? 0,
            reason: event.metrics.primary_reason ?? event.metrics.category_label ?? '',
            category: event.metrics.category_label ?? '',
          },
        }
      })
      .filter((feature) => feature !== null),
  }
}

export function buildContextSegmentGeoJson(segments: TrafficEvent[]) {
  const base = buildSegmentGeoJson(segments)
  return {
    ...base,
    features: base.features.map((feature) => ({
      ...feature,
      properties: { ...feature.properties, context: true },
    })),
  }
}
