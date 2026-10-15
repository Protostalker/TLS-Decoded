import React, { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react'
import { api } from '../api/client.js'

// Cloud T1 only: every active tank on one graph, actual gallons up to the
// latest synced reading, then a dashed predicted line built from each
// tank's own hour-of-day selling pattern (see cloud-api/forecast.py).
// Hover (or touch-drag) shows a table of every tank's gallons at that hour.

const RANGES = [
  { key: '24h', label: '24 hours', predict: '8h' },
  { key: '48h', label: '48 hours', predict: '12h' },
  { key: '72h', label: '72 hours', predict: '18h' },
  { key: '5d', label: '5 days', predict: '24h' },
  { key: '7d', label: '7 days', predict: '36h' },
]
const RANGE_STORAGE_KEY = 'tls_cloud_forecast_range'
const REFRESH_MS = 5 * 60_000

// Fixed categorical order, picked to stay distinct on the dark surfaces.
const TANK_COLORS = ['#60a5fa', '#f59e0b', '#34d399', '#f472b6', '#a78bfa', '#22d3ee', '#f87171', '#a3e635']

const HEIGHT = 300
const PAD = { top: 16, right: 64, bottom: 30, left: 12 }

function readStoredRange() {
  try {
    const v = localStorage.getItem(RANGE_STORAGE_KEY)
    return RANGES.some(r => r.key === v) ? v : '24h'
  } catch { return '24h' }
}

export default function ForecastChart({ stationId }) {
  const [range, setRange] = useState(readStoredRange)
  const [data, setData] = useState(null)
  const [error, setError] = useState(null)
  const [loading, setLoading] = useState(true)
  const [hoverIdx, setHoverIdx] = useState(null)
  const wrapRef = useRef(null)
  const [width, setWidth] = useState(800)

  const load = useCallback(async () => {
    try {
      const d = await api.stationForecast(stationId, range)
      setData(d)
      setError(null)
    } catch (e) {
      setError(e.message)
    } finally {
      setLoading(false)
    }
  }, [stationId, range])

  useEffect(() => {
    setLoading(true)
    setHoverIdx(null)
    load()
    const t = setInterval(load, REFRESH_MS)
    return () => clearInterval(t)
  }, [load])

  useLayoutEffect(() => {
    if (!wrapRef.current) return
    const el = wrapRef.current
    const ro = new ResizeObserver(entries => {
      const w = Math.floor(entries[0].contentRect.width)
      if (w > 0) setWidth(w)
    })
    ro.observe(el)
    return () => ro.disconnect()
  }, [])

  const changeRange = (key) => {
    setRange(key)
    try { localStorage.setItem(RANGE_STORAGE_KEY, key) } catch { /* ignore */ }
  }

  const tz = data?.timezone
  const fmt = useMemo(() => makeFormatters(tz), [tz])

  const chart = useMemo(() => {
    if (!data || !data.times?.length) return null
    const times = data.times.map(t => Date.parse(t))
    const t0 = times[0], t1 = times[times.length - 1]
    const nowMs = Date.parse(data.now)
    const plotW = Math.max(10, width - PAD.left - PAD.right)
    const plotH = HEIGHT - PAD.top - PAD.bottom
    const x = t => PAD.left + ((t - t0) / (t1 - t0)) * plotW

    let yMax = 0
    for (const tank of data.tanks) {
      if (tank.capacity_gallons) yMax = Math.max(yMax, tank.capacity_gallons)
      for (const v of tank.values) if (v != null) yMax = Math.max(yMax, v)
    }
    yMax = niceCeil(yMax || 1000)
    const y = v => PAD.top + plotH - (v / yMax) * plotH
    const yTicks = [0, 0.25, 0.5, 0.75, 1].map(f => Math.round(yMax * f))

    const tanks = data.tanks.map((tank, i) => {
      const color = TANK_COLORS[i % TANK_COLORS.length]
      const lastT = tank.last_reading_at ? Date.parse(tank.last_reading_at) : null
      const actual = []   // array of runs (null values break the line)
      let run = []
      const predPts = []
      tank.values.forEach((v, j) => {
        if (tank.predicted[j]) return
        if (v == null) { if (run.length) actual.push(run); run = []; return }
        run.push([x(times[j]), y(v)])
      })
      // Close the actual line at the exact latest reading, then start the
      // predicted line from that same point so the two join cleanly.
      if (lastT != null && lastT >= t0 && lastT <= t1 && tank.last_volume_gallons != null) {
        run.push([x(lastT), y(tank.last_volume_gallons)])
      }
      if (run.length) actual.push(run)
      if (tank.predicted.some(Boolean) && lastT != null && tank.last_volume_gallons != null) {
        predPts.push([x(Math.max(lastT, t0)), y(tank.last_volume_gallons)])
        tank.values.forEach((v, j) => { if (tank.predicted[j] && v != null) predPts.push([x(times[j]), y(v)]) })
      }
      return { ...tank, color, actual, predPts }
    })

    return { times, t0, t1, nowMs, x, y, yMax, yTicks, plotW, plotH, tanks, xTicks: makeXTicks(times, plotW, fmt) }
  }, [data, width, fmt])

  const onPointer = (e) => {
    if (!chart) return
    const rect = e.currentTarget.getBoundingClientRect()
    const px = e.clientX - rect.left
    const t = chart.t0 + ((px - PAD.left) / chart.plotW) * (chart.t1 - chart.t0)
    let best = 0, bestD = Infinity
    chart.times.forEach((tt, i) => { const d = Math.abs(tt - t); if (d < bestD) { bestD = d; best = i } })
    setHoverIdx(best)
  }

  const current = RANGES.find(r => r.key === range)

  return (
    <div style={panel}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-end', flexWrap: 'wrap', gap: 12, marginBottom: 12 }}>
        <label style={selectBox}>
          <span style={{ fontSize: 9, letterSpacing: 0.6, textTransform: 'uppercase', color: 'var(--brand-text-dimmer, #64748b)' }}>Graph range</span>
          <select value={range} onChange={e => changeRange(e.target.value)} style={selectEl}>
            {RANGES.map(r => <option key={r.key} value={r.key} style={{ background: '#1e2130', color: '#e2e8f0' }}>{r.label} ({r.predict} predicted)</option>)}
          </select>
        </label>
        <div style={{ display: 'flex', gap: 14, flexWrap: 'wrap', fontSize: 11, color: 'var(--brand-text-dim, #94a3b8)' }}>
          <LegendKey dashed={false} label="Actual" />
          <LegendKey dashed label={`Predicted (next ${current?.predict})`} />
          <span style={{ color: 'var(--brand-text-faint, #475569)' }}>Gallons</span>
        </div>
      </div>

      <div ref={wrapRef} style={{ position: 'relative', width: '100%' }}>
        {loading && !data && <Empty text="Loading forecast…" />}
        {error && !data && <Empty text={`Forecast unavailable: ${error}`} />}
        {data && data.tanks.length === 0 && <Empty text="No active tanks on this station" />}

        {chart && data.tanks.length > 0 && (
          <>
            <svg
              width={width} height={HEIGHT} style={{ display: 'block', touchAction: 'pan-y' }}
              onPointerMove={onPointer} onPointerDown={onPointer} onPointerLeave={() => setHoverIdx(null)}
            >
              {/* Forecast region */}
              {chart.nowMs < chart.t1 && (
                <rect
                  x={chart.x(Math.max(chart.nowMs, chart.t0))} y={PAD.top}
                  width={chart.x(chart.t1) - chart.x(Math.max(chart.nowMs, chart.t0))} height={chart.plotH}
                  fill="var(--brand-text, #e2e8f0)" opacity={0.04}
                />
              )}

              {/* Gridlines + right-side Y axis */}
              {chart.yTicks.map(v => (
                <g key={v}>
                  <line x1={PAD.left} x2={PAD.left + chart.plotW} y1={chart.y(v)} y2={chart.y(v)}
                        stroke="var(--brand-border-soft, #1e2130)" strokeWidth={1} />
                  <text x={PAD.left + chart.plotW + 8} y={chart.y(v) + 4} fontSize={11}
                        fill="var(--brand-text-dimmer, #64748b)" style={{ fontVariantNumeric: 'tabular-nums' }}>
                    {v.toLocaleString()}
                  </text>
                </g>
              ))}

              {/* X labels */}
              {chart.xTicks.filter(tk => chart.x(tk.t) > PAD.left + 22 && chart.x(tk.t) < PAD.left + chart.plotW - 22).map(tk => (
                <text key={tk.t} x={chart.x(tk.t)} y={HEIGHT - 8} fontSize={11} textAnchor="middle"
                      fill="var(--brand-text-dimmer, #64748b)">{tk.label}</text>
              ))}

              {/* Now marker */}
              {chart.nowMs >= chart.t0 && chart.nowMs <= chart.t1 && (
                <g>
                  <line x1={chart.x(chart.nowMs)} x2={chart.x(chart.nowMs)} y1={PAD.top} y2={PAD.top + chart.plotH}
                        stroke="var(--brand-text-dim, #94a3b8)" strokeWidth={1} strokeDasharray="2 3" />
                  <text x={chart.x(chart.nowMs) + 4} y={PAD.top + 10} fontSize={10} fill="var(--brand-text-dim, #94a3b8)">Now</text>
                </g>
              )}

              {/* Lines */}
              {chart.tanks.map(tank => (
                <g key={tank.tank_local_id}>
                  {tank.actual.map((pts, k) => (
                    <polyline key={k} points={pts.map(p => p.join(',')).join(' ')} fill="none"
                              stroke={tank.color} strokeWidth={2} strokeLinejoin="round" strokeLinecap="round" />
                  ))}
                  {tank.predPts.length > 1 && (
                    <polyline points={tank.predPts.map(p => p.join(',')).join(' ')} fill="none"
                              stroke={tank.color} strokeWidth={2} strokeDasharray="6 4" strokeLinejoin="round" opacity={0.85} />
                  )}
                </g>
              ))}

              {/* Hover crosshair */}
              {hoverIdx != null && (
                <g pointerEvents="none">
                  <line x1={chart.x(chart.times[hoverIdx])} x2={chart.x(chart.times[hoverIdx])}
                        y1={PAD.top} y2={PAD.top + chart.plotH} stroke="var(--brand-text, #e2e8f0)" strokeWidth={1} opacity={0.6} />
                  {chart.tanks.map(tank => {
                    const v = tank.values[hoverIdx]
                    if (v == null) return null
                    return <circle key={tank.tank_local_id} cx={chart.x(chart.times[hoverIdx])} cy={chart.y(v)} r={4}
                                   fill={tank.color} stroke="var(--brand-surface-2, #161b27)" strokeWidth={2} />
                  })}
                </g>
              )}
            </svg>

            {hoverIdx != null && (
              <HoverTable chart={chart} idx={hoverIdx} width={width} fmt={fmt} />
            )}
          </>
        )}
      </div>

      {chart && data.tanks.length > 0 && (
        <TankSummary tanks={chart.tanks} fmt={fmt} />
      )}

      <div style={{ fontSize: 10, color: 'var(--brand-text-faint, #475569)', marginTop: 10 }}>
        Prediction uses each tank's selling pattern by hour of day over the last 4 weeks, starting from its latest
        synced reading. It assumes no delivery arrives. Times shown in station time.
      </div>
    </div>
  )
}

// Tooltip table, modeled on the reference: time header, one colored row per
// tank (gallons + % full), total row.
function HoverTable({ chart, idx, width, fmt }) {
  const t = chart.times[idx]
  const px = chart.x(t)
  const isPredicted = chart.tanks.some(tk => tk.predicted[idx])
  const rows = chart.tanks.map(tk => ({
    id: tk.tank_local_id, name: tk.name, color: tk.color, value: tk.values[idx],
    pct: tk.values[idx] != null && tk.capacity_gallons ? Math.round((tk.values[idx] / tk.capacity_gallons) * 100) : null,
    predicted: tk.predicted[idx],
  }))
  const known = rows.filter(r => r.value != null)
  const total = known.length ? known.reduce((s, r) => s + r.value, 0) : null

  const boxW = 260
  const placeRight = px + 16 + boxW < width
  const left = placeRight ? px + 16 : Math.max(0, px - 16 - boxW)

  return (
    <div style={{
      position: 'absolute', top: PAD.top + 8, left, width: boxW, pointerEvents: 'none',
      background: '#05070bf0', border: '1px solid var(--brand-border, #2d3348)', borderRadius: 8,
      overflow: 'hidden', boxShadow: '0 8px 24px #0008', fontSize: 12,
    }}>
      <div style={{ padding: '8px 12px', textAlign: 'center', fontWeight: 700, color: '#f1f5f9' }}>
        {fmt.full(t)}
        {isPredicted && (
          <span style={{ marginLeft: 8, fontSize: 9, fontWeight: 700, letterSpacing: 0.5, textTransform: 'uppercase',
                         padding: '2px 6px', borderRadius: 4, background: '#334155', color: '#cbd5e1' }}>Predicted</span>
        )}
      </div>
      {rows.map(r => (
        <div key={r.id} style={{
          display: 'flex', alignItems: 'center', gap: 8, padding: '7px 12px',
          background: `linear-gradient(90deg, ${r.color}55, ${r.color}22)`, borderLeft: `3px solid ${r.color}`,
          color: '#f8fafc', marginBottom: 1,
        }}>
          <span style={{ flex: 1, fontWeight: 600, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>{r.name}</span>
          <span style={{ fontWeight: 700, fontVariantNumeric: 'tabular-nums' }}>
            {r.value != null ? `${Math.round(r.value).toLocaleString()} gal` : '—'}
          </span>
          <span style={{ width: 40, textAlign: 'right', fontSize: 10, color: '#cbd5e1', fontVariantNumeric: 'tabular-nums' }}>
            {r.pct != null ? `${r.pct}%` : ''}
          </span>
        </div>
      ))}
      <div style={{ display: 'flex', padding: '8px 12px', color: '#f1f5f9', fontWeight: 700 }}>
        <span style={{ flex: 1, color: '#94a3b8', fontWeight: 600 }}>Total</span>
        <span style={{ fontVariantNumeric: 'tabular-nums' }}>{total != null ? `${Math.round(total).toLocaleString()} gal` : '—'}</span>
        <span style={{ width: 40 }} />
      </div>
    </div>
  )
}

// Per-tank "when does it hit reorder / run dry" chips. This is the bit a
// supplier acts on, so it's always visible, not just on hover.
function TankSummary({ tanks, fmt }) {
  return (
    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))', gap: 8, marginTop: 12 }}>
      {tanks.map(tk => (
        <div key={tk.tank_local_id} style={{
          borderLeft: `3px solid ${tk.color}`, background: 'var(--brand-surface, #1e2130)', borderRadius: 6,
          padding: '8px 10px', fontSize: 11,
        }}>
          <div style={{ fontWeight: 700, color: 'var(--brand-text, #e2e8f0)', marginBottom: 4 }}>{tk.name}</div>
          {tk.note ? (
            <div style={{ color: 'var(--brand-text-dimmer, #64748b)' }}>{tk.note}</div>
          ) : (
            <>
              <SummaryRow label="Reorder level" value={
                !tk.reorder_threshold_gallons ? 'Not set'
                  : tk.projected_reorder_at ? fmt.full(Date.parse(tk.projected_reorder_at))
                  : (tk.last_volume_gallons != null && tk.last_volume_gallons <= tk.reorder_threshold_gallons ? 'Already below' : 'Over 60 days')
              } warn={tk.last_volume_gallons != null && tk.reorder_threshold_gallons && tk.last_volume_gallons <= tk.reorder_threshold_gallons} />
              <SummaryRow label="Runs empty" value={tk.projected_empty_at ? fmt.full(Date.parse(tk.projected_empty_at)) : 'Over 60 days'} />
            </>
          )}
        </div>
      ))}
    </div>
  )
}

function SummaryRow({ label, value, warn }) {
  return (
    <div style={{ display: 'flex', justifyContent: 'space-between', gap: 8 }}>
      <span style={{ color: 'var(--brand-text-dimmer, #64748b)' }}>{label}</span>
      <span style={{ color: warn ? '#fca5a5' : 'var(--brand-text, #e2e8f0)', fontWeight: 600 }}>{value}</span>
    </div>
  )
}

function LegendKey({ dashed, label }) {
  return (
    <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}>
      <svg width={22} height={6}><line x1={0} x2={22} y1={3} y2={3} stroke="currentColor" strokeWidth={2} strokeDasharray={dashed ? '6 4' : undefined} /></svg>
      {label}
    </span>
  )
}

function Empty({ text }) {
  return <div style={{ height: HEIGHT, display: 'flex', alignItems: 'center', justifyContent: 'center', color: 'var(--brand-text-faint, #475569)', fontSize: 12 }}>{text}</div>
}

// ── helpers ──────────────────────────────────────────────────────────────

function niceCeil(v) {
  const mag = 10 ** Math.floor(Math.log10(v))
  for (const m of [1, 1.2, 1.5, 2, 2.5, 3, 4, 5, 6, 8, 10]) if (m * mag >= v) return m * mag
  return 10 * mag
}

function makeFormatters(tz) {
  const opts = tz ? { timeZone: tz } : {}
  const hour = new Intl.DateTimeFormat(undefined, { ...opts, hour: 'numeric', minute: '2-digit' })
  const day = new Intl.DateTimeFormat(undefined, { ...opts, weekday: 'short', month: 'numeric', day: 'numeric' })
  const full = new Intl.DateTimeFormat(undefined, { ...opts, weekday: 'short', month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' })
  const parts = new Intl.DateTimeFormat('en-US', { ...opts, hour: 'numeric', hourCycle: 'h23' })
  return {
    hour: t => hour.format(t),
    day: t => day.format(t),
    full: t => full.format(t),
    localHour: t => Number(parts.formatToParts(t).find(p => p.type === 'hour')?.value ?? 0) % 24,
  }
}

// Label spacing picked from the hours covered and the pixel width, so
// labels never collide at phone width.
function makeXTicks(times, plotW, fmt) {
  const spanH = (times[times.length - 1] - times[0]) / 3_600_000
  const maxLabels = Math.max(2, Math.floor(plotW / 80))
  const every = [1, 2, 3, 4, 6, 12, 24, 48].find(h => spanH / h <= maxLabels) ?? 48
  const out = []
  for (const t of times) {
    const h = fmt.localHour(t)
    if (every > 24 ? (h !== 0 || Math.round((t - times[0]) / 86_400_000) % (every / 24) !== 0) : h % every !== 0) continue
    out.push({ t, label: every >= 24 || h === 0 ? fmt.day(t) : fmt.hour(t) })
  }
  return out
}

const panel = {
  background: 'var(--brand-surface-2, #161b27)', border: '1px solid var(--brand-border-soft, #1e2130)',
  borderRadius: 14, padding: 16, marginBottom: 16,
}
const selectBox = {
  display: 'flex', flexDirection: 'column', gap: 2, padding: '6px 10px', borderRadius: 6,
  background: 'var(--brand-surface, #1e2130)', border: '1px solid var(--brand-border, #2d3348)', minWidth: 200,
}
const selectEl = {
  background: 'transparent', color: 'var(--brand-text, #e2e8f0)', border: 'none', outline: 'none',
  fontSize: 14, fontWeight: 700, padding: 0, cursor: 'pointer',
}
