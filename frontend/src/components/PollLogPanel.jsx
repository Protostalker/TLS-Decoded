import React, { useEffect, useState, useCallback } from 'react'
import { format } from 'date-fns'
import { api } from '../api/client.js'

const ROW_MAX_HEIGHT = 260

export default function PollLogPanel() {
  const [rows, setRows] = useState([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)

  const load = useCallback(async () => {
    setLoading(true); setError(null)
    try {
      setRows(await api.pollLog({ limit: 20 }))
    } catch (e) {
      setError(e.message)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { load() }, [load])

  const failCount = rows.filter(r => r.success === false).length

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 8 }}>
        <div style={{ fontSize: 12, fontWeight: 700, color: '#94a3b8', textTransform: 'uppercase', letterSpacing: 0.4 }}>
          Poll log {rows.length > 0 && failCount > 0 && (
            <span style={{ color: '#fca5a5', textTransform: 'none', fontWeight: 600 }}>
              — {failCount} of last {rows.length} failed
            </span>
          )}
        </div>
        <button onClick={load} title="Refresh" style={{
          background: '#2d3348', border: 'none', borderRadius: 6,
          color: '#94a3b8', fontSize: 11, padding: '4px 10px', cursor: 'pointer',
        }}>
          ⟳ Refresh
        </button>
      </div>

      {loading && rows.length === 0 && (
        <div style={{ textAlign: 'center', color: '#64748b', padding: 16, fontSize: 12 }}>Loading…</div>
      )}
      {error && <div style={{ color: '#ef4444', fontSize: 12, padding: 12 }}>Error: {error}</div>}
      {!loading && !error && rows.length === 0 && (
        <div style={{ textAlign: 'center', color: '#64748b', padding: 16, fontSize: 12 }}>No poll attempts logged yet</div>
      )}

      {rows.length > 0 && (
        <div style={{ maxHeight: ROW_MAX_HEIGHT, overflowY: 'auto' }}>
          {rows.map(r => (
            <div key={r.id} style={{
              display: 'flex', alignItems: 'flex-start', gap: 8,
              padding: '7px 4px', borderBottom: '1px solid #262b3d',
            }}>
              <div style={{
                width: 8, height: 8, borderRadius: '50%', marginTop: 4, flexShrink: 0,
                background: r.success ? '#22c55e' : '#ef4444',
                boxShadow: r.success ? '0 0 4px #22c55e88' : '0 0 4px #ef444488',
              }} />
              <div style={{ flex: 1, minWidth: 0 }}>
                <div style={{ display: 'flex', gap: 8, alignItems: 'baseline', flexWrap: 'wrap' }}>
                  <span style={{ fontSize: 12, color: '#cbd5e1' }}>
                    {format(new Date(r.polled_at), 'MMM d, HH:mm:ss')}
                  </span>
                  {r.duration_ms != null && (
                    <span style={{ fontSize: 10, color: '#475569' }}>{r.duration_ms}ms</span>
                  )}
                </div>
                {!r.success && r.error_message && (
                  <div style={{
                    fontSize: 11, color: '#fca5a5', marginTop: 2,
                    fontFamily: 'monospace', wordBreak: 'break-word',
                  }}>
                    {r.error_message}
                  </div>
                )}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
