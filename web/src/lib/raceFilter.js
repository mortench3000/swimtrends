// Canonical order for the discipline chips. Individual strokes only; relays are
// collapsed into the single 'Stafet' option regardless of their stroke (Fri/HM…).
const STROKE_ORDER = ['Fri', 'Ryg', 'Bryst', 'Fly', 'IM']
const GENDER_ORDER = ['M', 'F', 'X']

// discipline: 'all' | 'Stafet' | <stroke>.  gender: 'all' | 'M' | 'F' | 'X'.
export function filterRaces(races, { discipline = 'all', gender = 'all' } = {}) {
  return races.filter((r) => {
    if (discipline === 'Stafet') {
      if (!r.is_relay) return false
    } else if (discipline !== 'all') {
      if (r.is_relay || r.stroke !== discipline) return false
    }
    if (gender !== 'all' && r.gender !== gender) return false
    return true
  })
}

export function disciplineOptions(races) {
  const present = new Set(races.filter((r) => !r.is_relay).map((r) => r.stroke))
  const opts = ['all', ...STROKE_ORDER.filter((s) => present.has(s))]
  if (races.some((r) => r.is_relay)) opts.push('Stafet')
  return opts
}

export function genderOptions(races) {
  const present = new Set(races.map((r) => r.gender))
  return ['all', ...GENDER_ORDER.filter((g) => present.has(g))]
}

// URL query-string form of the filters (?discipline=IM&gender=M). Unknown or
// wrong-case values read as 'all'; 'all' is omitted when writing.
export function filtersFromSearch(search) {
  const p = new URLSearchParams(search)
  const d = p.get('discipline')
  const g = p.get('gender')
  return {
    discipline: [...STROKE_ORDER, 'Stafet'].includes(d) ? d : 'all',
    gender: GENDER_ORDER.includes(g) ? g : 'all',
  }
}

export function filtersToSearch({ discipline = 'all', gender = 'all' } = {}) {
  const p = new URLSearchParams()
  if (discipline !== 'all') p.set('discipline', discipline)
  if (gender !== 'all') p.set('gender', gender)
  const s = p.toString()
  return s ? `?${s}` : ''
}
