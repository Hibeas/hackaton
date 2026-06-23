import { useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'
import type { CityPortDashboard, PortOperationsPayload } from '../types/portOps'
import { filterPortOpsDashboard } from '../utils/portOpsHelpers'
import { formatDateTime } from '../utils/trafficFormat'

interface PortOpsPanelProps {
  portOperations: PortOperationsPayload | null | undefined
  selectedPortId: string
  embedded?: boolean
}

function statusClass(status: string): string {
  switch (status) {
    case 'CRITICAL':
      return 'port-ops__status--critical'
    case 'CONGESTION':
      return 'port-ops__status--congestion'
    case 'CLEAR':
      return 'port-ops__status--clear'
    default:
      return 'port-ops__status--unknown'
  }
}

function TerminalRow({
  terminal,
}: {
  terminal: CityPortDashboard['terminals'][number]
}) {
  const { t } = useTranslation()

  return (
    <article className="port-ops__terminal">
      <div className="port-ops__terminal-head">
        <strong>{terminal.label}</strong>
        <span className={`port-ops__demand port-ops__demand--${terminal.truck_demand_hint}`}>
          {t(`portOps.demand.${terminal.truck_demand_hint}`)}
        </span>
      </div>
      <p className="port-ops__terminal-meta">
        {terminal.active_last_hour
          ? t('portOps.movesLastHour', { count: terminal.moves_in_last_hour })
          : t('portOps.terminalIdle')}
        {' · '}
        {t('portOps.moves24h', { count: terminal.total_moves_24h })}
      </p>
      {terminal.tir_roads && terminal.tir_roads.length > 0 ? (
        <p className="port-ops__terminal-roads">TIR: {terminal.tir_roads.join(', ')}</p>
      ) : null}
    </article>
  )
}

export function PortOpsPanel({
  portOperations,
  selectedPortId,
  embedded = false,
}: PortOpsPanelProps) {
  const { t, i18n } = useTranslation()
  const [expanded, setExpanded] = useState(true)

  const cityGroups = useMemo(
    () => filterPortOpsDashboard(portOperations?.city_port_dashboard),
    [portOperations],
  )

  const activeGroup = useMemo(
    () => cityGroups.find((group) => group.key === selectedPortId) ?? cityGroups[0],
    [cityGroups, selectedPortId],
  )

  if (!portOperations || cityGroups.length === 0) {
    return (
      <section className={`port-ops${embedded ? ' port-ops--embedded' : ''}`}>
        <h2 className="dash-section__title">{t('portOps.title')}</h2>
        <p className="dash-empty">{t('portOps.loading')}</p>
      </section>
    )
  }

  const summary = portOperations.summary

  return (
    <section className={`port-ops${embedded ? ' port-ops--embedded' : ''}`}>
      <header className="port-ops__header">
        <div>
          <h2 className="dash-section__title">{t('portOps.title')}</h2>
          {portOperations.updated_at ? (
            <p className="dash-hint">
              {t('portOps.updatedAt')}: {formatDateTime(portOperations.updated_at, i18n.language)}
            </p>
          ) : null}
        </div>
        {!embedded ? (
          <button type="button" className="port-ops__toggle" onClick={() => setExpanded((v) => !v)}>
            {expanded ? t('portOps.collapse') : t('portOps.expand')}
          </button>
        ) : null}
      </header>

      {expanded || embedded ? (
        <>
          <div className="port-ops__summary">
            <span className="stat-chip">{t('portOps.callsInPort', { count: summary.active_port_calls ?? 0 })}</span>
            <span className="stat-chip">{t('portOps.gateMoves', { count: summary.container_move_count ?? 0 })}</span>
          </div>

          {activeGroup ? (
            <div className="port-ops__city">
              <div className="port-ops__city-head">
                <h3>{activeGroup.label}</h3>
                <span className={`port-ops__status ${statusClass(activeGroup.corridor_status)}`}>
                  {activeGroup.corridor_status_pl}
                </span>
              </div>

              {activeGroup.roads_status.length > 0 ? (
                <ul className="port-ops__roads">
                  {activeGroup.roads_status.slice(0, 6).map((road) => (
                    <li key={road.road} className={statusClass(road.status)}>
                      <span>{road.road}</span>
                      <span>{road.status_pl ?? road.status}</span>
                    </li>
                  ))}
                </ul>
              ) : null}

              <div className="port-ops__terminals">
                {activeGroup.terminals.map((terminal) => (
                  <TerminalRow key={terminal.terminal} terminal={terminal} />
                ))}
              </div>
            </div>
          ) : null}
        </>
      ) : null}
    </section>
  )
}
