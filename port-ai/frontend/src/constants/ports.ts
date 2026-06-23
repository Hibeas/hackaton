export type GeofenceType =
  | 'APPROACH_CORRIDOR'
  | 'BOTTLENECK'
  | 'BUFFER_ZONE'
  | 'GATE_ZONE'
  | 'PORT_ACCESS'
  | 'CRITICAL_INFRASTRUCTURE'

export type BusinessPriority = 'CRITICAL' | 'HIGH'

export interface CorridorBbox {
  min_lat: number
  max_lat: number
  min_lon: number
  max_lon: number
}

export type LatLng = [number, number]

export interface CorridorConfig {
  id: string
  name: string
  city: string
  geofence_type: GeofenceType
  business_priority: BusinessPriority
  logistics_weight: number
  priority_weight: number
  impacts_port_access: boolean
  bbox: CorridorBbox
  polygon?: LatLng[]
  terminals: string[]
}

export interface PortGeofence {
  bbox: CorridorBbox
  polygon?: LatLng[]
}

export interface PortConfig {
  id: string
  name: string
  terminals: string[]
  geofence?: PortGeofence
  corridors: CorridorConfig[]
}

export const PORTS: PortConfig[] = [
  {
    id: 'gdynia',
    name: 'Port Gdynia',
    terminals: ['GCT', 'BCT'],
    corridors: [
      {
        id: 'estakada_kwiatkowskiego',
        name: 'Estakada Kwiatkowskiego',
        city: 'Gdynia',
        geofence_type: 'APPROACH_CORRIDOR',
        business_priority: 'CRITICAL',
        logistics_weight: 10,
        priority_weight: 1.0,
        impacts_port_access: true,
        bbox: { min_lat: 54.505, max_lat: 54.528, min_lon: 18.522, max_lon: 18.568 },
        terminals: ['GCT', 'BCT'],
      },
      {
        id: 'janka_wisniewskiego',
        name: 'Janka Wiśniewskiego',
        city: 'Gdynia',
        geofence_type: 'APPROACH_CORRIDOR',
        business_priority: 'HIGH',
        logistics_weight: 8,
        priority_weight: 0.8,
        impacts_port_access: true,
        bbox: { min_lat: 54.518, max_lat: 54.542, min_lon: 18.532, max_lon: 18.562 },
        terminals: ['BCT'],
      },
      {
        id: 'ul_polska',
        name: 'Polska',
        city: 'Gdynia',
        geofence_type: 'PORT_ACCESS',
        business_priority: 'HIGH',
        logistics_weight: 8,
        priority_weight: 0.8,
        impacts_port_access: true,
        bbox: { min_lat: 54.526, max_lat: 54.552, min_lon: 18.542, max_lon: 18.572 },
        terminals: ['GCT'],
      },
      {
        id: 's6_wezel_estakada',
        name: 'Węzeł Obwodnicy Trójmiasta → Estakada',
        city: 'Gdynia',
        geofence_type: 'BUFFER_ZONE',
        business_priority: 'HIGH',
        logistics_weight: 7,
        priority_weight: 0.7,
        impacts_port_access: true,
        bbox: { min_lat: 54.488, max_lat: 54.518, min_lon: 18.458, max_lon: 18.528 },
        terminals: ['GCT', 'BCT'],
      },
    ],
  },
  {
    id: 'gdansk',
    name: 'Port Gdańsk',
    terminals: ['DCT'],
    corridors: [
      {
        id: 'trasa_sucharskiego',
        name: 'Trasa Sucharskiego',
        city: 'Gdańsk',
        geofence_type: 'APPROACH_CORRIDOR',
        business_priority: 'CRITICAL',
        logistics_weight: 10,
        priority_weight: 1.0,
        impacts_port_access: true,
        bbox: { min_lat: 54.328, max_lat: 54.398, min_lon: 18.592, max_lon: 18.718 },
        terminals: ['DCT'],
      },
      {
        id: 'tunel_martwa_wisla',
        name: 'Tunel pod Martwą Wisłą',
        city: 'Gdańsk',
        geofence_type: 'BOTTLENECK',
        business_priority: 'CRITICAL',
        logistics_weight: 10,
        priority_weight: 1.0,
        impacts_port_access: true,
        bbox: { min_lat: 54.356, max_lat: 54.374, min_lon: 18.664, max_lon: 18.692 },
        terminals: ['DCT'],
      },
      {
        id: 'marynarki_polskiej',
        name: 'Marynarki Polskiej',
        city: 'Gdańsk',
        geofence_type: 'APPROACH_CORRIDOR',
        business_priority: 'HIGH',
        logistics_weight: 8,
        priority_weight: 0.8,
        impacts_port_access: true,
        bbox: { min_lat: 54.512, max_lat: 54.548, min_lon: 18.498, max_lon: 18.542 },
        terminals: ['DCT'],
      },
      {
        id: 'wezel_s7_sucharskiego',
        name: 'Węzeł S7 / Sucharskiego',
        city: 'Gdańsk',
        geofence_type: 'BUFFER_ZONE',
        business_priority: 'HIGH',
        logistics_weight: 7,
        priority_weight: 0.7,
        impacts_port_access: true,
        bbox: { min_lat: 54.328, max_lat: 54.348, min_lon: 18.595, max_lon: 18.628 },
        terminals: ['DCT'],
      },
      {
        id: 'baltic_hub_gate',
        name: 'Baltic Hub Gate Area',
        city: 'Gdańsk',
        geofence_type: 'GATE_ZONE',
        business_priority: 'CRITICAL',
        logistics_weight: 10,
        priority_weight: 1.0,
        impacts_port_access: true,
        bbox: { min_lat: 54.375, max_lat: 54.395, min_lon: 18.655, max_lon: 18.678 },
        terminals: ['DCT'],
      },
    ],
  },
  {
    id: 'szczecin',
    name: 'Port Szczecin',
    terminals: ['DBPS'],
    corridors: [
      {
        id: 'dk10_stargard',
        name: 'DK10 (od strony Stargardu)',
        city: 'Szczecin',
        geofence_type: 'APPROACH_CORRIDOR',
        business_priority: 'HIGH',
        logistics_weight: 8,
        priority_weight: 0.8,
        impacts_port_access: true,
        bbox: { min_lat: 53.408, max_lat: 53.478, min_lon: 14.608, max_lon: 14.718 },
        terminals: ['DBPS'],
      },
      {
        id: 'a6_szczecin',
        name: 'A6 → Szczecin',
        city: 'Szczecin',
        geofence_type: 'BUFFER_ZONE',
        business_priority: 'HIGH',
        logistics_weight: 7,
        priority_weight: 0.7,
        impacts_port_access: true,
        bbox: { min_lat: 53.418, max_lat: 53.488, min_lon: 14.448, max_lon: 14.588 },
        terminals: ['DBPS'],
      },
      {
        id: 'ul_gdanska',
        name: 'Ulica Gdańska',
        city: 'Szczecin',
        geofence_type: 'APPROACH_CORRIDOR',
        business_priority: 'CRITICAL',
        logistics_weight: 10,
        priority_weight: 1.0,
        impacts_port_access: true,
        bbox: { min_lat: 53.428, max_lat: 53.462, min_lon: 14.522, max_lon: 14.562 },
        terminals: ['DBPS'],
      },
      {
        id: 'ul_energetykow',
        name: 'Energetyków',
        city: 'Szczecin',
        geofence_type: 'PORT_ACCESS',
        business_priority: 'HIGH',
        logistics_weight: 8,
        priority_weight: 0.8,
        impacts_port_access: true,
        bbox: { min_lat: 53.412, max_lat: 53.442, min_lon: 14.532, max_lon: 14.572 },
        terminals: ['DBPS'],
      },
      {
        id: 'basen_gorniczy',
        name: 'Rejon Basenu Górniczego',
        city: 'Szczecin',
        geofence_type: 'GATE_ZONE',
        business_priority: 'CRITICAL',
        logistics_weight: 10,
        priority_weight: 1.0,
        impacts_port_access: true,
        bbox: { min_lat: 53.402, max_lat: 53.432, min_lon: 14.542, max_lon: 14.582 },
        terminals: ['DBPS'],
      },
    ],
  },
  {
    id: 'swinoujscie',
    name: 'Port Świnoujście',
    terminals: [],
    corridors: [
      {
        id: 's3_swinoujscie',
        name: 'S3',
        city: 'Świnoujście',
        geofence_type: 'APPROACH_CORRIDOR',
        business_priority: 'CRITICAL',
        logistics_weight: 10,
        priority_weight: 1.0,
        impacts_port_access: true,
        bbox: { min_lat: 53.892, max_lat: 53.938, min_lon: 14.208, max_lon: 14.278 },
        terminals: [],
      },
      {
        id: 'tunel_swinoujscie',
        name: 'Tunel w Świnoujściu',
        city: 'Świnoujście',
        geofence_type: 'BOTTLENECK',
        business_priority: 'CRITICAL',
        logistics_weight: 10,
        priority_weight: 1.0,
        impacts_port_access: true,
        bbox: { min_lat: 53.904, max_lat: 53.922, min_lon: 14.242, max_lon: 14.268 },
        terminals: [],
      },
      {
        id: 'terminal_promowy',
        name: 'Terminal Promowy',
        city: 'Świnoujście',
        geofence_type: 'GATE_ZONE',
        business_priority: 'HIGH',
        logistics_weight: 8,
        priority_weight: 0.8,
        impacts_port_access: true,
        bbox: { min_lat: 53.906, max_lat: 53.924, min_lon: 14.250, max_lon: 14.282 },
        terminals: [],
      },
      {
        id: 'terminal_lng',
        name: 'Terminal LNG',
        city: 'Świnoujście',
        geofence_type: 'CRITICAL_INFRASTRUCTURE',
        business_priority: 'CRITICAL',
        logistics_weight: 10,
        priority_weight: 1.0,
        impacts_port_access: true,
        bbox: { min_lat: 53.914, max_lat: 53.936, min_lon: 14.220, max_lon: 14.258 },
        terminals: [],
      },
      {
        id: 'wezel_s3_port',
        name: 'Rejon Węzła S3 → Port',
        city: 'Świnoujście',
        geofence_type: 'BUFFER_ZONE',
        business_priority: 'HIGH',
        logistics_weight: 7,
        priority_weight: 0.7,
        impacts_port_access: true,
        bbox: { min_lat: 53.896, max_lat: 53.918, min_lon: 14.228, max_lon: 14.262 },
        terminals: [],
      },
    ],
  },
]

export function getPort(id: string): PortConfig | undefined {
  return PORTS.find((port) => port.id === id)
}

export function getCorridor(corridorId: string): CorridorConfig | undefined {
  for (const port of PORTS) {
    const corridor = port.corridors.find((item) => item.id === corridorId)
    if (corridor) {
      return corridor
    }
  }
  return undefined
}

export function getPortForCorridor(corridorId: string): PortConfig | undefined {
  return PORTS.find((port) => port.corridors.some((corridor) => corridor.id === corridorId))
}
