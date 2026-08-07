// Cloud-side counterpart to frontend/src/brandPresets.js's applyBrandTheme —
// theme APPLICATION only. There's no preset picker or logo upload here: the
// cloud never sets branding, it only mirrors whatever the station last
// pushed (see cloud-api/routers/ingest.py's station_info handling).
//
// Two consumers, two different mechanisms — both fed by the same derivation
// logic below so the math never drifts between them:
//   - StationDashboardPage (T1) calls applyBrandTheme(), which sets CSS vars
//     on the document root. Scoped to that page only — every call site must
//     invoke the returned cleanup function on unmount so a station's colors
//     never bleed into T2/Admin/Login, which share the same document root.
//   - StationsPage (T2) calls deriveBrandPalette() directly and applies the
//     result as literal inline styles per station card. It deliberately does
//     NOT go through CSS vars — T2 shows multiple stations at once, and the
//     global --brand-* vars can only ever hold one station's theme at a
//     time, so using them here would make every card show whichever station
//     happened to render/theme last. Literal per-card styles let each card
//     carry its own station's colors independently without touching page
//     chrome (TopBar, Overview bar, background), which stays neutral.
//
// Derivation: accent drives the background; everything else (surfaces,
// borders, text) is derived from it via WCAG contrast ratio (not a naive
// luminance threshold — see bestTextColor) so an arbitrary station-pushed
// accent stays readable. Primary/secondary pass through unchanged and are
// used for elements/sub-elements (selected states, section accents, badges).

function hexToRgb(hex) {
  let h = (hex || '').replace('#', '')
  if (h.length === 3) h = h.split('').map(c => c + c).join('')
  const n = parseInt(h, 16)
  if (h.length !== 6 || Number.isNaN(n)) return { r: 15, g: 17, b: 23 } // fallback: #0f1117
  return { r: (n >> 16) & 255, g: (n >> 8) & 255, b: n & 255 }
}

function toHex({ r, g, b }) {
  const c = v => Math.max(0, Math.min(255, Math.round(v))).toString(16).padStart(2, '0')
  return `#${c(r)}${c(g)}${c(b)}`
}

function relativeLuminance({ r, g, b }) {
  const chan = v => {
    const c = v / 255
    return c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4
  }
  return 0.2126 * chan(r) + 0.7152 * chan(g) + 0.0722 * chan(b)
}

function contrastRatio(hexA, hexB) {
  const l1 = relativeLuminance(hexToRgb(hexA)) + 0.05
  const l2 = relativeLuminance(hexToRgb(hexB)) + 0.05
  return l1 > l2 ? l1 / l2 : l2 / l1
}

const NEAR_BLACK = '#0f1117'
const NEAR_WHITE = '#f1f5f9'

// Picks whichever of near-black/near-white contrasts better against `bg` —
// a plain luminance>0.5 threshold misjudges mid-tone accents.
function bestTextColor(bg) {
  return contrastRatio(bg, NEAR_BLACK) >= contrastRatio(bg, NEAR_WHITE) ? NEAR_BLACK : NEAR_WHITE
}

function shade(hex, weight, towardWhite) {
  const c = hexToRgb(hex)
  const target = towardWhite ? { r: 255, g: 255, b: 255 } : { r: 0, g: 0, b: 0 }
  return toHex({ r: c.r + (target.r - c.r) * weight, g: c.g + (target.g - c.g) * weight, b: c.b + (target.b - c.b) * weight })
}

function blend(a, b, weight) {
  const ca = hexToRgb(a), cb = hexToRgb(b)
  return toHex({ r: ca.r + (cb.r - ca.r) * weight, g: ca.g + (cb.g - ca.g) * weight, b: ca.b + (cb.b - ca.b) * weight })
}

// Pure — computes the full palette from raw brand fields without touching
// the DOM. Shared by applyBrandTheme (T1, sets CSS vars) and StationsPage
// (T2, applies the object directly as literal per-card inline styles).
export function deriveBrandPalette({ primary, secondary, accent } = {}) {
  const bg = accent || '#0f1117'
  const p  = primary || '#3b82f6'
  const s  = secondary || '#6366f1'

  const text = bestTextColor(bg)
  const towardWhite = text === NEAR_WHITE

  return {
    primary: p,
    secondary: s,
    accent: bg,
    bg,
    surface: shade(bg, 0.07, towardWhite),
    surface2: shade(bg, 0.11, towardWhite),
    border: shade(bg, 0.22, towardWhite),
    borderSoft: shade(bg, 0.15, towardWhite),
    well: shade(bg, 0.045, towardWhite),
    primarySoft: blend(bg, p, 0.16),
    text,
    textDim: blend(text, bg, 0.4),
    textDimmer: blend(text, bg, 0.58),
    textFaint: blend(text, bg, 0.72),
  }
}

const CSS_VAR_MAP = {
  primary: '--brand-primary',
  secondary: '--brand-secondary',
  accent: '--brand-accent',
  bg: '--brand-bg',
  surface: '--brand-surface',
  surface2: '--brand-surface-2',
  border: '--brand-border',
  borderSoft: '--brand-border-soft',
  well: '--brand-well',
  primarySoft: '--brand-primary-soft',
  text: '--brand-text',
  textDim: '--brand-text-dim',
  textDimmer: '--brand-text-dimmer',
  textFaint: '--brand-text-faint',
}

export function applyBrandTheme(fields = {}) {
  const root = document.documentElement
  const palette = deriveBrandPalette(fields)

  Object.entries(CSS_VAR_MAP).forEach(([key, cssVar]) => {
    root.style.setProperty(cssVar, palette[key])
  })
  return () => Object.values(CSS_VAR_MAP).forEach(cssVar => root.style.removeProperty(cssVar))
}
