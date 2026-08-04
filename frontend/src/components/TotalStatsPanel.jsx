import React, { useEffect, useState, useCallback } from 'react'
import {
  ComposedChart, Bar, Line,
  XAxis, YAxis, CartesianGrid, Tooltip,
  ResponsiveContainer,
} from 'recharts'
import { api } from '../api/client.js'

// ── Helpers ────────────────────────────────────────────────────────────────
// (Deliberately self-contained rather than shared with StatsPanel.jsx — same
// pattern the rest of this codebase uses for per-panel components.)

function fmt$(n) {
  if (n == null) return null
  return '$' + n.toLocaleString('en-US', { minimumFractionDigits: 0, maximumFractionDigits: 0 })
}

function fmtGal(n) {
  if (n == null) return '—'
  return n.toLocaleString() + ' gal'
}

function shortDate(iso) {
  const d = new Date(iso + 'T12:00:00')  // noon avoids DST midnight edge cases
  return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric' })
}

// ── Sub-components ─────────────────────────────────────────────────────────

function Tile({ label, value, sub, accent, sub2 }) {
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
      {sub  && <div style={{ fontSize: 10, color: '#64748b', marginTop: 2 }}>{sub}</div>}
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
      background: '#1e2130', border: '1px solid #2d3348', borderRadius: 8,
      padding: '8px 12px', fontSize: 12, color: '#e2e8f0',
    }}>
      <div style={{ fontWeight: 700, marginBottom: 4 }}>{label}</div>
      {gal    && <div style={{ color: '#60a5fa' }}>{gal.value.toLocaleString()} gal (all tanks)</div>}
      {margin && margin.value != null
        ? <div style={{ color: '#22c55e' }}>{fmt$(margin.value)} margin</div>
        : <div style={{ color: '#64748b' }}>no price set</div>
      }
    </div>
  )
}

function DailyMarginChart({ data, window }) {
  if (!data || data.length === 0) return null
  const hasMargin = data.some(d => d.margin_dollars != null)

  return (
    <div style={{
      background: '#111827', border: '1px solid #2d3348', borderRadius: 10,
      padding: '14px 10px 8px', marginTop: 2,
    }}>
      <div style={{ fontSize: 11, color: '#64748b', marginBottom: 10, paddingLeft: 4 }}>
        Combined daily consumption &amp; margin — {window}
        {!hasMargin && (
          <span style={{ color: '#f59e0b', marginLeft: 8 }}>⚠ no price set</span>
        )}
      </div>
      <ResponsiveContainer width="100%" height={160}>
        <ComposedChart data={data} margin={{ top: 0, right: 10, left: -10, bottom: 0 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="#1f2937" vertical={false} />
          <XAxis
            dataKey="date"
            tickFormatter={shortDate}
            tick={{ fontSize: 10, fill: '#64748b' }}
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
            fill="#7c3aed"
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
// All-tanks combined view. Deliberately generic — iterates over whatever
// `summary.tanks` the API returns, so it works with any number of active
// tanks rather than assuming Unleaded/Super/Diesel specifically.

export default function TotalStatsPanel({ visible = true }) {
  const [summary, setSummary] = useState(null)
  const [error, setError] = useState(null)
  const [chartWindow, setChartWindow] = useState('7d')

  const load = useCallback(async () => {
    if (!visible) return
    try {
      const s = await api.statsSummary()
      setSummary(s)
      setError(null)
    } catch (e) {
      setError(e.message)
    }
  }, [visible])

  useEffect(() => { load() }, [load])

  if (!visible) return null

  const chartData = chartWindow === '7d'
    ? summary?.daily_breakdown_7d
    : summary?.daily_breakdown_30d

  const tankCount = summary?.tanks?.length ?? 0

  return (
    <div style={{
      background: '#1e2130', borderRadius: 12,
      padding: '18px 16px', border: '1.5px solid #2d3348',
    }}>
      <div style={{ fontWeight: 700, fontSize: 15, color: '#e2e8f0', marginBottom: 12 }}>
        All Tanks — Combined{tankCount > 0 ? ` (${tankCount} active)` : ''}
      </div>

      {error && <div style={{ color: '#ef4444', fontSize: 12 }}>Error: {error}</div>}

      {summary && (
        <>
          {/* ── Combined stat tiles ── */}
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 10 }}>

            <Tile
              label="Today"
              value={fmtGal(summary.today_consumed_gallons)}
              sub="consumed, all tanks"
              sub2={summary.today_profit_dollars != null ? fmt$(summary.today_profit_dollars) + ' profit (live)' : null}
              accent="#a78bfa"
            />

            <Tile
              label="Last 7 days"
              value={fmtGal(summary.week_consumed_gallons)}
              sub="consumed, all tanks"
              sub2={summary.total_margin_7d != null ? fmt$(summary.total_margin_7d) + ' margin' : null}
            />

            <Tile
              label="Avg / day (30d)"
              value={summary.avg_daily_gallons_30d != null ? `${summary.avg_daily_gallons_30d.toLocaleString()} gal` : '—'}
              sub="all tanks combined"
              sub2={summary.total_margin_30d != null ? fmt$(summary.total_margin_30d) + ' margin (30d)' : null}
            />

          </div>

          {/* ── Combined daily chart ── */}
          {chartData && (
            <div style={{ marginTop: 14 }}>
              <div style={{ display: 'flex', gap: 8, marginBottom: 8 }}>
                {['7d', '30d'].map(w => (
                  <button
                    key={w}
                    onClick={() => setChartWindow(w)}
                    style={{
                      fontSize: 11, padding: '3px 10px', borderRadius: 6, cursor: 'pointer',
                      border: '1px solid #2d3348',
                      background: chartWindow === w ? '#7c3aed' : '#111827',
                      color: chartWindow === w ? '#fff' : '#64748b',
                    }}
                  >
                    {w}
                  </button>
                ))}
              </div>
              <DailyMarginChart data={chartData} window={chartWindow} />
            </div>
          )}

          {/* ── Per-tank contribution breakdown ── */}
          {summary.tanks?.length > 0 && (
            <div style={{ marginTop: 14 }}>
              <div style={{ fontSize: 11, color: '#64748b', marginBottom: 8 }}>
                Per-tank contribution
              </div>
              <div style={{
                background: '#111827', border: '1px solid #2d3348', borderRadius: 10,
                overflow: 'hidden',
              }}>
                <div style={{
                  display: 'grid', gridTemplateColumns: '1.4fr 1fr 1fr 1fr',
                  fontSize: 10, color: '#64748b', textTransform: 'uppercase', letterSpacing: 0.3,
                  padding: '8px 12px', borderBottom: '1px solid #2d3348',
                }}>
                  <div>Tank</div>
                  <div>Today</div>
                  <div>Profit (live)</div>
                  <div>Margin 7d</div>
                </div>
                {summary.tanks.map(t => (
                  <div key={t.tank_id} style={{
                    display: 'grid', gridTemplateColumns: '1.4fr 1fr 1fr 1fr',
                    fontSize: 12, color: '#e2e8f0',
                    padding: '9px 12px', borderBottom: '1px solid #1a1e2b',
                  }}>
                    <div style={{ fontWeight: 600 }}>{t.name}</div>
                    <div>{fmtGal(t.today_consumed_gallons)}</div>
                    <div style={{ color: t.today_profit_dollars != null ? '#22c55e' : '#64748b' }}>
                      {t.today_profit_dollars != null ? fmt$(t.today_profit_dollars) : '—'}
                    </div>
                    <div style={{ color: t.total_margin_7d != null ? '#22c55e' : '#64748b' }}>
                      {t.total_margin_7d != null ? fmt$(t.total_margin_7d) : '—'}
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}
        </>
      )}
    </div>
  )
}
