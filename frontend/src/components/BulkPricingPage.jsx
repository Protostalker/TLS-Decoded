import React, { useEffect, useState, useCallback, useMemo } from 'react'
import { api } from '../api/client.js'

const btn = {
  padding: '7px 14px', borderRadius: 6, cursor: 'pointer', fontSize: 12, fontWeight: 600,
  border: '1px solid var(--brand-border-soft, #374151)', background: 'transparent', color: 'var(--brand-text, #cbd5e1)',
}
const cellInput = {
  background: 'var(--brand-surface-2, #0b0f19)', border: '1px solid var(--brand-border-soft, #374151)', borderRadius: 5,
  color: 'var(--brand-text, #e2e8f0)', fontSize: 12, padding: '5px 6px', width: 78, boxSizing: 'border-box',
}
const th = {
  fontSize: 10, textTransform: 'uppercase', letterSpacing: 0.4, color: 'var(--brand-text-dimmer, #64748b)',
  padding: '6px 8px', textAlign: 'left', position: 'sticky', top: 0, background: 'var(--brand-surface, #1e2130)',
}

function dayLabel(iso) {
  const [y, m, d] = iso.split('-').map(Number)
  return new Date(y, m - 1, d).toLocaleDateString(undefined, { weekday: 'short', month: 'short', day: 'numeric' })
}

// Day-by-day catch-up entry for the current month. One cost + one sale price
// per product per day (both effective 6:00 AM). Blank cells change nothing —
// the previous day's price simply continues — so only type where it changed.
export default function BulkPricingPage({ onClose }) {
  const [data, setData] = useState(null)
  const [edits, setEdits] = useState({})      // `${tankId}|${date}|cost|sale` -> string
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [msg, setMsg] = useState(null)

  const load = useCallback(async () => {
    setLoading(true)
    try {
      setData(await api.bulkPricesMonth())
      setMsg(null)
    } catch (e) {
      setMsg({ type: 'error', text: e.message })
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { load() }, [load])

  const key = (tankId, day, f) => `${tankId}|${day}|${f}`
  const setEdit = (tankId, day, f, v) => setEdits(e => ({ ...e, [key(tankId, day, f)]: v }))

  const pending = useMemo(() => {
    const byCell = {}
    for (const [k, v] of Object.entries(edits)) {
      if (v === '' || v == null) continue
      const [tankId, day, f] = k.split('|')
      const ck = `${tankId}|${day}`
      byCell[ck] = byCell[ck] || { tank_id: Number(tankId), date: day }
      byCell[ck][f === 'cost' ? 'cost_per_gallon' : 'sale_price_per_gallon'] = Number(v)
    }
    return Object.values(byCell)
  }, [edits])

  const save = async () => {
    setSaving(true); setMsg(null)
    try {
      const r = await api.saveBulkPrices(pending)
      setEdits({})
      await load()
      setMsg({ type: 'ok', text: `Saved — ${r.created} added, ${r.updated} updated.` })
    } catch (e) {
      setMsg({ type: 'error', text: e.message })
    } finally {
      setSaving(false)
    }
  }

  // Copy the value typed (or shown) for the first day down into every
  // still-blank day of that column — handy when the price held steady.
  const fillColumn = (tank, f) => {
    const field = f === 'cost' ? 'cost_per_gallon' : 'sale_price_per_gallon'
    let last = null
    const next = { ...edits }
    for (const day of data.days) {
      const typed = edits[key(tank.id, day, f)]
      if (typed !== undefined && typed !== '') { last = typed; continue }
      if (last === null) {
        const cell = tank.days[day]
        if (cell?.entered && cell[field] != null) last = String(cell[field])
        continue
      }
      if (!tank.days[day]?.entered) next[key(tank.id, day, f)] = String(last)
    }
    setEdits(next)
  }

  const monthTitle = data
    ? new Date(`${data.month}-01T00:00:00`).toLocaleDateString(undefined, { month: 'long', year: 'numeric' })
    : ''

  return (
    <div style={{
      background: 'var(--brand-surface, #1e2130)', borderRadius: 12,
      padding: '18px 16px', border: '1.5px solid var(--brand-border, #2d3348)',
    }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: 8, marginBottom: 6 }}>
        <div style={{ fontWeight: 700, fontSize: 16, color: 'var(--brand-text, #e2e8f0)' }}>
          Bulk pricing — {monthTitle}
        </div>
        <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
          {msg && <span style={{ fontSize: 12, color: msg.type === 'ok' ? '#86efac' : '#fca5a5' }}>{msg.text}</span>}
          <button
            disabled={saving || pending.length === 0}
            onClick={save}
            style={{ ...btn, background: 'var(--brand-primary, #3b82f6)', border: 'none', color: '#fff', opacity: pending.length ? 1 : 0.5 }}
          >
            {saving ? 'Saving…' : `Save ${pending.length} day${pending.length === 1 ? '' : 's'}`}
          </button>
          <button style={btn} onClick={onClose}>← Back to dashboard</button>
        </div>
      </div>

      <div style={{ fontSize: 11, color: 'var(--brand-text-dimmer, #64748b)', marginBottom: 12, lineHeight: 1.5 }}>
        Enter the cost (what you paid, arrives ~6 AM) and the pump sale price for each day. Both take effect at
        6:00 AM that day. Leave a cell blank to keep the previous day's price — grey numbers are what's currently
        in effect. Tax rate and additional fee apply automatically. For a price change at another time of day,
        use "Update price" on the dashboard.
      </div>

      {loading && <div style={{ textAlign: 'center', color: 'var(--brand-text-dimmer, #64748b)', padding: 24, fontSize: 12 }}>Loading…</div>}

      {data && !loading && (
        <div style={{ overflow: 'auto', maxHeight: '70vh', border: '1px solid var(--brand-border, #2d3348)', borderRadius: 8 }}>
          <table style={{ borderCollapse: 'collapse', width: '100%', fontSize: 12 }}>
            <thead>
              <tr>
                <th style={th} rowSpan={2}>Day</th>
                {data.tanks.map(t => (
                  <th key={t.id} colSpan={2} style={{ ...th, textAlign: 'center', borderLeft: '1px solid var(--brand-border, #2d3348)' }}>
                    {t.name}
                  </th>
                ))}
              </tr>
              <tr>
                {data.tanks.map(t => (
                  <React.Fragment key={t.id}>
                    <th style={{ ...th, top: 28, borderLeft: '1px solid var(--brand-border, #2d3348)' }}>
                      Cost <button style={{ ...btn, padding: '1px 6px', fontSize: 10, marginLeft: 4 }}
                        title="Copy the first filled day's value down into blank days"
                        onClick={() => fillColumn(t, 'cost')}>fill ↓</button>
                    </th>
                    <th style={{ ...th, top: 28 }}>
                      Sale <button style={{ ...btn, padding: '1px 6px', fontSize: 10, marginLeft: 4 }}
                        title="Copy the first filled day's value down into blank days"
                        onClick={() => fillColumn(t, 'sale')}>fill ↓</button>
                    </th>
                  </React.Fragment>
                ))}
              </tr>
            </thead>
            <tbody>
              {data.days.map(day => (
                <tr key={day} style={{ borderTop: '1px solid var(--brand-border, #2d3348)' }}>
                  <td style={{ padding: '4px 8px', whiteSpace: 'nowrap', color: 'var(--brand-text-dim, #94a3b8)' }}>{dayLabel(day)}</td>
                  {data.tanks.map(t => {
                    const cell = t.days[day] || {}
                    return (
                      <React.Fragment key={t.id}>
                        {['cost', 'sale'].map((f, i) => {
                          const cur = f === 'cost' ? cell.cost_per_gallon : cell.sale_price_per_gallon
                          const v = edits[key(t.id, day, f)] ?? ''
                          return (
                            <td key={f} style={{
                              padding: '3px 6px',
                              borderLeft: i === 0 ? '1px solid var(--brand-border, #2d3348)' : undefined,
                            }}>
                              <input
                                type="number" step="0.000001" min={0}
                                value={v}
                                onChange={e => setEdit(t.id, day, f, e.target.value)}
                                placeholder={cur != null ? Number(cur).toFixed(4) : '—'}
                                style={{
                                  ...cellInput,
                                  borderColor: v !== '' ? 'var(--brand-primary, #3b82f6)'
                                    : cell.entered ? '#22c55e88' : 'var(--brand-border-soft, #374151)',
                                }}
                              />
                            </td>
                          )
                        })}
                      </React.Fragment>
                    )
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <div style={{ fontSize: 10, color: 'var(--brand-text-dimmer, #64748b)', marginTop: 8 }}>
        Green outline = a 6 AM entry already exists for that day (typing replaces it). Blue = unsaved change.
      </div>
    </div>
  )
}
