import React, { useEffect, useState, useCallback } from 'react'
import { api } from '../api/client.js'

function Tile({ label, value, sub, accent }) {
  return (
    <div style={{
      background: '#111827', border: '1px solid #2d3348', borderRadius: 10,
      padding: '12px 14px', flex: '1 1 130px', minWidth: 130,
    }}>
      <div style={{ fontSize: 10, color: '#64748b', textTransform: 'uppercase', letterSpacing: 0.4, marginBottom: 4 }}>
        {label}
      </div>
      <div style={{ fontSize: 20, fontWeight: 800, color: accent || '#e2e8f0' }}>
        {value ?? '—'}
      </div>
      {sub && <div style={{ fontSize: 10, color: '#64748b', marginTop: 2 }}>{sub}</div>}
    </div>
  )
}

export default function StatsPanel({ tank }) {
  const [stats, setStats] = useState(null)
  const [error, setError] = useState(null)

  const load = useCallback(async () => {
    if (!tank) return
    try {
      const s = await api.stats(tank.id)
      setStats(s)
      setError(null)
    } catch (e) {
      setError(e.message)
    }
  }, [tank?.id])

  useEffect(() => { load() }, [load])

  if (!tank) return null

  return (
    <div style={{
      background: '#1e2130', borderRadius: 12,
      padding: '18px 16px', border: '1.5px solid #2d3348',
    }}>
      <div style={{ fontWeight: 700, fontSize: 15, color: '#e2e8f0', marginBottom: 12 }}>
        {tank.name} — Stats
      </div>

      {error && <div style={{ color: '#ef4444', fontSize: 12 }}>Error: {error}</div>}

      {stats && (
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 10 }}>
          <Tile label="Today" value={stats.today_consumed_gallons != null ? `${stats.today_consumed_gallons.toLocaleString()} gal` : '—'} sub="consumed" />
          <Tile label="Last 7 days" value={stats.week_consumed_gallons != null ? `${stats.week_consumed_gallons.toLocaleString()} gal` : '—'} sub="consumed" />
          <Tile label="Avg / day (30d)" value={stats.avg_daily_gallons_30d != null ? `${stats.avg_daily_gallons_30d.toLocaleString()} gal` : '—'} />
          <Tile
            label="Turnover"
            value={stats.turnover_days_estimate != null ? `${stats.turnover_days_estimate}d` : '—'}
            sub="days for a full tank to sell through at current rate"
          />
          <Tile
            label="Last delivery"
            value={stats.days_since_last_delivery != null ? `${stats.days_since_last_delivery}d ago` : 'none yet'}
            sub={stats.last_delivery_gallons != null ? `+${stats.last_delivery_gallons.toLocaleString()} gal` : null}
          />
          <Tile
            label="Temp range (7d)"
            value={stats.temp_min_7d != null ? `${stats.temp_min_7d}–${stats.temp_max_7d}°F` : '—'}
          />
          <Tile
            label="Water"
            value={stats.water_inches_latest != null ? `${stats.water_inches_latest}″` : '—'}
            accent={stats.water_alert ? '#ef4444' : undefined}
            sub={stats.water_alert ? '⚠ elevated — check tank' : 'normal'}
          />
        </div>
      )}
    </div>
  )
}
