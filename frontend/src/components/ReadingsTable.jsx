import React, { useEffect, useState, useCallback } from 'react'
import { format } from 'date-fns'
import { api } from '../api/client.js'

const ROW_H = 34
const VISIBLE_ROWS = 5
const FETCH_LIMIT = 15

function fmt(n, digits = 0) {
  return n == null ? '—' : n.toLocaleString(undefined, { maximumFractionDigits: digits })
}

export default function ReadingsTable({ tank }) {
  const [rows, setRows] = useState([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)

  const load = useCallback(async () => {
    if (!tank) return
    setLoading(true); setError(null)
    try {
      const data = await api.readings(tank.id, { limit: FETCH_LIMIT })
      // API returns newest-first already; keep as-is (most recent on top).
      setRows(data)
    } catch (e) {
      setError(e.message)
    } finally {
      setLoading(false)
    }
  }, [tank?.id])

  useEffect(() => { load() }, [load])

  if (!tank) return null

  return (
    <div style={{
      background: '#1e2130', borderRadius: 12,
      padding: '18px 16px', border: '1.5px solid #2d3348',
    }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 10 }}>
        <div style={{ fontWeight: 700, fontSize: 15, color: '#e2e8f0' }}>
          {tank.name} — Recent Readings
        </div>
        <button onClick={load} title="Refresh" style={{
          background: '#2d3348', border: 'none', borderRadius: 6,
          color: '#94a3b8', fontSize: 11, padding: '4px 10px', cursor: 'pointer',
        }}>
          ⟳ Refresh
        </button>
      </div>

      {loading && rows.length === 0 && (
        <div style={{ textAlign: 'center', color: '#64748b', padding: 24, fontSize: 12 }}>Loading…</div>
      )}
      {error && <div style={{ color: '#ef4444', fontSize: 12, padding: 12 }}>Error: {error}</div>}
      {!loading && !error && rows.length === 0 && (
        <div style={{ textAlign: 'center', color: '#64748b', padding: 24, fontSize: 12 }}>No readings yet</div>
      )}

      {rows.length > 0 && (
        <div>
          <div style={{
            display: 'grid',
            gridTemplateColumns: '1.3fr 1fr 1fr 0.8fr 0.8fr 0.8fr',
            fontSize: 10, color: '#64748b', textTransform: 'uppercase',
            letterSpacing: 0.4, padding: '0 8px 6px', borderBottom: '1px solid #2d3348',
          }}>
            <span>Time</span>
            <span>Volume</span>
            <span>Ullage</span>
            <span>Height</span>
            <span>Water</span>
            <span>Temp</span>
          </div>

          <div style={{
            maxHeight: ROW_H * VISIBLE_ROWS,
            overflowY: rows.length > VISIBLE_ROWS ? 'auto' : 'visible',
          }}>
            {rows.map((r, i) => (
              <div key={r.id} style={{
                display: 'grid',
                gridTemplateColumns: '1.3fr 1fr 1fr 0.8fr 0.8fr 0.8fr',
                fontSize: 12, color: '#cbd5e1', padding: '8px 8px',
                height: ROW_H - 8, alignItems: 'center',
                borderBottom: i === rows.length - 1 ? 'none' : '1px solid #262b3d',
              }}>
                <span style={{ color: '#94a3b8' }}>{format(new Date(r.polled_at), 'MMM d HH:mm')}</span>
                <span>{fmt(r.volume_gallons)} gal</span>
                <span>{fmt(r.ullage_gallons)} gal</span>
                <span>{r.height_inches != null ? `${r.height_inches.toFixed(2)}″` : '—'}</span>
                <span>{r.water_inches != null ? `${r.water_inches.toFixed(2)}″` : '—'}</span>
                <span>{r.temperature_f != null ? `${r.temperature_f.toFixed(1)}°F` : '—'}</span>
              </div>
            ))}
          </div>

          <div style={{ fontSize: 10, color: '#475569', marginTop: 8, textAlign: 'right' }}>
            Showing {Math.min(VISIBLE_ROWS, rows.length)} of {rows.length} loaded (scroll for more)
          </div>
        </div>
      )}
    </div>
  )
}
