import React, { useEffect, useState, useCallback } from 'react'
import {
  ComposedChart, Bar, Line,
  XAxis, YAxis, CartesianGrid, Tooltip, Legend,
  ResponsiveContainer,
} from 'recharts'
import { api } from '../api/client.js'

// ── Helpers ────────────────────────────────────────────────────────────────

function fmt$(n) {
  if (n == null) return null
  return '$' + n.toLocaleString('en-US', { minimumFractionDigits: 0, maximumFractionDigits: 0 })
}

function fmtGal(n) {
  if (n == null) return '—'
  return n.toLocaleString() + ' gal'
}

function shortDate(iso) {
  // "2026-07-26" → "Jul 26"
  const d = new Date(iso + 'T12:00:00')  // noon avoids DST midnight edge cases
  return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric' })
}

// ── Sub-components ─────────────────────────────────────────────────────────

function Tile({ label, value, sub, accent, sub2 }) {
  return (
    <div style={{
      background: 'var(--brand-well, #111827)', border: '1px solid var(--brand-border, #2d3348)', borderRadius: 10,
      padding: '12px 14px', flex: '1 1 130px', minWidth: 130,
    }}>
      <div style={{ fontSize: 10, color: 'var(--brand-text-dimmer, #64748b)', textTransform: 'uppercase', letterSpacing: 0.4, marginBottom: 4 }}>
        {label}
      </div>
      <div style={{ fontSize: 20, fontWeight: 800, color: accent || 'var(--brand-text, #e2e8f0)' }}>
        {value ?? '—'}
      </div>
      {sub  && <div style={{ fontSize: 10, color: 'var(--brand-text-dimmer, #64748b)', marginTop: 2 }}>{sub}</div>}
      {sub2 && <div style={{ fontSize: 10, color: '#22c55e', marginTop: 1 }}>{sub2}</div>}
    </div>
  )
}

const CustomTooltip = ({ active, payload, label }) => {
  if (!active || !payload?.length) return null
  const gal    = payload.find(p => p.dataKey === 'gallons')
  const margin = payload.find(p => p.dataKey === 'margin_dollars')
  return (
    <div style={{
      background: 'var(--brand-surface, #1e2130)', border: '1px solid var(--brand-border, #2d3348)', borderRadius: 8,
      padding: '8px 12px', fontSize: 12, color: 'var(--brand-text, #e2e8f0)',
    }}>
      <div style={{ fontWeight: 700, marginBottom: 4 }}>{label}</div>
      {gal    && <div style={{ color: '#60a5fa' }}>{gal.value.toLocaleString()} gal consumed</div>}
      {margin && margin.value != null
        ? <div style={{ color: '#22c55e' }}>{fmt$(margin.value)} margin</div>
        : <div style={{ color: 'var(--brand-text-dimmer, #64748b)' }}>no price set</div>
      }
    </div>
  )
}

function DailyMarginChart({ data, window }) {
  if (!data || data.length === 0) return null
  const hasMargin = data.some(d => d.margin_dollars != null)

  return (
    <div style={{
      background: 'var(--brand-well, #111827)', border: '1px solid var(--brand-border, #2d3348)', borderRadius: 10,
      padding: '14px 10px 8px', marginTop: 2,
    }}>
      <div style={{ fontSize: 11, color: 'var(--brand-text-dimmer, #64748b)', marginBottom: 10, paddingLeft: 4 }}>
        Daily consumption &amp; margin — {window}
        {!hasMargin && (
          <span style={{ color: '#f59e0b', marginLeft: 8 }}>⚠ no price set</span>
        )}
      </div>
      <ResponsiveContainer width="100%" height={160}>
        <ComposedChart data={data} margin={{ top: 0, right: 10, left: -10, bottom: 0 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="var(--brand-border-soft, #1f2937)" vertical={false} />
          <XAxis
            dataKey="date"
            tickFormatter={shortDate}
            tick={{ fontSize: 10, fill: 'var(--brand-text-dimmer, #64748b)' }}
            axisLine={false}
            tickLine={false}
          />
          <YAxis
            yAxisId="gal"
            orientation="left"
            tick={{ fontSize: 10, fill: '#60a5fa' }}
            axisLine={false}
            tickLine={false}
            tickFormatter={v => v >= 1000 ? (v / 1000).toFixed(1) + 'k' : v}
          />
          {hasMargin && (
            <YAxis
              yAxisId="margin"
              orientation="right"
              tick={{ fontSize: 10, fill: '#22c55e' }}
              axisLine={false}
              tickLine={false}
              tickFormatter={v => '$' + (v >= 1000 ? (v / 1000).toFixed(1) + 'k' : v)}
            />
          )}
          <Tooltip content={<CustomTooltip />} />
          <Bar
            yAxisId="gal"
            dataKey="gallons"
            fill="#1d4ed8"
            radius={[3, 3, 0, 0]}
            maxBarSize={28}
            name="Gallons"
          />
          {hasMargin && (
            <Line
              yAxisId="margin"
              type="monotone"
              dataKey="margin_dollars"
              stroke="#22c55e"
              strokeWidth={2}
              dot={{ r: 3, fill: '#22c55e', strokeWidth: 0 }}
              connectNulls={false}
              name="Margin $"
            />
          )}
        </ComposedChart>
      </ResponsiveContainer>
    </div>
  )
}

// ── Main component ─────────────────────────────────────────────────────────

export default function StatsPanel({ tank }) {
  const [stats, setStats] = useState(null)
  const [error, setError] = useState(null)
  const [chartWindow, setChartWindow] = useState('7d')

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

  const chartData = chartWindow === '7d'
    ? stats?.daily_breakdown_7d
    : stats?.daily_breakdown_30d

  return (
    <div style={{
      background: 'var(--brand-surface, #1e2130)', borderRadius: 12,
      padding: '18px 16px', border: '1.5px solid var(--brand-border, #2d3348)',
    }}>
      <div style={{ fontWeight: 700, fontSize: 15, color: 'var(--brand-text, #e2e8f0)', marginBottom: 12 }}>
        {tank.name} — Stats
      </div>

      {error && <div style={{ color: '#ef4444', fontSize: 12 }}>Error: {error}</div>}

      {stats && (
        <>
          {/* ── Stat tiles ── */}
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 10 }}>

            <Tile
              label="Today"
              value={fmtGal(stats.today_consumed_gallons)}
              sub="consumed"
            />

            <Tile
              label="Last 7 days"
              value={fmtGal(stats.week_consumed_gallons)}
              sub="consumed"
              sub2={stats.total_margin_7d != null ? fmt$(stats.total_margin_7d) + ' margin' : null}
            />

            <Tile
              label="Avg / day (30d)"
              value={stats.avg_daily_gallons_30d != null ? `${stats.avg_daily_gallons_30d.toLocaleString()} gal` : '—'}
              sub2={stats.total_margin_30d != null ? fmt$(stats.total_margin_30d) + ' margin (30d)' : null}
            />

            <Tile
              label="Turnover"
              value={stats.turnover_days_estimate != null ? `${stats.turnover_days_estimate}d` : '—'}
              sub="days for a full tank at current rate"
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

          {/* ── Daily chart ── */}
          {chartData && (
            <div style={{ marginTop: 14 }}>
              <div style={{ display: 'flex', gap: 8, marginBottom: 8 }}>
                {['7d', '30d'].map(w => (
                  <button
                    key={w}
                    onClick={() => setChartWindow(w)}
                    style={{
                      fontSize: 11, padding: '3px 10px', borderRadius: 6, cursor: 'pointer',
                      border: '1px solid var(--brand-border, #2d3348)',
                      background: chartWindow === w ? '#1d4ed8' : 'var(--brand-well, #111827)',
                      color: chartWindow === w ? '#fff' : 'var(--brand-text-dimmer, #64748b)',
                    }}
                  >
                    {w}
                  </button>
                ))}
              </div>
              <DailyMarginChart data={chartData} window={chartWindow} />
            </div>
          )}
        </>
      )}
    </div>
  )
}
