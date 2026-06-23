import { useTranslation } from 'react-i18next'
import type { BottleneckItem } from '../types/engine'
import { formatDuration } from '../utils/trafficFormat'

interface BottleneckListProps {
  items: BottleneckItem[]
  selectedCorridorId: string | null
  onSelect: (corridorId: string) => void
}

export function BottleneckList({ items, selectedCorridorId, onSelect }: BottleneckListProps) {
  const { t } = useTranslation()

  if (items.length === 0) {
    return (
      <p className="sidebar__meta">{t('engine.noBottlenecks')}</p>
    )
  }

  return (
    <ol className="bottleneck-list">
      {items.slice(0, 5).map((item, index) => (
        <li key={item.corridor_id}>
          <button
            type="button"
            className={`bottleneck-item${selectedCorridorId === item.corridor_id ? ' bottleneck-item--selected' : ''}`}
            onClick={() => onSelect(item.corridor_id)}
          >
            <span className="bottleneck-item__rank">#{index + 1}</span>
            <span className="bottleneck-item__body">
              <strong>{item.corridor_name}</strong>
              <span>
                {item.port_name} · {formatDuration(item.avg_delay_sec)} {t('engine.delayShort')}
              </span>
            </span>
          </button>
        </li>
      ))}
    </ol>
  )
}
