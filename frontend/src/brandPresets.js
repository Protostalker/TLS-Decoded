// Color presets inspired by well-known fuel brands' public color
// associations — NOT their trademarked logo artwork, which isn't
// reproduced here (or anywhere in this app). If you're branding a station
// under a real trademark, upload that brand's actual logo file yourself
// (Branding -> Custom -> upload logo) rather than relying on anything
// bundled with the app.
export const BRAND_PRESETS = [
  { id: 'default', name: 'Default', primary: '#3b82f6', secondary: '#6366f1', accent: '#3b82f6' },
  { id: 'arco', name: 'Arco', primary: '#E31837', secondary: '#003DA5', accent: '#FFC72C' },
  { id: 'sinclair', name: 'Sinclair', primary: '#00693E', secondary: '#DA291C', accent: '#FFFFFF' },
  { id: 'chevron', name: 'Chevron', primary: '#1F4E96', secondary: '#ED1C24', accent: '#C4C4C4' },
  { id: 'mobil', name: 'Mobil', primary: '#ED1B2E', secondary: '#0A3B7C', accent: '#FFFFFF' },
  { id: 'pemex', name: 'Pemex', primary: '#006341', secondary: '#E4002B', accent: '#C69214' },
  { id: 'buckees', name: "Buc-ee's", primary: '#7B241C', secondary: '#D9C79E', accent: '#F5EBD8' },
  { id: 'custom', name: 'Custom', primary: '#3b82f6', secondary: '#6366f1', accent: '#3b82f6' },
]

export function findPreset(id) {
  return BRAND_PRESETS.find(p => p.id === id) || BRAND_PRESETS[0]
}

// Applies brand colors as CSS custom properties on the document root, and
// returns a cleanup function to restore the defaults (used by the cloud
// frontend's per-station T1 page, which shouldn't leave a station's colors
// bleeding into the neutral T2/Admin/Login pages after navigating away).
export function applyBrandTheme({ primary, secondary, accent } = {}) {
  const root = document.documentElement
  root.style.setProperty('--brand-primary', primary || '#3b82f6')
  root.style.setProperty('--brand-secondary', secondary || '#6366f1')
  root.style.setProperty('--brand-accent', accent || primary || '#3b82f6')
  return () => {
    root.style.removeProperty('--brand-primary')
    root.style.removeProperty('--brand-secondary')
    root.style.removeProperty('--brand-accent')
  }
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
