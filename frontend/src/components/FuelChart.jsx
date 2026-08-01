import React, { useEffect, useState, useCallback } from 'react'
import {
  ComposedChart, Area, Line, XAxis, YAxis,
  CartesianGrid, Tooltip, ReferenceLine, ResponsiveContainer,
} from 'recharts'
import { api } from '../api/client.js'
import { format, subHours } from 'date-fns'

const RANGES = [
  { label: '24h', hours: 24 },
  { label: '7d',  hours: 168 },
  { label: '30d', hours: 720 },
]

function CustomTooltip({ active, payload, label }) {
  if (!active || !payload?.length) return null
  return (
    <div style={{
      background: '#1e2130', border: '1px solid #374151',
      borderRadius: 8, padding: '10px 14px', fontSize: 12,
    }}>
      <div style={{ color: '#94a3b8', marginBottom: 6 }}>{label}</div>
      {payload.map(p => (
        <div key={p.dataKey} style={{ color: p.color }}>
          {p.name}: {typeof p.value === 'number'
            ? p.value.toLocaleString(undefined, { maximumFractionDigits: 0 })
            : p.value} gal
        </div>
      ))}
    </div>
  )
}

export default function FuelChart({ tank }) {
  const [rangeIdx, setRangeIdx] = useState(1)
  const [data, setData] = useState([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)

  const range = RANGES[rangeIdx]

  const load = useCallback(async () => {
    if (!tank) return
    setLoading(true); setError(null)
    try {
      const from = subHours(new Date(), range.hours)
      const rows = await api.readings(tank.id, { from, limit: 500 })
      const sorted = [...rows].sort((a, b) => new Date(a.polled_at) - new Date(b.polled_at))
      setData(sorted.map(r => ({
        time: format(new Date(r.polled_at), 'MMM d HH:mm'),
        volume: r.volume_gallons != null ? Math.round(r.volume_gallons) : null,
      })))
    } catch (e) {
      setError(e.message)
    } finally {
      setLoading(false)
    }
  }, [tank?.id, range.hours])

  useEffect(() => { load() }, [load])

  if (!tank) return null

  const reorder = tank.reorder_threshold_gallons

  return (
    <div style={{
      background: '#1e2130', borderRadius: 12,
      padding: '20px 16px', border: '1.5px solid #2d3348',
    }}>
      <div style={{ display:'flex', justifyContent:'space-between', alignItems:'center', marginBottom:16 }}>
        <div style={{ fontWeight:700, fontSize:15, color:'#e2e8f0' }}>
          {tank.name} — Volume History
        </div>
        <div style={{ display:'flex', gap:6 }}>
          {RANGES.map((r, i) => (
            <button key={r.label} onClick={() => setRangeIdx(i)} style={{
              padding: '4px 12px', borderRadius: 6, cursor: 'pointer',
              border: 'none', fontSize: 12, fontWeight: 600,
              background: i === rangeIdx ? '#3b82f6' : '#2d3348',
              color: i === rangeIdx ? '#fff' : '#94a3b8',
            }}>
              {r.label}
            </button>
          ))}
        </div>
      </div>

      {loading && <div style={{ textAlign:'center', color:'#64748b', padding:40 }}>Loading…</div>}
      {error   && <div style={{ color:'#ef4444', fontSize:12, padding:16 }}>Error: {error}</div>}
      {!loading && !error && data.length === 0 && (
        <div style={{ textAlign:'center', color:'#64748b', padding:40 }}>No data for this period</div>
      )}

      {!loading && data.length > 0 && (
        <ResponsiveContainer width="100%" height={240}>
          <ComposedChart data={data} margin={{ top:4, right:10, left:0, bottom:4 }}>
            <defs>
              <linearGradient id="volGrad" x1="0" y1="0" x2="0" y2="1">
                <stop offset="5%"  stopColor="#3b82f6" stopOpacity={0.18} />
                <stop offset="95%" stopColor="#3b82f6" stopOpacity={0} />
              </linearGradient>
            </defs>
            <CartesianGrid strokeDasharray="3 3" stroke="#2d3348" />
            <XAxis dataKey="time" tick={{ fill:'#64748b', fontSize:10 }}
              tickLine={false} interval="preserveStartEnd" />
            <YAxis tick={{ fill:'#64748b', fontSize:10 }} tickLine={false}
              axisLine={false} tickFormatter={v => v.toLocaleString()} width={62} />
            <Tooltip content={<CustomTooltip />} />
            <Area type="monotone" dataKey="volume" stroke="none"
              fill="url(#volGrad)" name="Volume" />
            <Line type="monotone" dataKey="volume" stroke="#3b82f6"
              strokeWidth={2} dot={false} activeDot={{ r:4 }} name="Volume" />
            {reorder && (
              <ReferenceLine y={reorder} stroke="#ef4444" strokeDasharray="6 3"
                label={{ value:`Reorder (${reorder.toLocaleString()} gal)`,
                  fill:'#ef4444', fontSize:10, position:'insideTopRight' }} />
            )}
          </ComposedChart>
        </ResponsiveContainer>
      )}
    </div>
  )
}
