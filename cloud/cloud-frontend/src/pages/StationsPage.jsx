import React, { useEffect, useState } from 'react'
import { Link, Navigate } from 'react-router-dom'
import { api } from '../api/client.js'
import TopBar from '../components/TopBar.jsx'
import StalenessBadge from '../components/StalenessBadge.jsx'
import Footer from '../components/Footer.jsx'
import { deriveBrandPalette } from '../brandTheme.js'
import { useAuth } from '../context/AuthContext.jsx'

const card = {
  background: '#161b27', border: '1px solid #1e2130', borderRadius: 14, padding: 18,
}

// Page chrome (this constant, TopBar, the Overview box, weather roll-up,
// empty/error states) never themes itself — a customer with stations under
// multiple brands shouldn't have the whole hub flip colors depending on
// load order. Only individual station cards below theme themselves, each
// from that station's own mirrored fields — see stationCardTheme().
const NEUTRAL_CARD_THEME = {
  bg: '#161b27', surface: '#161b27', border: '#1e2130', borderSoft: '#1e2130',
  well: '#111827', primary: '#3b82f6', text: '#e2e8f0',
  textDim: '#94a3b8', textDimmer: '#64748b', textFaint: '#475569',
}

// A station only gets a themed card once it's actually set a brand locally
// (mirrored up via sync) — no primary/accent means it stays on the neutral
// default look, same as before branding existed.
function stationCardTheme(station) {
  if (!station.brand_primary_color && !station.brand_accent_color) return NEUTRAL_CARD_THEME
  return deriveBrandPalette({
    primary: station.brand_primary_color,
    secondary: station.brand_secondary_color,
    accent: station.brand_accent_color,
  })
}

export default function StationsPage() {
  const { user } = useAuth()
  const isSupplier = user?.role === 'supplier'
  const [stations, setStations] = useState(null)
  const [summary, setSummary] = useState(null)
  const [weather, setWeather] = useState(null)
  const [error, setError] = useState(null)

  // Suppliers have their own dedicated dashboard — redirect immediately.
  // All hooks are declared above so this early return doesn't violate rules.
  useEffect(() => {
    if (isSupplier) return
    ;(async () => {
      try {
        const [s, sum] = await Promise.all([api.myStations(), api.combinedStats()])
        setStations(s)
        setSummary(sum)
      } catch (e) {
        setError(e.message)
      }
      // Best-effort, separate from the above — a weather hiccup or a station
      // with no zip set shouldn't block the rest of the hub from loading.
      api.weatherSummary().then(setWeather).catch(() => setWeather({}))
    })()
  }, [isSupplier])

  if (isSupplier) return <Navigate to="/supplier" replace />

  const stationsWithWarnings = stations && weather
    ? stations.filter(s => weather[s.id]?.top_recommendation)
    : []

  return (
    <div style={{ minHeight: '100vh', background: '#0f1117' }}>
      <TopBar title="Your Stations" />
      <main style={{ padding: 24, maxWidth: 1260, margin: '0 auto' }}>
        {error && <ErrorBox message={error} />}

        {stations === null && !error && (
          <div style={{ color: '#64748b', padding: 40, textAlign: 'center' }}>Loading…</div>
        )}

        {stations && stations.length === 0 && (
          <div style={{ ...card, textAlign: 'center', color: '#64748b' }}>
            No stations are assigned to your account yet. Ask an admin to assign one.
          </div>
        )}

        {/* Weather warning roll-up — quick "anything I should act on today"
            glance before drilling into any one station. */}
        {stationsWithWarnings.length > 0 && (
          <div style={{ ...card, marginBottom: 20, border: '1px solid #7f1d1d', background: '#2a1010' }}>
            <div style={{ fontSize: 13, fontWeight: 700, color: '#fca5a5', marginBottom: 10 }}>
              Weather heads-up
            </div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
              {stationsWithWarnings.map(s => (
                <div key={s.id} style={{ fontSize: 12, color: '#fca5a5' }}>
                  <strong>{s.name}:</strong> {weather[s.id].top_recommendation}
                  {weather[s.id].recommendation_count > 1 && ` (+${weather[s.id].recommendation_count - 1} more)`}
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Combined stats — same pattern as the per-station /stats/summary,
            one level up: loop over assigned stations instead of tanks. Shown
            any time there's at least one station, so this is always a quick
            "everything at a glance" hub, not just a multi-station feature. */}
        {stations && stations.length > 0 && summary && (
          <div style={{ ...card, marginBottom: 20 }}>
            <div style={{ fontSize: 13, fontWeight: 700, color: '#94a3b8', marginBottom: 12 }}>
              {stations.length > 1 ? 'Overview — all stations' : 'Overview'}
            </div>
            <div style={{ display: 'flex', gap: 24, flexWrap: 'wrap' }}>
              <Stat label="Today consumed" value={fmtGal(summary.today_consumed_gallons)} />
              {!isSupplier && <Stat label="Today profit" value={fmtUsd(summary.today_profit_dollars)} />}
              <Stat label="7-day consumed" value={fmtGal(summary.week_consumed_gallons)} />
              {!isSupplier && <Stat label="7-day margin" value={fmtUsd(summary.total_margin_7d)} />}
              <Stat label="30-day avg/day" value={fmtGal(summary.avg_daily_gallons_30d)} />
              {stations.length > 1 && <Stat label="Stations" value={String(stations.length)} />}
            </div>
          </div>
        )}

        {stations && stations.length > 0 && (
          <div style={{
            display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(300px, 380px))',
            justifyContent: 'center', gap: 16,
          }}>
            {stations.map(s => {
              const stat = summary?.stations?.find(x => x.station_id === s.id)
              const w = weather?.[s.id]
              // Full per-card theme derived from this station's own mirrored
              // fields (literal inline styles, never the global --brand-*
              // vars — see stationCardTheme() above and brandTheme.js). This
              // is what makes branding "visible on T2": each card previews
              // that station's actual T1 look, so a multi-brand operator can
              // tell their stations apart at a glance without opening one.
              const theme = stationCardTheme(s)
              return (
                <Link key={s.id} to={`/stations/${s.id}`} style={{ textDecoration: 'none', color: 'inherit' }}>
                  <div style={{
                         background: theme.bg, borderRadius: 14, padding: 18,
                         border: `1px solid ${theme.border}`, borderLeft: `4px solid ${theme.primary}`,
                         cursor: 'pointer', transition: 'border-color 0.15s',
                       }}
                       onMouseEnter={e => e.currentTarget.style.borderColor = theme.primary}
                       onMouseLeave={e => e.currentTarget.style.borderColor = theme.border}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
                      <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                        <StationBadge station={s} theme={theme} />
                        <div>
                          <div style={{ fontWeight: 800, fontSize: 16, color: theme.text }}>{s.name}</div>
                          <div style={{ fontSize: 11, color: theme.textDimmer, marginTop: 2 }}>{s.customer_name}</div>
                        </div>
                      </div>
                      <div style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
                        {stat?.water_alert && (
                          <span style={{ fontSize: 10, color: '#fca5a5', background: '#450a0a', borderRadius: 6, padding: '2px 6px' }}>
                            water
                          </span>
                        )}
                        {!s.active && (
                          <span style={{ fontSize: 10, color: '#fca5a5', background: '#450a0a', borderRadius: 6, padding: '2px 6px' }}>
                            inactive
                          </span>
                        )}
                      </div>
                    </div>

                    <div style={{ marginTop: 14, display: 'flex', gap: 10, alignItems: 'center', flexWrap: 'wrap' }}>
                      <StalenessBadge lastSyncAt={s.last_sync_at} />
                      {w?.current && (
                        <span style={{ fontSize: 11, color: theme.textDimmer }}>
                          {w.current.temperature}°{w.current.temperature_unit} · {w.current.short_forecast}
                        </span>
                      )}
                    </div>

                    {stat && (
                      <>
                        <div style={{
                          display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 12,
                          marginTop: 14, fontSize: 12,
                        }}>
                          <Stat compact label="Today" value={fmtGal(stat.today_consumed_gallons)} theme={theme} />
                          {!isSupplier && <Stat compact label="Profit" value={fmtUsd(stat.today_profit_dollars)} theme={theme} />}
                          <Stat compact label="7d gal" value={fmtGal(stat.week_consumed_gallons)} theme={theme} />
                          {!isSupplier && <Stat compact label="7d margin" value={fmtUsd(stat.total_margin_7d)} theme={theme} />}
                          <Stat compact label="30d avg/day" value={fmtGal(stat.avg_daily_gallons_30d)} theme={theme} />
                          <Stat compact label="Last delivery" value={stat.days_since_last_delivery !== null && stat.days_since_last_delivery !== undefined ? `${stat.days_since_last_delivery}d ago` : '—'} theme={theme} />
                        </div>

                        {stat.tanks?.length > 0 && (
                          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, marginTop: 14 }}>
                            {stat.tanks.map(t => (
                              <TankPill key={t.tank_local_id} tank={t} theme={theme} hideFinancials={isSupplier} />
                            ))}
                          </div>
                        )}
                      </>
                    )}
                  </div>
                </Link>
              )
            })}
          </div>
        )}
      </main>
      <Footer />
    </div>
  )
}

// Per-card only — deliberately does NOT reuse BrandLogo/brandTheme.js's
// applyBrandTheme, which reads the global --brand-* CSS vars. Those vars are
// reserved for T1 (StationDashboardPage) alone; a station picker card shows
// its brand using that station's own field values directly (via the `theme`
// object passed down from stationCardTheme()), so cards for different
// brands can sit side by side and the page chrome (TopBar, Overview bar)
// never shifts color.
function StationBadge({ station, theme }) {
  const { brand_logo_data_url: logo, brand_primary_color: primary, brand_secondary_color: secondary } = station
  if (logo) {
    return (
      <img
        src={logo} alt="" width={28} height={28}
        style={{ borderRadius: 7, objectFit: 'contain', background: '#fff', flexShrink: 0 }}
      />
    )
  }
  if (!primary) return null
  return (
    <div style={{
      width: 28, height: 28, borderRadius: 7, flexShrink: 0,
      background: secondary ? `linear-gradient(135deg, ${primary}, ${secondary})` : primary,
      border: `1px solid ${theme.border}`,
    }} />
  )
}

function TankPill({ tank, theme, hideFinancials }) {
  const pct = tank.capacity_gallons && tank.current_volume_gallons != null
    ? Math.round((tank.current_volume_gallons / tank.capacity_gallons) * 100)
    : null
  return (
    <div style={{
      fontSize: 10, color: tank.water_alert ? '#fca5a5' : theme.textDim,
      background: theme.well, border: `1px solid ${tank.water_alert ? '#7f1d1d' : theme.borderSoft}`,
      borderRadius: 8, padding: '4px 8px', display: 'flex', gap: 6, alignItems: 'center',
    }}>
      <span style={{ fontWeight: 700, color: theme.text }}>{tank.tank_name}</span>
      {pct !== null && <span>{pct}%</span>}
      {!hideFinancials && tank.current_margin_per_gallon != null && <span>${tank.current_margin_per_gallon.toFixed(2)}/gal</span>}
    </div>
  )
}

// Also used by the neutral Overview/weather boxes above (no theme passed —
// falls back to the original hardcoded look, same as before branding).
function Stat({ label, value, compact, theme }) {
  const t = theme || NEUTRAL_CARD_THEME
  return (
    <div>
      <div style={{ fontSize: compact ? 10 : 11, color: t.textDimmer }}>{label}</div>
      <div style={{ fontSize: compact ? 14 : 20, fontWeight: 700, color: t.text }}>{value}</div>
    </div>
  )
}

function ErrorBox({ message }) {
  return (
    <div style={{
      background: '#450a0a', border: '1px solid #ef4444', borderRadius: 10,
      padding: '14px 18px', color: '#fca5a5', fontSize: 13, marginBottom: 20,
    }}>{message}</div>
  )
}

function fmtGal(v) { return v === null || v === undefined ? '—' : `${Math.round(v).toLocaleString()} gal` }
function fmtUsd(v) { return v === null || v === undefined ? '—' : `$${v.toLocaleString(undefined, { maximumFractionDigits: 2 })}` }
