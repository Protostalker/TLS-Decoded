import React, { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../api/client.js'
import TopBar from '../components/TopBar.jsx'
import StalenessBadge from '../components/StalenessBadge.jsx'

const card = {
  background: '#161b27', border: '1px solid #1e2130', borderRadius: 14, padding: 18,
}

export default function StationsPage() {
  const [stations, setStations] = useState(null)
  const [summary, setSummary] = useState(null)
  const [weather, setWeather] = useState(null)
  const [error, setError] = useState(null)

  useEffect(() => {
    (async () => {
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
  }, [])

  const stationsWithWarnings = stations && weather
    ? stations.filter(s => weather[s.id]?.top_recommendation)
    : []

  return (
    <div style={{ minHeight: '100vh', background: '#0f1117' }}>
      <TopBar title="Your Stations" />
      <main style={{ padding: 24, maxWidth: 1100, margin: '0 auto' }}>
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
              <Stat label="Today profit" value={fmtUsd(summary.today_profit_dollars)} />
              <Stat label="7-day consumed" value={fmtGal(summary.week_consumed_gallons)} />
              <Stat label="7-day margin" value={fmtUsd(summary.total_margin_7d)} />
              <Stat label="30-day avg/day" value={fmtGal(summary.avg_daily_gallons_30d)} />
              {stations.length > 1 && <Stat label="Stations" value={String(stations.length)} />}
            </div>
          </div>
        )}

        {stations && stations.length > 0 && (
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(320px, 1fr))', gap: 16 }}>
            {stations.map(s => {
              const stat = summary?.stations?.find(x => x.station_id === s.id)
              const w = weather?.[s.id]
              return (
                <Link key={s.id} to={`/stations/${s.id}`} style={{ textDecoration: 'none', color: 'inherit' }}>
                  <div style={{ ...card, cursor: 'pointer', transition: 'border-color 0.15s' }}
                       onMouseEnter={e => e.currentTarget.style.borderColor = '#3b82f6'}
                       onMouseLeave={e => e.currentTarget.style.borderColor = '#1e2130'}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
                      <div>
                        <div style={{ fontWeight: 800, fontSize: 16 }}>{s.name}</div>
                        <div style={{ fontSize: 11, color: '#64748b', marginTop: 2 }}>{s.customer_name}</div>
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
                        <span style={{ fontSize: 11, color: '#64748b' }}>
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
                          <Stat compact label="Today" value={fmtGal(stat.today_consumed_gallons)} />
                          <Stat compact label="Profit" value={fmtUsd(stat.today_profit_dollars)} />
                          <Stat compact label="7d gal" value={fmtGal(stat.week_consumed_gallons)} />
                          <Stat compact label="7d margin" value={fmtUsd(stat.total_margin_7d)} />
                          <Stat compact label="30d avg/day" value={fmtGal(stat.avg_daily_gallons_30d)} />
                          <Stat compact label="Last delivery" value={stat.days_since_last_delivery !== null && stat.days_since_last_delivery !== undefined ? `${stat.days_since_last_delivery}d ago` : '—'} />
                        </div>

                        {stat.tanks?.length > 0 && (
                          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, marginTop: 14 }}>
                            {stat.tanks.map(t => (
                              <TankPill key={t.tank_local_id} tank={t} />
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
    </div>
  )
}

function TankPill({ tank }) {
  const pct = tank.capacity_gallons && tank.current_volume_gallons != null
    ? Math.round((tank.current_volume_gallons / tank.capacity_gallons) * 100)
    : null
  return (
    <div style={{
      fontSize: 10, color: tank.water_alert ? '#fca5a5' : '#94a3b8',
      background: '#111827', border: `1px solid ${tank.water_alert ? '#7f1d1d' : '#1e2130'}`,
      borderRadius: 8, padding: '4px 8px', display: 'flex', gap: 6, alignItems: 'center',
    }}>
      <span style={{ fontWeight: 700, color: '#cbd5e1' }}>{tank.tank_name}</span>
      {pct !== null && <span>{pct}%</span>}
      {tank.current_margin_per_gallon != null && <span>${tank.current_margin_per_gallon.toFixed(2)}/gal</span>}
    </div>
  )
}

function Stat({ label, value, compact }) {
  return (
    <div>
      <div style={{ fontSize: compact ? 10 : 11, color: '#64748b' }}>{label}</div>
      <div style={{ fontSize: compact ? 14 : 20, fontWeight: 700, color: '#e2e8f0' }}>{value}</div>
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
