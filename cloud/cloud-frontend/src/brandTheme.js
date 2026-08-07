// Cloud-side counterpart to frontend/src/brandPresets.js's applyBrandTheme —
// theme APPLICATION only. There's no preset picker or logo upload here: the
// cloud never sets branding, it only mirrors whatever the station last
// pushed (see cloud-api/routers/ingest.py's station_info handling). Scoped
// to T1 (StationDashboardPage) only — every call site must invoke the
// returned cleanup function on unmount so a station's colors never bleed
// into T2/Admin/Login, which share the same document root.
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
