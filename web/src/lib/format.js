const DASH = '–'
const nf = new Intl.NumberFormat('da-DK')

export function formatTime(cs) {
  if (cs == null) return DASH
  const m = Math.floor(cs / 6000)
  const s = Math.floor((cs % 6000) / 100)
  const c = cs % 100
  const ss = String(s).padStart(2, '0')
  const cc = String(c).padStart(2, '0')
  return m > 0 ? `${m}:${ss}.${cc}` : `${s}.${cc}`
}
export const formatTimeStr = (s) => (s == null ? DASH : s)
export const formatInt = (n) => (n == null ? DASH : nf.format(n))
export const formatPoints = (n) => (n == null ? DASH : `${nf.format(n)} p`)

// Share of a total, as whole percent. null when either side is missing, so the
// caller can just leave it out.
export const formatShare = (part, total) =>
  part == null || !total ? null : `${Math.round((part / total) * 100)} %`

export function formatDelta(curr, prev, { lowerIsBetter = false } = {}) {
  if (curr == null || prev == null) return { text: DASH, dir: 'flat' }
  const d = curr - prev
  if (d === 0) return { text: '0', dir: 'flat' }
  const better = lowerIsBetter ? d < 0 : d > 0
  const sign = d > 0 ? '+' : '−' // U+2212 minus
  return { text: `${sign}${nf.format(Math.abs(d))}`, dir: better ? 'good' : 'bad' }
}
