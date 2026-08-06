import React, { useEffect, useState, useCallback } from 'react'
import { format, parseISO } from 'date-fns'
import { api } from '../api/client.js'

const btn = {
  padding: '5px 10px', borderRadius: 6, cursor: 'pointer', fontSize: 11, fontWeight: 600,
  border: '1px solid #374151', background: 'transparent', color: '#cbd5e1',
}
const inputStyle = {
  background: '#0b0f19', border: '1px solid #374151', borderRadius: 6,
  color: '#e2e8f0', fontSize: 12, padding: '6px 8px', width: '100%', boxSizing: 'border-box',
}
const fieldLabel = { fontSize: 10, color: '#64748b', marginBottom: 3 }

function money(n, digits = 3) {
  return n === null || n === undefined ? '—' : `$${Number(n).toFixed(digits)}`
}

// Cloud-side price updates queue on the station rather than applying
// instantly — v1 sync is one-way (station -> cloud), so this is a narrow
// exception, not a general remote-config channel. The station's own sync
// container picks these up (usually within seconds if it's online) and
// applies them locally, same as if someone typed it in at the station.
function PriceUpdateForm({ stationId, tank, onDone, onCancel }) {
  const [cost, setCost] = useState('')
  const [taxRate, setTaxRate] = useState('')
  const [sale, setSale] = useState('')
  const [note, setNote] = useState('')
  const [saving, setSaving] = useState(false)
  const [err, setErr] = useState(null)

  const submit = async () => {
    if (cost === '' || sale === '') { setErr('Cost and sale price are required'); return }
    setSaving(true); setErr(null)
    try {
      await api.submitPriceUpdate(stationId, tank.local_id, {
        cost_per_gallon: Number(cost),
        tax_rate_percent: taxRate === '' ? null : Number(taxRate),
        sale_price_per_gallon: Number(sale),
        note: note || undefined,
      })
      onDone()
    } catch (e) {
      setErr(e.message)
    } finally {
      setSaving(false)
    }
  }

  return (
    <div style={{ background: '#111827', border: '1px solid #2d3348', borderRadius: 8, padding: '10px 12px', marginTop: 8 }}>
      <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', marginBottom: 8 }}>
        <div style={{ width: 120 }}>
          <div style={fieldLabel}>Cost / gal</div>
          <input type="number" step="0.000001" min={0} value={cost} onChange={e => setCost(e.target.value)} style={inputStyle} />
        </div>
        <div style={{ width: 120 }}>
          <div style={fieldLabel}>Tax rate (%)</div>
          <input type="number" step="0.0001" min={0} value={taxRate} onChange={e => setTaxRate(e.target.value)} style={inputStyle} />
        </div>
        <div style={{ width: 120 }}>
          <div style={fieldLabel}>Sale price / gal</div>
          <input type="number" step="0.000001" min={0} value={sale} onChange={e => setSale(e.target.value)} style={inputStyle} />
        </div>
        <div style={{ flex: 1, minWidth: 140 }}>
          <div style={fieldLabel}>Note (optional)</div>
          <input type="text" value={note} onChange={e => setNote(e.target.value)} style={inputStyle} />
        </div>
      </div>
      <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
        <button style={{ ...btn, background: '#3b82f6', border: 'none', color: '#fff' }} disabled={saving} onClick={submit}>
          Queue update
        </button>
        <button style={btn} onClick={onCancel}>Cancel</button>
        {err && <span style={{ color: '#fca5a5', fontSize: 11 }}>{err}</span>}
      </div>
    </div>
  )
}

export default function PricingPanel({ stationId, tanks }) {
  const [prices, setPrices] = useState({})     // tank_local_id -> current price entry or null
  const [pending, setPending] = useState([])    // not-yet-applied PendingPriceUpdate rows
  const [loading, setLoading] = useState(true)
  const [editingTankId, setEditingTankId] = useState(null)

  const load = useCallback(async () => {
    if (!tanks?.length) { setLoading(false); return }
    setLoading(true)
    const [priceEntries, updates] = await Promise.all([
      Promise.all(tanks.map(t =>
        api.stationTankPrices(stationId, t.local_id).then(list => [t.local_id, list?.[0] ?? null]).catch(() => [t.local_id, null])
      )),
      api.priceUpdates(stationId).catch(() => []),
    ])
    setPrices(Object.fromEntries(priceEntries))
    setPending(updates.filter(u => !u.applied_at))
    setLoading(false)
  }, [stationId, tanks])

  useEffect(() => { load() }, [load])

  if (!tanks?.length) return null

  return (
    <div style={{ background: '#161b27', border: '1px solid #1e2130', borderRadius: 14, padding: 16, marginBottom: 16 }}>
      <div style={{ fontSize: 13, fontWeight: 700, color: '#94a3b8', marginBottom: 12 }}>Pricing — all products</div>

      {pending.length > 0 && (
        <div style={{
          fontSize: 11, color: '#93c5fd', background: '#0f1c33', border: '1px solid #1e3a5f',
          borderRadius: 8, padding: '8px 10px', marginBottom: 12,
        }}>
          {pending.length} update{pending.length > 1 ? 's' : ''} queued — applied next time the station checks in
          (usually within seconds if it's online).
        </div>
      )}

      {loading && <div style={{ color: '#64748b', fontSize: 12 }}>Loading…</div>}

      {!loading && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
          {tanks.map(tank => {
            const p = prices[tank.local_id]
            const pendingForTank = pending.filter(u => u.tank_local_id === tank.local_id)
            return (
              <div key={tank.local_id} style={{ background: '#111827', border: '1px solid #2d3348', borderRadius: 8, padding: '10px 12px' }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: 8 }}>
                  <div style={{ fontWeight: 700, fontSize: 13, minWidth: 100 }}>{tank.name}</div>
                  {p ? (
                    <div style={{ fontSize: 12, color: '#cbd5e1', flex: 1 }}>
                      cost {money(p.cost_per_gallon, 4)} · sale {money(p.sale_price_per_gallon, 4)}
                      {' · '}
                      <span style={{ color: p.margin_per_gallon >= 0 ? '#86efac' : '#fca5a5' }}>
                        margin {money(p.margin_per_gallon, 4)}
                      </span>
                      <span style={{ color: '#475569' }}> · as of {format(parseISO(p.effective_at), 'MMM d, HH:mm')}</span>
                    </div>
                  ) : (
                    <div style={{ fontSize: 12, color: '#64748b', flex: 1 }}>No pricing mirrored yet</div>
                  )}
                  <button style={btn} onClick={() => setEditingTankId(editingTankId === tank.local_id ? null : tank.local_id)}>
                    {editingTankId === tank.local_id ? '× Cancel' : 'Update'}
                  </button>
                </div>
                {pendingForTank.length > 0 && (
                  <div style={{ fontSize: 11, color: '#93c5fd', marginTop: 6 }}>
                    Queued: sale {money(pendingForTank[0].sale_price_per_gallon, 4)} (submitted{' '}
                    {format(parseISO(pendingForTank[0].created_at), 'MMM d, HH:mm')})
                  </div>
                )}
                {editingTankId === tank.local_id && (
                  <PriceUpdateForm
                    stationId={stationId}
                    tank={tank}
                    onCancel={() => setEditingTankId(null)}
                    onDone={() => { setEditingTankId(null); load() }}
                  />
                )}
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}
