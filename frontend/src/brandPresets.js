// Color presets inspired by well-known fuel brands' public color
// associations — NOT their trademarked logo artwork, which isn't
// reproduced here (or anywhere in this app). If you're branding a station
// under a real trademark, upload that brand's actual logo file yourself
// (Branding -> Custom -> upload logo) rather than relying on anything
// bundled with the app.
// Note: 'accent' doubles as the page background color (see applyBrandTheme
// below), so Default/Custom deliberately use the app's original near-black
// neutral here rather than the primary blue — an unbranded station should
// still get the plain dark dashboard, not a blue-flooded page.
export const BRAND_PRESETS = [
  { id: 'default', name: 'Default', primary: '#3b82f6', secondary: '#6366f1', accent: '#0f1117' },
  { id: 'arco', name: 'Arco', primary: '#E31837', secondary: '#003DA5', accent: '#FFC72C' },
  { id: 'sinclair', name: 'Sinclair', primary: '#00693E', secondary: '#DA291C', accent: '#FFFFFF' },
  { id: 'chevron', name: 'Chevron', primary: '#1F4E96', secondary: '#ED1C24', accent: '#C4C4C4' },
  { id: 'mobil', name: 'Mobil', primary: '#ED1B2E', secondary: '#0A3B7C', accent: '#FFFFFF' },
  { id: 'pemex', name: 'Pemex', primary: '#006341', secondary: '#E4002B', accent: '#C69214' },
  { id: 'buckees', name: "Buc-ee's", primary: '#7B241C', secondary: '#D9C79E', accent: '#F5EBD8' },
  { id: 'custom', name: 'Custom', primary: '#3b82f6', secondary: '#6366f1', accent: '#0f1117' },
]

export function findPreset(id) {
  return BRAND_PRESETS.find(p => p.id === id) || BRAND_PRESETS[0]
}

// ---- Color math -----------------------------------------------------
// Small helpers to derive a full surface/border/text scale from a single
// accent color, so any accent (dark, light, saturated) produces a readable
// theme without hand-tuning each preset.

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

// WCAG relative luminance + contrast ratio.
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

// Picks whichever of near-black/near-white actually contrasts better against
// `bg`. A plain luminance>0.5 threshold misjudges mid-tone accents (e.g. a
// medium gold like Pemex's #C69214 scores as "dark" by luminance but reads
// far better with black text than white) — comparing real contrast ratios
// avoids that.
function bestTextColor(bg) {
  return contrastRatio(bg, NEAR_BLACK) >= contrastRatio(bg, NEAR_WHITE) ? NEAR_BLACK : NEAR_WHITE
}

// Blends `hex` toward black or white by `weight` (0-1).
function shade(hex, weight, towardWhite) {
  const c = hexToRgb(hex)
  const target = towardWhite ? { r: 255, g: 255, b: 255 } : { r: 0, g: 0, b: 0 }
  return toHex({
    r: c.r + (target.r - c.r) * weight,
    g: c.g + (target.g - c.g) * weight,
    b: c.b + (target.b - c.b) * weight,
  })
}

// Blends two arbitrary hex colors together by `weight` (0 = all `a`, 1 = all `b`).
function blend(a, b, weight) {
  const ca = hexToRgb(a), cb = hexToRgb(b)
  return toHex({
    r: ca.r + (cb.r - ca.r) * weight,
    g: ca.g + (cb.g - ca.g) * weight,
    b: ca.b + (cb.b - ca.b) * weight,
  })
}

// Applies brand colors as CSS custom properties on the document root, and
// returns a cleanup function to restore the defaults (used by the cloud
// frontend's per-station T1 page, which shouldn't leave a station's colors
// bleeding into the neutral T2/Admin/Login pages after navigating away).
//
// `accent` drives the page background. Everything else (surfaces, borders,
// text) is derived from it so it stays readable whether the accent is a
// near-black neutral (Default) or a bright brand white/gold/cream. `primary`
// and `secondary` are left as-is and used for elements/sub-elements —
// selected states, section accents, buttons, badges, icon fills.
export function applyBrandTheme({ primary, secondary, accent } = {}) {
  const root = document.documentElement
  const bg = accent || '#0f1117'
  const p  = primary || '#3b82f6'
  const s  = secondary || '#6366f1'

  const text = bestTextColor(bg)
  const towardWhite = text === NEAR_WHITE // dark bg -> surfaces step up toward white; light bg -> step down toward black

  const vars = {
    '--brand-primary': p,
    '--brand-secondary': s,
    '--brand-accent': bg, // kept for anything already reading --brand-accent directly
    '--brand-bg': bg,
    '--brand-surface': shade(bg, 0.07, towardWhite),
    '--brand-surface-2': shade(bg, 0.11, towardWhite),
    '--brand-border': shade(bg, 0.22, towardWhite),
    '--brand-border-soft': shade(bg, 0.15, towardWhite),
    '--brand-well': shade(bg, 0.045, towardWhite),
    '--brand-primary-soft': blend(bg, p, 0.16),
    '--brand-text': text,
    '--brand-text-dim': blend(text, bg, 0.4),
    '--brand-text-dimmer': blend(text, bg, 0.58),
    '--brand-text-faint': blend(text, bg, 0.72),
  }

  Object.entries(vars).forEach(([k, v]) => root.style.setProperty(k, v))
  return () => Object.keys(vars).forEach(k => root.style.removeProperty(k))
}

// Reads a File (from an <input type="file">) into a data: URL, resolving
// with null if it's not an image or the browser can't read it.
export function fileToDataUrl(file) {
  return new Promise((resolve, reject) => {
    if (!file || !file.type?.startsWith('image/')) { resolve(null); return }
    const reader = new FileReader()
    reader.onload = () => resolve(reader.result)
    reader.onerror = reject
    reader.readAsDataURL(file)
  })
}
