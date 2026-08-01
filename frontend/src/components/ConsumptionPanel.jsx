import React, { useEffect, useState, useCallback } from 'react'
import { format } from 'date-fns'
import { api } from '../api/client.js'

const ROW_H = 34
const VISIBLE_ROWS = 5

export default function ConsumptionPanel({ tank }) {
  const [rows, setRows] = useState([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)

  const load = useCallback(async () => {
    if (!tank) return
    setLoading(true); setError(null)
    try {
      const data = await api.consumption(tank.id, { limit: 15 })
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
          {tank.name} — Consumption per Poll
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
        <div style={{ textAlign: 'center', color: '#64748b', padding: 24, fontSize: 12 }}>
          Not enough readings yet — check back after a couple of polls
        </div>
      )}

      {rows.length > 0 && (
        <div>
          <div style={{
            display: 'grid',
            gridTemplateColumns: '1.5fr 1fr 1fr',
            fontSize: 10, color: '#64748b', textTransform: 'uppercase',
            letterSpacing: 0.4, padding: '0 8px 6px', borderBottom: '1px solid #2d3348',
          }}>
            <span>Interval end</span>
            <span>Gallons</span>
            <span>Rate</span>
          </div>

          <div style={{
            maxHeight: ROW_H * VISIBLE_ROWS,
            overflowY: rows.length > VISIBLE_ROWS ? 'auto' : 'visible',
          }}>
            {rows.map((r, i) => (
              <div key={r.to_time + i} style={{
                display: 'grid',
                gridTemplateColumns: '1.5fr 1fr 1fr',
                fontSize: 12, padding: '8px 8px',
                height: ROW_H - 8, alignItems: 'center',
                borderBottom: i === rows.length - 1 ? 'none' : '1px solid #262b3d',
              }}>
                <span style={{ color: '#94a3b8' }}>{format(new Date(r.to_time), 'MMM d HH:mm')}</span>
                {r.is_increase ? (
                  <span style={{ color: '#86efac' }}>+{Math.abs(r.delta_gallons).toFixed(0)} gal ⛽</span>
                ) : (
                  <span style={{ color: '#e2e8f0' }}>-{r.delta_gallons.toFixed(0)} gal</span>
                )}
                <span style={{ color: '#64748b' }}>
                  {r.rate_gal_per_hour != null ? `${r.rate_gal_per_hour.toFixed(1)} gal/hr` : '—'}
                </span>
              </div>
            ))}
          </div>

          <div style={{ fontSize: 10, color: '#475569', marginTop: 8, textAlign: 'right' }}>
            Showing {Math.min(VISIBLE_ROWS, rows.length)} of {rows.length} loaded (scroll for more) · ⛽ = volume rose (delivery)
          </div>
        </div>
      )}
    </div>
  )
}
