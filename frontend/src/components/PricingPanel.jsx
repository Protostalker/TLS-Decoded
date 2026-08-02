import React, { useEffect, useState, useCallback } from 'react'
import { format } from 'date-fns'
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
  return n == null ? '—' : `$${Number(n).toFixed(digits)}`
}

function nowLocalInputValue() {
  const d = new Date()
  d.setSeconds(0, 0)
  d.setMinutes(d.getMinutes() - d.getTimezoneOffset())
  return d.toISOString().slice(0, 16)
}

function Tile({ label, value, accent, sub }) {
  return (
    <div style={{
      background: '#111827', border: '1px solid #2d3348', borderRadius: 10,
      padding: '12px 14px', flex: '1 1 110px', minWidth: 110,
    }}>
      <div style={{ fontSize: 10, color: '#64748b', textTransform: 'uppercase', letterSpacing: 0.4, marginBottom: 4 }}>
        {label}
      </div>
      <div style={{ fontSize: 18, fontWeight: 800, color: accent || '#e2e8f0' }}>{value}</div>
      {sub && <div style={{ fontSize: 10, color: '#64748b', marginTop: 2 }}>{sub}</div>}
    </div>
  )
}

function PriceForm({ tank, initial, onDone, onCancel }) {
  const [cost, setCost] = useState(initial?.cost_per_gallon ?? '')
  const [tax, setTax] = useState(initial?.tax_fees_per_gallon ?? '')
  const [sale, setSale] = useState(initial?.sale_price_per_gallon ?? '')
  const [when, setWhen] = useState(nowLocalInputValue())
  const [note, setNote] = useState(initial?.note ?? '')
  const [saving, setSaving] = useState(false)
  const [err, setErr] = useState(null)

  const submit = async () => {
    if (cost === '' || sale === '') { setErr('Cost and sale price are required'); return }
    setSaving(true); setErr(null)
    try {
      const body = {
        cost_per_gallon: Number(cost),
        tax_fees_per_gallon: Number(tax || 0),
        sale_price_per_gallon: Number(sale),
        note: note || undefined,
      }
      let result
      if (initial) {
        result = await api.updatePrice(initial.id, body)
      } else {
        body.effective_at = when
        result = await api.addPrice(tank.id, body)
      }
      onDone(result)
    } catch (e) {
      setErr(e.message)
    } finally {
      setSaving(false)
    }
  }

  return (
    <div style={{
      background: '#111827', border: '1px solid #2d3348', borderRadius: 8,
      padding: '10px 12px', marginBottom: 10,
    }}>
      <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', marginBottom: 8 }}>
        <div style={{ width: 130 }}>
          <div style={fieldLabel}>Cost / gal</div>
          <input type="number" step="0.000001" min={0} value={cost} onChange={e => setCost(e.target.value)}
            placeholder="4.000000" style={inputStyle} />
        </div>
        <div style={{ width: 130 }}>
          <div style={fieldLabel}>Tax + fees / gal</div>
          <input type="number" step="0.000001" min={0} value={tax} onChange={e => setTax(e.target.value)}
            placeholder="0.400000" style={inputStyle} />
        </div>
        <div style={{ width: 130 }}>
          <div style={fieldLabel}>Sale price / gal</div>
          <input type="number" step="0.000001" min={0} value={sale} onChange={e => setSale(e.target.value)}
            placeholder="4.999000" style={inputStyle} />
        </div>
        {!initial && (
          <div style={{ width: 190 }}>
            <div style={fieldLabel}>Effective from</div>
            <input type="datetime-local" value={when} onChange={e => setWhen(e.target.value)} style={inputStyle} />
          </div>
        )}
        <div style={{ flex: 1, minWidth: 140 }}>
          <div style={fieldLabel}>Note (optional)</div>
          <input type="text" value={note} onChange={e => setNote(e.target.value)}
            placeholder="e.g. supplier invoice #" style={inputStyle} />
        </div>
      </div>
      <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
        <button style={{ ...btn, background: '#3b82f6', border: 'none', color: '#fff' }} disabled={saving} onClick={submit}>
          {initial ? 'Save changes' : 'Save price'}
        </button>
        <button style={btn} onClick={onCancel}>Cancel</button>
        {err && <span style={{ color: '#fca5a5', fontSize: 11 }}>{err}</span>}
      </div>
    </div>
  )
}

export default function PricingPanel({ tank }) {
  const [current, setCurrent] = useState(null)
  const [history, setHistory] = useState([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)
  const [showAddForm, setShowAddForm] = useState(false)
  const [editingId, setEditingId] = useState(null)

  const load = useCallback(async () => {
    if (!tank) return
    setLoading(true); setError(null)
    try {
      const [cur, hist] = await Promise.all([
        api.currentPrice(tank.id),
        api.priceHistory(tank.id, { limit: 8 }),
      ])
      setCurrent(cur)
      setHistory(hist)
    } catch (e) {
      setError(e.message)
    } finally {
      setLoading(false)
    }
  }, [tank?.id])

  useEffect(() => { load() }, [load])

  if (!tank) return null

  const marginColor = current
    ? (current.margin_per_gallon > 0 ? '#86efac' : current.margin_per_gallon < 0 ? '#fca5a5' : '#94a3b8')
    : undefined

  return (
    <div style={{
      background: '#1e2130', borderRadius: 12,
      padding: '18px 16px', border: '1.5px solid #2d3348',
    }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 12 }}>
        <div style={{ fontWeight: 700, fontSize: 15, color: '#e2e8f0' }}>
          {tank.name} — Pricing &amp; Margin
        </div>
        <button style={btn} onClick={() => setShowAddForm(v => !v)}>
          {showAddForm ? '× Cancel' : '+ Update price'}
        </button>
      </div>

      {showAddForm && (
        <PriceForm tank={tank} onCancel={() => setShowAddForm(false)} onDone={() => { setShowAddForm(false); load() }} />
      )}

      {loading && <div style={{ textAlign: 'center', color: '#64748b', padding: 20, fontSize: 12 }}>Loading…</div>}
      {error && <div style={{ color: '#ef4444', fontSize: 12, padding: 12 }}>Error: {error}</div>}

      {!loading && !error && !current && !showAddForm && (
        <div style={{ textAlign: 'center', color: '#64748b', padding: 20, fontSize: 12 }}>
          No pricing set yet — use "+ Update price" to enter cost, taxes/fees, and sale price
        </div>
      )}

      {current && (
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 10, marginBottom: 14 }}>
          <Tile label="Cost" value={money(current.cost_per_gallon, 4)} />
          <Tile label="Tax + fees" value={money(current.tax_fees_per_gallon, 4)} />
          <Tile label="Breakeven" value={money(current.breakeven_per_gallon, 4)} />
          <Tile label="Sale price" value={money(current.sale_price_per_gallon, 4)} accent="#93c5fd" />
          <Tile label="Margin / gal" value={money(current.margin_per_gallon, 4)} accent={marginColor} />
          <Tile
            label="Margin %"
            value={current.margin_percent != null ? `${current.margin_percent.toFixed(2)}%` : '—'}
            accent={marginColor}
            sub={`as of ${format(new Date(current.effective_at), 'MMM d, HH:mm')}`}
          />
        </div>
      )}

      {history.length > 0 && (
        <div>
          <div style={{ fontSize: 11, color: '#64748b', marginBottom: 6, textTransform: 'uppercase', letterSpacing: 0.4 }}>
            Price history
          </div>
          {history.map(h => (
            <div key={h.id} style={{
              padding: '8px 10px', background: '#111827', borderRadius: 7,
              border: '1px solid #2d3348', marginBottom: 6,
            }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: 6 }}>
                <div style={{ fontSize: 12, color: '#cbd5e1' }}>
                  cost {money(h.cost_per_gallon, 4)} · tax {money(h.tax_fees_per_gallon, 4)} · sale {money(h.sale_price_per_gallon, 4)}
                  {' · '}
                  <span style={{ color: h.margin_per_gallon >= 0 ? '#86efac' : '#fca5a5' }}>
                    margin {money(h.margin_per_gallon, 4)}
                  </span>
                </div>
                <div style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
                  <span style={{ fontSize: 10, color: '#64748b' }}>
                    {format(new Date(h.effective_at), 'MMM d, yyyy HH:mm')}
                  </span>
                  <button style={{ ...btn, padding: '3px 8px' }} onClick={() => setEditingId(editingId === h.id ? null : h.id)}>
                    Edit
                  </button>
                  <button
                    style={{ ...btn, padding: '3px 8px', color: '#fca5a5' }}
                    onClick={async () => {
                      if (!confirm('Delete this price entry?')) return
                      await api.deletePrice(h.id)
                      load()
                    }}
                  >
                    Delete
                  </button>
                </div>
              </div>
              {h.note && <div style={{ fontSize: 11, color: '#94a3b8', marginTop: 4, fontStyle: 'italic' }}>{h.note}</div>}
              {editingId === h.id && (
                <div style={{ marginTop: 8 }}>
                  <PriceForm
                    tank={tank}
                    initial={h}
                    onCancel={() => setEditingId(null)}
                    onDone={() => { setEditingId(null); load() }}
                  />
                </div>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
