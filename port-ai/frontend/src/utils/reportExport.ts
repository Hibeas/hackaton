import type { OperationalReport } from './operationalReport'

export function formatOperationalReportText(report: OperationalReport): string {
  const lines = [
    'PORT-AI — RAPORT OPERACYJNY KORYTARZA',
    '====================================',
    `Port: ${report.portName}`,
    `Korytarz: ${report.corridorName} (${report.corridorId})`,
    `Status: ${report.hasAlert ? `ALERT (severity ${report.severity ?? '—'})` : 'BEZ ALERTU'}`,
    '',
    'CO SIĘ DZIEJE',
    report.what,
    '',
    'PRAWDOPODOBNA PRZYCZYNA',
    report.why,
    '',
    'REKOMENDACJA',
    report.recommendation,
    '',
    'METRYKI',
    `- Incydenty TomTom: ${report.incidentCount}`,
    `- Suma opóźnień: ${report.totalDelaySec} s`,
  ]

  if (report.predictedDelaySec !== null && report.forecastHorizon !== null) {
    lines.push(
      `- Prognoza (+${report.forecastHorizon} min): ${report.predictedDelaySec} s`,
    )
  }

  if (report.dispatchImpact) {
    lines.push(`- Wpływ na dispatch: ${report.dispatchImpact}`)
  }

  lines.push('', `Wygenerowano: ${new Date().toISOString()}`)
  return lines.join('\n')
}

export async function copyOperationalReport(report: OperationalReport): Promise<void> {
  const text = formatOperationalReportText(report)
  await navigator.clipboard.writeText(text)
}

export function downloadOperationalReport(report: OperationalReport): void {
  const text = formatOperationalReportText(report)
  const slug = report.corridorId.replace(/[^a-z0-9_-]+/gi, '-').toLowerCase()
  const filename = `port-ai-report-${slug}-${Date.now()}.txt`
  const blob = new Blob([text], { type: 'text/plain;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = filename
  anchor.click()
  URL.revokeObjectURL(url)
}
