import React, { useEffect, useState, useCallback } from 'react'
import { api } from '../api/client.js'
import { PriceForm, money } from './PricingPanel.jsx'

const btn = {
  padding: '5px 10px', borderRadius: 6, cursor: 'pointer', fontSize: 11, fontWeight: 600,
  border: '1px solid #374151', background: 'transparent', color: '#cbd5e1',
}

// Single place to see and update every product's price at once — the
// per-tank PricingPanel below still exists for history/editing individual
// entries, but this is the "update everything without switching tanks"
// interface.
export default function AllPricingPanel({ tanks }) {
  const [prices, setPrices] = useState({})   // tank_id -> current price or null
  const [loading, setLoading] = useState(true)
  const [editingTankId, setEditingTankId] = useState(null)

  const load = useCallback(async () => {
    if (!tanks?.length) { setLoading(false); return }
    setLoading(true)
    const entries = await Promise.all(
      tanks.map(t => api.currentPrice(t.id).then(p => [t.id, p]).catch(() => [t.id, null]))
    )
    setPrices(Object.fromEntries(entries))
    setLoading(false)
  }, [tanks])

  useEffect(() => { load() }, [load])

  if (!tanks?.length) return null

  return (
    <div style={{
      background: '#1e2130', borderRadius: 12,
      padding: '18px 16px', border: '1.5px solid #2d3348',
    }}>
      <div style={{ fontWeight: 700, fontSize: 15, color: '#e2e8f0', marginBottom: 12 }}>
        Pricing — all products
      </div>

      {loading && <div style={{ textAlign: 'center', color: '#64748b', padding: 20, fontSize: 12 }}>Loading…</div>}

      {!loading && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
          {tanks.map(tank => {
            const p = prices[tank.id]
            return (
              <div key={tank.id} style={{
                background: '#111827', border: '1px solid #2d3348', borderRadius: 8,
                padding: '10px 12px',
              }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: 8 }}>
                  <div style={{ fontWeight: 700, fontSize: 13, minWidth: 100 }}>{tank.name}</div>
                  {p ? (
                    <div style={{ fontSize: 12, color: '#cbd5e1', flex: 1 }}>
                      cost {money(p.cost_per_gallon, 4)} · sale {money(p.sale_price_per_gallon, 4)}
                      {' · '}
                      <span style={{ color: p.margin_per_gallon >= 0 ? '#86efac' : '#fca5a5' }}>
                        margin {money(p.margin_per_gallon, 4)}
                      </span>
                    </div>
                  ) : (
                    <div style={{ fontSize: 12, color: '#64748b', flex: 1 }}>No pricing set yet</div>
                  )}
                  <button style={btn} onClick={() => setEditingTankId(editingTankId === tank.id ? null : tank.id)}>
                    {editingTankId === tank.id ? '× Cancel' : (p ? 'Update' : '+ Set price')}
                  </button>
                </div>
                {editingTankId === tank.id && (
                  <div style={{ marginTop: 8 }}>
                    <PriceForm
                      tank={tank}
                      onCancel={() => setEditingTankId(null)}
                      onDone={() => { setEditingTankId(null); load() }}
                    />
                  </div>
                )}
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}
