import React, { useEffect, useState, useCallback } from 'react'
import { format } from 'date-fns'
import { api } from '../api/client.js'

const btn = {
  padding: '5px 10px', borderRadius: 6, cursor: 'pointer', fontSize: 11, fontWeight: 600,
  border: '1px solid var(--brand-border-soft, #374151)', background: 'transparent', color: 'var(--brand-text, #cbd5e1)',
}

function nowLocalInputValue() {
  const d = new Date()
  d.setSeconds(0, 0)
  d.setMinutes(d.getMinutes() - d.getTimezoneOffset())
  return d.toISOString().slice(0, 16)
}

function EditTotal({ event, onSaved, onCancel }) {
  const [value, setValue] = useState(Math.round(event.effective_gallons_received ?? event.gallons_received))
  const [saving, setSaving] = useState(false)
  const [err, setErr] = useState(null)

  const save = async () => {
    setSaving(true); setErr(null)
    try {
      const updated = await api.confirmDelivery(event.id, Number(value))
      onSaved(updated)
    } catch (e) {
      setErr(e.message)
    } finally {
      setSaving(false)
    }
  }

  return (
    <div style={{ display: 'flex', gap: 6, alignItems: 'center', marginTop: 6 }}>
      <input
        type="number" min={0} value={value} onChange={e => setValue(e.target.value)}
        style={{
          background: 'var(--brand-well, #111827)', border: '1px solid var(--brand-border-soft, #374151)', borderRadius: 6,
          color: 'var(--brand-text, #e2e8f0)', fontSize: 12, padding: '5px 8px', width: 100,
        }}
      />
      <span style={{ fontSize: 11, color: 'var(--brand-text-dimmer, #64748b)' }}>gal</span>
      <button style={{ ...btn, background: 'var(--brand-primary, #3b82f6)', border: 'none', color: '#fff' }} disabled={saving} onClick={save}>
        Confirm
      </button>
      <button style={btn} onClick={onCancel}>Cancel</button>
      {err && <span style={{ color: '#fca5a5', fontSize: 11 }}>{err}</span>}
    </div>
  )
}

function LogDeliveryForm({ tank, onSaved, onCancel }) {
  const [gallons, setGallons] = useState('')
  const [when, setWhen] = useState(nowLocalInputValue())
  const [note, setNote] = useState('')
  const [saving, setSaving] = useState(false)
  const [err, setErr] = useState(null)

  const submit = async () => {
    if (!gallons || Number(gallons) <= 0) { setErr('Enter a gallons amount'); return }
    setSaving(true); setErr(null)
    try {
      const created = await api.logManualDelivery(tank.id, {
        gallonsReceived: Number(gallons), detectedAt: when, note: note || undefined,
      })
      onSaved(created)
    } catch (e) {
      setErr(e.message)
    } finally {
      setSaving(false)
    }
  }

  return (
    <div style={{
      background: 'var(--brand-well, #111827)', border: '1px solid var(--brand-border, #2d3348)', borderRadius: 8,
      padding: '10px 12px', marginBottom: 10,
    }}>
      <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', marginBottom: 8 }}>
        <div>
          <div style={{ fontSize: 10, color: 'var(--brand-text-dimmer, #64748b)', marginBottom: 3 }}>Gallons</div>
          <input type="number" min={1} value={gallons} onChange={e => setGallons(e.target.value)}
            placeholder="e.g. 6015"
            style={{ background: 'var(--brand-surface-2, #0b0f19)', border: '1px solid var(--brand-border-soft, #374151)', borderRadius: 6, color: 'var(--brand-text, #e2e8f0)', fontSize: 12, padding: '6px 8px', width: 110 }} />
        </div>
        <div>
          <div style={{ fontSize: 10, color: 'var(--brand-text-dimmer, #64748b)', marginBottom: 3 }}>When</div>
          <input type="datetime-local" value={when} onChange={e => setWhen(e.target.value)}
            style={{ background: 'var(--brand-surface-2, #0b0f19)', border: '1px solid var(--brand-border-soft, #374151)', borderRadius: 6, color: 'var(--brand-text, #e2e8f0)', fontSize: 12, padding: '6px 8px' }} />
        </div>
        <div style={{ flex: 1, minWidth: 140 }}>
          <div style={{ fontSize: 10, color: 'var(--brand-text-dimmer, #64748b)', marginBottom: 3 }}>Note (optional)</div>
          <input type="text" value={note} onChange={e => setNote(e.target.value)}
            placeholder="e.g. driver ticket #123"
            style={{ background: 'var(--brand-surface-2, #0b0f19)', border: '1px solid var(--brand-border-soft, #374151)', borderRadius: 6, color: 'var(--brand-text, #e2e8f0)', fontSize: 12, padding: '6px 8px', width: '100%', boxSizing: 'border-box' }} />
        </div>
      </div>
      <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
        <button style={{ ...btn, background: 'var(--brand-primary, #3b82f6)', border: 'none', color: '#fff' }} disabled={saving} onClick={submit}>
          Save delivery
        </button>
        <button style={btn} onClick={onCancel}>Cancel</button>
        {err && <span style={{ color: '#fca5a5', fontSize: 11 }}>{err}</span>}
      </div>
    </div>
  )
}

export default function DeliveryPanel({ tank }) {
  const [events, setEvents] = useState([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)
  const [editingId, setEditingId] = useState(null)
  const [showLogForm, setShowLogForm] = useState(false)

  const load = useCallback(async () => {
    if (!tank) return
    setLoading(true); setError(null)
    try {
      const rows = await api.deliveries(tank.id)
      setEvents(rows.slice(0, 10))
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
      background: 'var(--brand-surface, #1e2130)', borderRadius: 12,
      padding: '18px 16px', border: '1.5px solid var(--brand-border, #2d3348)',
    }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 10 }}>
        <div style={{ fontWeight: 700, fontSize: 15, color: 'var(--brand-text, #e2e8f0)' }}>
          {tank.name} — Recent Fuel Deliveries
        </div>
        <button style={btn} onClick={() => setShowLogForm(v => !v)}>
          {showLogForm ? '× Cancel' : '+ Log delivery'}
        </button>
      </div>

      {showLogForm && (
        <LogDeliveryForm
          tank={tank}
          onCancel={() => setShowLogForm(false)}
          onSaved={() => { setShowLogForm(false); load() }}
        />
      )}

      {loading && <div style={{ textAlign: 'center', color: 'var(--brand-text-dimmer, #64748b)', padding: 20, fontSize: 12 }}>Loading…</div>}
      {error && <div style={{ color: '#ef4444', fontSize: 12, padding: 12 }}>Error: {error}</div>}
      {!loading && !error && events.length === 0 && (
        <div style={{ textAlign: 'center', color: 'var(--brand-text-dimmer, #64748b)', padding: 20, fontSize: 12 }}>
          No deliveries detected recently — use "+ Log delivery" to report one manually
        </div>
      )}

      {events.map(e => {
        const effective = e.effective_gallons_received ?? e.gallons_received
        const isManual = e.manual_gallons_received != null
        const showAdjustedHint = !isManual && e.adjusted_gallons_received != null
          && Math.round(e.adjusted_gallons_received) !== Math.round(e.gallons_received)

        return (
          <div key={e.id} style={{
            padding: '10px 12px', background: '#052e16', borderRadius: 8,
            border: '1px solid #16653433', marginBottom: 8,
          }}>
            <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between' }}>
              <div>
                <div style={{ color: '#86efac', fontWeight: 700, fontSize: 13 }}>
                  +{Math.round(effective).toLocaleString()} gal
                  {isManual && <span style={{ color: '#93c5fd', fontWeight: 600, fontSize: 10, marginLeft: 6 }}>✓ verified</span>}
                  {!e.confirmed && !isManual && (
                    <span style={{ color: '#fbbf24', fontWeight: 600, fontSize: 10, marginLeft: 6 }}>unconfirmed</span>
                  )}
                  {e.merged_poll_count > 1 && (
                    <span style={{ color: 'var(--brand-text-dimmer, #64748b)', fontWeight: 500, fontSize: 10, marginLeft: 6 }}>
                      · combined from {e.merged_poll_count} polls
                    </span>
                  )}
                </div>
                {showAdjustedHint && (
                  <div style={{ color: '#93c5fd', fontSize: 11, marginTop: 2 }} title="Net change plus estimated gallons sold during the delivery window">
                    net {Math.round(e.gallons_received).toLocaleString()} gal · est. gross {Math.round(e.adjusted_gallons_received).toLocaleString()} gal
                  </div>
                )}
                {e.note && <div style={{ color: 'var(--brand-text-dim, #94a3b8)', fontSize: 11, marginTop: 2, fontStyle: 'italic' }}>{e.note}</div>}
                <div style={{ color: 'var(--brand-text-dimmer, #64748b)', fontSize: 11, marginTop: 2 }}>
                  {format(new Date(e.detected_at), 'MMM d, yyyy · HH:mm')}
                </div>
              </div>
              <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'flex-end', gap: 4 }}>
                {e.start_volume_gallons != null && e.end_volume_gallons != null && (
                  <div style={{ fontSize: 11, color: 'var(--brand-text-dimmer, #64748b)' }}>
                    {Math.round(e.start_volume_gallons).toLocaleString()} → {Math.round(e.end_volume_gallons).toLocaleString()} gal
                  </div>
                )}
                {editingId !== e.id && (
                  <button style={btn} onClick={() => setEditingId(e.id)}>
                    {isManual ? 'Edit' : 'Confirm / edit'}
                  </button>
                )}
              </div>
            </div>

            {editingId === e.id && (
              <EditTotal
                event={e}
                onCancel={() => setEditingId(null)}
                onSaved={updated => {
                  setEvents(evs => evs.map(x => x.id === updated.id ? updated : x))
                  setEditingId(null)
                }}
              />
            )}
          </div>
        )
      })}
    </div>
  )
}
