// Same palette and precedence the jira-rel-review skill uses for Excel fills.
const NDP_STATUS_CLASS: Record<string, string> = {
  'QC Approved': 'ndp-qc',
  'IIC Approved': 'ndp-iic',
  'IT Exec Approved': 'ndp-exec',
  Verified: 'ndp-verified',
}

export const NDP_LEGEND = Object.entries(NDP_STATUS_CLASS).map(([label, cls]) => ({
  label,
  cls,
}))

export function ndpStatusClass(status: string): string {
  return NDP_STATUS_CLASS[status?.trim()] ?? ''
}

export function formatDuration(seconds: number): string {
  const total = Math.max(0, Math.round(seconds))
  const m = Math.floor(total / 60)
  const s = total % 60
  if (m === 0) return `${s}s`
  return s === 0 ? `${m}m` : `${m}m ${s}s`
}

export function formatSyncTime(iso: string | null): string {
  if (!iso) return 'never'
  const d = new Date(iso)
  return d.toLocaleString(undefined, {
    month: '2-digit',
    day: '2-digit',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  })
}
