import type { PortConfig } from '../constants/ports'

export interface CorridorConfigResponse {
  schema_version?: number
  description?: string
  ports: PortConfig[]
}
