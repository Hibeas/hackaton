import { useTranslation } from 'react-i18next'
import type { PortConfig } from '../constants/ports'

interface PortTabsProps {
  ports: PortConfig[]
  selectedPortId: string
  onSelect: (portId: string) => void
  eventCounts: Record<string, number>
}

export function PortTabs({ ports, selectedPortId, onSelect, eventCounts }: PortTabsProps) {
  const { t } = useTranslation()

  return (
    <div className="port-tabs" role="tablist" aria-label={t('engine.ports')}>
      {ports.map((port) => {
        const count = eventCounts[port.id] ?? 0
        const isActive = port.id === selectedPortId
        return (
          <button
            key={port.id}
            type="button"
            role="tab"
            aria-selected={isActive}
            className={`port-tab${isActive ? ' port-tab--active' : ''}`}
            onClick={() => onSelect(port.id)}
          >
            <span>{port.name}</span>
            {count > 0 ? <span className="port-tab__badge">{count}</span> : null}
          </button>
        )
      })}
    </div>
  )
}
