import React, { useEffect, useState, useCallback } from 'react'
import { format, parseISO } from 'date-fns'
import { api } from '../api/client.js'

// Admin-only panel for correcting a station's grade/tank config from the
// cloud when there's no local or network access to the box. Same queue
// semantics as PricingPanel: v1 sync is one-way, so edits here are queued as
// PendingTankUpdate rows and applied by the station's own sync container on
// its next tick, then mirrored back up. Nothing here reaches into the
// station's network; it only writes to the cloud queue.

const btn = {
  padding: '5px 10px', borderRadius: 6, cursor: 'pointer', fontSize: 11, fontWeight: 600,
  border: '1px solid var(--brand-border-soft, #374151)', background: 'transparent', color: 'var(--brand-text, #cbd5e1)',
}
const btnPrimary = { ...btn, background: 'var(--brand-primary, #3b82f6)', border: 'none', color: '#fff' }
const inputStyle = {
  background: 'var(--brand-surface-2, #0b0f19)', border: '1px solid var(--brand-border-soft, #374151)', borderRadius: 6,
  color: 'var(--brand-text, #e2e8f0)', fontSize: 12, padding: '6px 8px', width: '100%', boxSizing: 'border-box',
}
const fieldLabel = { fontSize: 10, color: 'var(--brand-text-dimmer, #64748b)', marginBottom: 3 }

function TankConfigForm({ stationId, tank, onDone, onCancel }) {
  const [name, setName] = useState(tank.name ?? '')
  const [product, setProduct] = useState(tank.product ?? '')
  const [active, setActive] = useState(tank.active !== false)
  const [note, setNote] = useState('')
  const [saving, setSaving] = useState(false)
  const [err, setErr] = useState(null)

  const submit = async () => {
    if (!name.trim()) { setErr('Name is required'); return }
    setSaving(true); setErr(null)
    try {
      // Send only what changed. product cleared to empty -> null (explicit
      // clear, which the backend's set_* flags preserve across the queue).
      const body = { note: note || undefined }
      if (name !== (tank.name ?? '')) body.name = name
      if (product !== (tank.product ?? '')) body.product = product === '' ? null : product
      if (active !== (tank.active !== false)) body.active = active
      if (body.name === undefined && body.product === undefined && body.active === undefined) {
        setErr('Nothing changed'); setSaving(false); return
      }
      await api.submitTankConfigUpdate(stationId, tank.local_id, body)
      onDone()
    } catch (e) {
      setErr(e.message)
    } finally {
      setSaving(false)
    }
  }

  return (
    <div style={{ background: 'var(--brand-well, #111827)', border: '1px solid var(--brand-border, #2d3348)', borderRadius: 8, padding: '10px 12px', marginTop: 8 }}>
      <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', marginBottom: 8 }}>
        <div style={{ width: 160 }}>
          <div style={fieldLabel}>Tank name</div>
          <input type="text" value={name} onChange={e => setName(e.target.value)} style={inputStyle} />
        </div>
        <div style={{ width: 180 }}>
          <div style={fieldLabel}>Grade / product label</div>
          <input type="text" value={product} onChange={e => setProduct(e.target.value)} placeholder="(blank = clear)" style={inputStyle} />
        </div>
        <div style={{ display: 'flex', alignItems: 'flex-end', paddingBottom: 6 }}>
          <label style={{ fontSize: 12, color: 'var(--brand-text, #cbd5e1)', display: 'flex', gap: 6, alignItems: 'center', cursor: 'pointer' }}>
            <input type="checkbox" checked={active} onChange={e => setActive(e.target.checked)} />
            Active
          </label>
        </div>
        <div style={{ flex: 1, minWidth: 140 }}>
          <div style={fieldLabel}>Note (optional)</div>
          <input type="text" value={note} onChange={e => setNote(e.target.value)} style={inputStyle} />
        </div>
      </div>
      <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
        <button style={btnPrimary} disabled={saving} onClick={submit}>Queue change</button>
        <button style={btn} onClick={onCancel}>Cancel</button>
        {err && <span style={{ color: '#fca5a5', fontSize: 11 }}>{err}</span>}
      </div>
    </div>
  )
}

const DEFAULT_OVERRIDE_NOTE = 'This name will update/change.'

// Cloud-ONLY label override. Does not touch the station — it only changes how
// this tank is labeled in the cloud view (T1 + the supplier's dashboard) so a
// mislabeled grade reads correctly to everyone while the real station-side fix
// is still pending. Rendered in red with an asterisk + note.
function CloudLabelForm({ stationId, tank, onDone, onCancel }) {
  const [nameOv, setNameOv] = useState(tank.name_override ?? '')
  const [productOv, setProductOv] = useState(tank.product_override ?? '')
  const [note, setNote] = useState(tank.override_note ?? '')
  const [saving, setSaving] = useState(false)
  const [err, setErr] = useState(null)

  const save = async () => {
    setSaving(true); setErr(null)
    try {
      await api.setCloudLabel(stationId, tank.local_id, {
        name_override: nameOv,
        product_override: productOv,
        note: note,
      })
      onDone()
    } catch (e) { setErr(e.message) } finally { setSaving(false) }
  }
  const clear = async () => {
    setSaving(true); setErr(null)
    try { await api.clearCloudLabel(stationId, tank.local_id); onDone() }
    catch (e) { setErr(e.message) } finally { setSaving(false) }
  }

  return (
    <div style={{ background: 'var(--brand-well, #111827)', border: '1px solid #7f1d1d', borderRadius: 8, padding: '10px 12px', marginTop: 8 }}>
      <div style={{ fontSize: 10, color: '#f87171', marginBottom: 8 }}>
        Cloud-only label — shows in red with an asterisk to everyone (including the supplier). Does not change the station. Clear it once the station is fixed.
      </div>
      <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', marginBottom: 8 }}>
        <div style={{ width: 160 }}>
          <div style={fieldLabel}>Show name as</div>
          <input type="text" value={nameOv} onChange={e => setNameOv(e.target.value)} placeholder={tank.name} style={inputStyle} />
        </div>
        <div style={{ width: 160 }}>
          <div style={fieldLabel}>Show grade as</div>
          <input type="text" value={productOv} onChange={e => setProductOv(e.target.value)} placeholder={tank.product || '(none)'} style={inputStyle} />
        </div>
        <div style={{ flex: 1, minWidth: 160 }}>
          <div style={fieldLabel}>Asterisk note</div>
          <input type="text" value={note} onChange={e => setNote(e.target.value)} placeholder={DEFAULT_OVERRIDE_NOTE} style={inputStyle} />
        </div>
      </div>
      <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
        <button style={{ ...btn, background: '#b91c1c', border: 'none', color: '#fff' }} disabled={saving} onClick={save}>Apply cloud label</button>
        {(tank.name_override || tank.product_override) &&
          <button style={btn} disabled={saving} onClick={clear}>Clear override</button>}
        <button style={btn} onClick={onCancel}>Cancel</button>
        {err && <span style={{ color: '#fca5a5', fontSize: 11 }}>{err}</span>}
      </div>
    </div>
  )
}


export default function GradesPanel({ stationId, tanks, onApplied }) {
  const [pending, setPending] = useState([])    // not-yet-applied PendingTankUpdate rows
  const [editingTankId, setEditingTankId] = useState(null)
  const [overrideTankId, setOverrideTankId] = useState(null)
  const [reordering, setReordering] = useState(false)
  const [order, setOrder] = useState([])          // local working order of tank local_ids
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState(null)

  const load = useCallback(async () => {
    const updates = await api.tankUpdates(stationId).catch(() => [])
    setPending(updates.filter(u => !u.applied_at))
  }, [stationId])

  useEffect(() => { load() }, [load])

  if (!tanks?.length) return null

  const startReorder = () => { setOrder(tanks.map(t => t.local_id)); setReordering(true); setErr(null) }
  const move = (idx, dir) => {
    const j = idx + dir
    if (j < 0 || j >= order.length) return
    const next = order.slice()
    ;[next[idx], next[j]] = [next[j], next[idx]]
    setOrder(next)
  }
  const saveOrder = async () => {
    setBusy(true); setErr(null)
    try {
      await api.reorderTanks(stationId, order, 'Reordered from cloud Grades panel')
      setReordering(false)
      await load()
      onApplied && onApplied()
    } catch (e) {
      setErr(e.message)
    } finally {
      setBusy(false)
    }
  }
  const saveCloudOrder = async () => {
    setBusy(true); setErr(null)
    try {
      await api.cloudReorderTanks(stationId, order, 'Cloud-only reorder')
      setReordering(false)
      onApplied && onApplied()
    } catch (e) {
      setErr(e.message)
    } finally {
      setBusy(false)
    }
  }
  const clearCloudOrderNow = async () => {
    setBusy(true); setErr(null)
    try { await api.clearCloudOrder(stationId); onApplied && onApplied() }
    catch (e) { setErr(e.message) } finally { setBusy(false) }
  }
  const cloudOrderActive = tanks.some(t => t.display_order_override != null)

  const tankById = Object.fromEntries(tanks.map(t => [t.local_id, t]))
  const rows = reordering ? order.map(lid => tankById[lid]).filter(Boolean) : tanks

  return (
    <div style={{ background: 'var(--brand-surface-2, #161b27)', border: '1px solid var(--brand-border-soft, #1e2130)', borderRadius: 14, padding: 16, marginBottom: 16 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 12, flexWrap: 'wrap', gap: 8 }}>
        <div style={{ fontSize: 13, fontWeight: 700, color: 'var(--brand-text-dim, #94a3b8)' }}>
          Grades &amp; tank config <span style={{ fontWeight: 500, color: 'var(--brand-text-faint, #475569)' }}>· admin</span>
        </div>
        {!reordering
          ? <button style={btn} onClick={startReorder}>Reorder tanks</button>
          : (
            <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
              <button style={btnPrimary} disabled={busy} onClick={saveOrder} title="Drives the new order to the station">Queue for station</button>
              <button style={{ ...btnPrimary, background: '#b91c1c' }} disabled={busy} onClick={saveCloudOrder} title="Changes the order in the cloud view only — does not touch the station">Apply to cloud now</button>
              <button style={btn} disabled={busy} onClick={() => setReordering(false)}>Cancel</button>
            </div>
          )}
      </div>

      {cloudOrderActive && !reordering && (
        <div style={{ fontSize: 11, color: '#f87171', background: 'var(--brand-well, #111827)', border: '1px solid #7f1d1d', borderRadius: 8, padding: '8px 10px', marginBottom: 12, display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
          <span>Tank order is temporarily set in the cloud only<sup>*</sup> — the station's own order is unchanged.</span>
          <button style={btn} disabled={busy} onClick={clearCloudOrderNow}>Clear cloud order</button>
        </div>
      )}
      {pending.length > 0 && (
        <div style={{
          fontSize: 11, color: '#93c5fd', background: 'var(--brand-primary-soft, #0f1c33)', border: '1px solid #1e3a5f',
          borderRadius: 8, padding: '8px 10px', marginBottom: 12,
        }}>
          {pending.length} change{pending.length > 1 ? 's' : ''} queued — applied next time the station checks in
          (usually within seconds if it's online), then reflected here once it syncs back.
        </div>
      )}
      {err && <div style={{ color: '#fca5a5', fontSize: 11, marginBottom: 10 }}>{err}</div>}

      <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
        {rows.map((tank, idx) => {
          const pendingForTank = pending.filter(u => u.tank_local_id === tank.local_id)
          return (
            <div key={tank.local_id} style={{ background: 'var(--brand-well, #111827)', border: '1px solid var(--brand-border, #2d3348)', borderRadius: 8, padding: '10px 12px' }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: 8 }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 10, minWidth: 180 }}>
                  {reordering && (
                    <div style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
                      <button style={{ ...btn, padding: '0 6px' }} disabled={idx === 0} onClick={() => move(idx, -1)}>▲</button>
                      <button style={{ ...btn, padding: '0 6px' }} disabled={idx === rows.length - 1} onClick={() => move(idx, 1)}>▼</button>
                    </div>
                  )}
                  <div>
                    <div style={{ fontWeight: 700, fontSize: 13, color: 'var(--brand-text, #e2e8f0)' }}>{tank.name}</div>
                    <div style={{ fontSize: 11, color: 'var(--brand-text-dimmer, #64748b)' }}>
                      grade: {tank.product || '—'}{tank.active === false ? ' · inactive' : ''}
                    </div>
                    {(tank.name_override || tank.product_override) && (
                      <div style={{ fontSize: 11, color: '#f87171', marginTop: 2 }}>
                        cloud label: {tank.name_override || tank.name}{(tank.product_override || tank.product) ? ` · ${tank.product_override || tank.product}` : ''}<sup>*</sup>
                        <span style={{ color: 'var(--brand-text-dimmer, #64748b)' }}> — {tank.override_note || DEFAULT_OVERRIDE_NOTE}</span>
                      </div>
                    )}
                  </div>
                </div>
                {!reordering && (
                  <div style={{ display: 'flex', gap: 6 }}>
                    <button style={btn} onClick={() => { setOverrideTankId(null); setEditingTankId(editingTankId === tank.local_id ? null : tank.local_id) }}>
                      {editingTankId === tank.local_id ? '× Cancel' : 'Edit'}
                    </button>
                    <button style={{ ...btn, borderColor: '#7f1d1d', color: '#f87171' }} onClick={() => { setEditingTankId(null); setOverrideTankId(overrideTankId === tank.local_id ? null : tank.local_id) }}>
                      {overrideTankId === tank.local_id ? '× Cancel' : 'Cloud label'}
                    </button>
                  </div>
                )}
              </div>
              {pendingForTank.length > 0 && (
                <div style={{ fontSize: 11, color: '#93c5fd', marginTop: 6 }}>
                  Queued: {pendingForTank.map(u => {
                    const parts = []
                    if (u.set_name) parts.push(`name → ${u.name}`)
                    if (u.set_product) parts.push(`grade → ${u.product ?? '(cleared)'}`)
                    if (u.set_active) parts.push(u.active ? 'activate' : 'deactivate')
                    if (u.set_display_order) parts.push(`order → ${u.display_order}`)
                    return parts.join(', ')
                  }).join(' · ')}
                  {' '}(submitted {format(parseISO(pendingForTank[0].created_at), 'MMM d, HH:mm')})
                </div>
              )}
              {!reordering && editingTankId === tank.local_id && (
                <TankConfigForm
                  stationId={stationId}
                  tank={tank}
                  onCancel={() => setEditingTankId(null)}
                  onDone={() => { setEditingTankId(null); load(); onApplied && onApplied() }}
                />
              )}
              {!reordering && overrideTankId === tank.local_id && (
                <CloudLabelForm
                  stationId={stationId}
                  tank={tank}
                  onCancel={() => setOverrideTankId(null)}
                  onDone={() => { setOverrideTankId(null); onApplied && onApplied() }}
                />
              )}
            </div>
          )
        })}
      </div>
    </div>
  )
}
