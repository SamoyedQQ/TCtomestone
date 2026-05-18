export function fmtDps(n) {
  if (n == null) return '—'
  return Math.round(n).toLocaleString('en-US')
}

export function fmtDuration(ms) {
  if (!ms) return '—'
  const s = Math.floor(ms / 1000)
  const m = Math.floor(s / 60)
  return `${m}:${String(s % 60).padStart(2, '0')}`
}

export function fmtDate(ms) {
  if (!ms) return '—'
  const d = new Date(ms)
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
}

export function fmtRank(n) {
  if (n === 1) return '#1'
  if (n === 2) return '#2'
  if (n === 3) return '#3'
  return `#${n}`
}
