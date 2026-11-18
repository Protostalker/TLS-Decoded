/**
 * Fleet — the Fuel Provider's own infrastructure: Loading Racks (where a
 * tanker picks up fuel), Tankers (physical vehicles + their fixed
 * compartments), Loads (what a tanker is carrying on one trip), and
 * Delivery Runs (that load, dropped off across 1+ stations in sequence —
 * the daisy chain).
 *
 * Four tabs, matching the order you'd actually use this in: set up a rack
 * and a tanker once, load the tanker before a trip, then build the
 * delivery run that drains that load across however many stops it takes.
 */
import React, { useEffect, useState } from 'react'
import { api } from '../api/client.js'
import TopBar from '../components/TopBar.jsx'
import Footer from '../components/Footer.jsx'

const TABS = ['Loading Racks', 'Tankers', 'Loads', 'Delivery Runs', 'Reports']

export default function FleetPage() {
  const [tab, setTab] = useState('Loading Racks')

  return (
    <div style={{ minHeight: '100vh', background: 'var(--brand-bg, #0f1117)' }}>
      <TopBar title="Fleet" backTo="/supplier" />
      <main style={{ padding: 24, maxWidth: 1100, margin: '0 auto' }}>
        <div style={{ display: 'flex', gap: 8, marginBottom: 20, flexWrap: 'wrap' }}>
          {TABS.map(t => (
            <button key={t} onClick={() => setTab(t)} style={{
              background: tab === t ? '#3b82f6' : '#161b27',
              border: '1px solid var(--brand-border-soft, #1e2130)', borderRadius: 8, padding: '8px 16px',
              color: tab === t ? '#fff' : '#94a3b8', fontSize: 13, cursor: 'pointer', fontWeight: 600,
            }}>{t}</button>
          ))}
        </div>

        {tab === 'Loading Racks' && <RacksTab />}
        {tab === 'Tankers' && <TankersTab />}
        {tab === 'Loads' && <LoadsTab />}
        {tab === 'Delivery Runs' && <RunsTab />}
        {tab === 'Reports' && <ReportsTab />}
      </main>
      <Footer />
    </div>
  )
}

// ── Shared styles (same look as AdminPage, duplicated per this codebase's
//    own convention of per-page local style constants) ─────────────────────
const card = { background: 'var(--brand-surface-2, #161b27)', border: '1px solid var(--brand-border-soft, #1e2130)', borderRadius: 14, padding: 18, marginBottom: 16 }
const inputStyle = {
  background: 'var(--brand-bg, #0f1117)', border: '1px solid var(--brand-border, #2d3348)', borderRadius: 8,
  padding: '8px 10px', color: 'var(--brand-text, #e2e8f0)', fontSize: 13, outline: 'none',
}
const btn = { background: '#3b82f6', border: 'none', borderRadius: 8, padding: '8px 14px', color: '#fff', fontSize: 13, fontWeight: 600, cursor: 'pointer' }
const btnGhost = { background: 'transparent', border: '1px solid var(--brand-border, #2d3348)', borderRadius: 8, padding: '6px 10px', color: 'var(--brand-text-dim, #94a3b8)', fontSize: 12, cursor: 'pointer' }
const th = { padding: '8px 10px', fontWeight: 600, color: 'var(--brand-text-dimmer, #64748b)', textAlign: 'left', fontSize: 11 }
const td = { padding: '8px 10px', fontSize: 13 }

function Field({ label, children }) {
  return (
    <label style={{ display: 'flex', flexDirection: 'column', gap: 4, fontSize: 11, color: 'var(--brand-text-dim, #94a3b8)' }}>
      {label}
      {children}
    </label>
  )
}
function ErrorBox({ message }) {
  return <div style={{ background: 'var(--brand-danger-bg, #450a0a)', border: '1px solid #ef4444', borderRadius: 10, padding: '10px 14px', color: 'var(--brand-danger-text, #fca5a5)', fontSize: 12, marginBottom: 16 }}>{message}</div>
}

// ── Loading Racks ─────────────────────────────────────────────────────────────
function RacksTab() {
  const [racks, setRacks] = useState(null)
  const [form, setForm] = useState({ name: '', address: '' })
  const [error, setError] = useState(null)
  const [saving, setSaving] = useState(false)

  // Block body on purpose: an arrow function with an expression body
  // (`() => promise`) implicitly RETURNS that promise, and useEffect(load,
  // []) would then treat the promise as its cleanup function and try to
  // call it on unmount -- "TypeError: ... is not a function", crashing
  // the whole page the moment you switch away from this tab. Wrapping the
  // call in braces makes the effect return undefined instead.
  const load = () => { api.fleet.racks().then(setRacks).catch(e => setError(e.message)) }
  useEffect(load, [])

  const create = async (e) => {
    e.preventDefault()
    setError(null)
    setSaving(true)
    try {
      await api.fleet.createRack({ name: form.name, address: form.address })
      setForm({ name: '', address: '' })
      load()
    } catch (e) { setError(e.message) }
    finally { setSaving(false) }
  }

  const remove = async (rack) => {
    if (!window.confirm(`Delete rack "${rack.name}"? This also deletes any loads (and delivery runs) ever drawn from it. This cannot be undone.`)) return
    try { await api.fleet.deleteRack(rack.id); load() } catch (e) { setError(e.message) }
  }

  return (
    <div>
      <form onSubmit={create} style={{ ...card, display: 'flex', gap: 10, alignItems: 'flex-end', flexWrap: 'wrap' }}>
        <Field label="Rack name">
          <input required value={form.name} onChange={e => setForm({ ...form, name: e.target.value })} style={inputStyle} placeholder="e.g. Wilmington Terminal" />
        </Field>
        <Field label="Address">
          <input required value={form.address} onChange={e => setForm({ ...form, address: e.target.value })} style={{ ...inputStyle, width: 280 }} placeholder="Street, City, State Zip" />
        </Field>
        <button type="submit" disabled={saving} style={btn}>{saving ? 'Locating…' : 'Add rack'}</button>
      </form>

      {error && <ErrorBox message={error} />}

      <div style={card}>
        <div style={{ overflowX: 'auto' }}>
          <table style={{ width: '100%', borderCollapse: 'collapse', minWidth: 500 }}>
            <thead><tr><th style={th}>Name</th><th style={th}>Address</th><th style={th}>Pin</th><th style={th}></th></tr></thead>
            <tbody>
              {racks?.map(r => (
                <tr key={r.id} style={{ borderTop: '1px solid var(--brand-border-soft, #1e2130)' }}>
                  <td style={td}>{r.name}</td>
                  <td style={{ ...td, color: 'var(--brand-text-dimmer, #64748b)' }}>{r.address || '—'}</td>
                  <td style={td}>{r.lat != null ? <span style={{ color: '#86efac' }}>📍 pinned</span> : <span style={{ color: 'var(--brand-text-faint, #475569)' }}>not located</span>}</td>
                  <td style={td}><button onClick={() => remove(r)} style={{ ...btnGhost, color: '#fca5a5' }}>Delete</button></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {racks?.length === 0 && <div style={{ color: 'var(--brand-text-faint, #475569)', padding: 12, fontSize: 12 }}>No loading racks yet.</div>}
      </div>
    </div>
  )
}

// ── Tankers ───────────────────────────────────────────────────────────────────
function TankersTab() {
  const [tankers, setTankers] = useState(null)
  const [label, setLabel] = useState('')
  const [compartments, setCompartments] = useState([{ label: 'Tank 1', capacity_gallons: '' }])
  const [error, setError] = useState(null)
  const [saving, setSaving] = useState(false)

  // Block body — see RacksTab's load() above for why this matters.
  const load = () => { api.fleet.tankers().then(setTankers).catch(e => setError(e.message)) }
  useEffect(load, [])

  const addRow = () => setCompartments(c => [...c, { label: `Tank ${c.length + 1}`, capacity_gallons: '' }])
  const removeRow = (i) => setCompartments(c => c.filter((_, idx) => idx !== i))
  const updateRow = (i, field, value) => setCompartments(c => c.map((row, idx) => idx === i ? { ...row, [field]: value } : row))

  const create = async (e) => {
    e.preventDefault()
    setError(null)
    setSaving(true)
    try {
      await api.fleet.createTanker({
        label,
        compartments: compartments.filter(c => c.capacity_gallons).map(c => ({ label: c.label, capacity_gallons: Number(c.capacity_gallons) })),
      })
      setLabel('')
      setCompartments([{ label: 'Tank 1', capacity_gallons: '' }])
      load()
    } catch (e) { setError(e.message) }
    finally { setSaving(false) }
  }

  const remove = async (t) => {
    if (!window.confirm(`Delete tanker "${t.label}"? This also deletes every load and delivery run ever built from it. This cannot be undone.\n\n(If you just want to retire it without losing history, leave it and stop selecting it for new loads instead.)`)) return
    try { await api.fleet.deleteTanker(t.id); load() } catch (e) { setError(e.message) }
  }

  // "Shape" label — e.g. "10,000 gal" for one compartment, "2 x 10,000 gal
  // (20,000 total)" for a split tanker. This is the "type" a supplier is
  // really picking when they pick a tanker — the same Tanker row gets
  // reused trip after trip with different contents each time (see Loads
  // tab), it's never tied to a single delivery.
  const shapeLabel = (t) => {
    if (!t.compartments.length) return 'No compartments'
    const caps = t.compartments.map(c => c.capacity_gallons)
    const total = caps.reduce((a, b) => a + b, 0)
    if (caps.length === 1) return `${caps[0].toLocaleString()} gal`
    return `${caps.length} x compartments (${total.toLocaleString()} gal total)`
  }

  return (
    <div>
      <div style={{ fontSize: 12, color: 'var(--brand-text-dim, #94a3b8)', marginBottom: 14 }}>
        A tanker here is really a reusable <strong>type</strong> — its compartment shape (e.g. "10k single" or
        "10k+10k split") is defined once below, then reused for as many loads/runs as you like. What's actually
        inside it is chosen fresh every time on the Loads tab, so the same tanker can carry diesel one trip and a
        50/50 split the next.
      </div>

      <form onSubmit={create} style={card}>
        <div style={{ display: 'flex', gap: 10, alignItems: 'flex-end', flexWrap: 'wrap', marginBottom: 14 }}>
          <Field label="Tanker label">
            <input required value={label} onChange={e => setLabel(e.target.value)} style={inputStyle} placeholder="e.g. Tanker 7, or '10k Single'" />
          </Field>
        </div>

        <div style={{ fontSize: 12, fontWeight: 700, color: 'var(--brand-text-dim, #94a3b8)', marginBottom: 8 }}>
          Compartments — fixed physical layout, defined once and reused every time this tanker loads
        </div>
        {compartments.map((c, i) => (
          <div key={i} style={{ display: 'flex', gap: 8, marginBottom: 6, alignItems: 'center' }}>
            <input value={c.label} onChange={e => updateRow(i, 'label', e.target.value)} style={{ ...inputStyle, width: 140 }} placeholder="Tank 1" />
            <input type="number" min="1" value={c.capacity_gallons} onChange={e => updateRow(i, 'capacity_gallons', e.target.value)} style={{ ...inputStyle, width: 120 }} placeholder="Capacity (gal)" />
            {compartments.length > 1 && <button type="button" onClick={() => removeRow(i)} style={btnGhost}>Remove</button>}
          </div>
        ))}
        <div style={{ display: 'flex', gap: 10, marginTop: 10 }}>
          <button type="button" onClick={addRow} style={btnGhost}>+ Add compartment</button>
          <button type="submit" disabled={saving} style={btn}>{saving ? 'Saving…' : 'Create tanker'}</button>
        </div>
      </form>

      {error && <ErrorBox message={error} />}

      {tankers?.map(t => (
        <div key={t.id} style={card}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', marginBottom: 8, flexWrap: 'wrap', gap: 8 }}>
            <div>
              <span style={{ fontWeight: 700 }}>{t.label}</span>
              <span style={{ color: 'var(--brand-text-dimmer, #64748b)', fontWeight: 400, marginLeft: 8, fontSize: 12 }}>{shapeLabel(t)}</span>
            </div>
            <button onClick={() => remove(t)} style={{ ...btnGhost, color: '#fca5a5' }}>Delete</button>
          </div>
          <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap' }}>
            {t.compartments.map(c => (
              <div key={c.id} style={{ background: 'var(--brand-bg, #0f1117)', border: '1px solid var(--brand-border, #2d3348)', borderRadius: 8, padding: '8px 12px', fontSize: 12 }}>
                <span style={{ fontWeight: 600 }}>{c.label}</span>
                <span style={{ color: 'var(--brand-text-dimmer, #64748b)' }}> — {c.capacity_gallons.toLocaleString()} gal</span>
              </div>
            ))}
            {t.compartments.length === 0 && <span style={{ color: 'var(--brand-text-faint, #475569)', fontSize: 12 }}>No compartments defined.</span>}
          </div>
        </div>
      ))}
      {tankers?.length === 0 && <div style={{ ...card, color: 'var(--brand-text-faint, #475569)', textAlign: 'center' }}>No tankers yet.</div>}
    </div>
  )
}

// ── Loads — build a new one via the %/max compartment splitter, and list
//    existing open ones ───────────────────────────────────────────────────────
function LoadsTab() {
  const [tankers, setTankers] = useState(null)
  const [racks, setRacks] = useState(null)
  const [loads, setLoads] = useState(null)
  const [tankerId, setTankerId] = useState('')
  const [rackId, setRackId] = useState('')
  const [error, setError] = useState(null)
  const [saving, setSaving] = useState(false)
  // splits[compartmentId] = [{ product, pct }]
  const [splits, setSplits] = useState({})

  const load = () => {
    api.fleet.tankers().then(setTankers).catch(() => {})
    api.fleet.racks().then(setRacks).catch(() => {})
    api.fleet.loads(true).then(setLoads).catch(e => setError(e.message))
  }
  useEffect(load, [])

  const tanker = tankers?.find(t => String(t.id) === String(tankerId))

  const onPickTanker = (id) => {
    setTankerId(id)
    const t = tankers?.find(t => String(t.id) === String(id))
    const next = {}
    t?.compartments.forEach(c => { next[c.id] = [{ product: '', pct: '' }] })
    setSplits(next)
  }

  const setSplitRow = (compId, idx, field, value) => {
    setSplits(s => ({
      ...s,
      [compId]: s[compId].map((row, i) => i === idx ? { ...row, [field]: value } : row),
    }))
  }
  const addSplitRow = (compId) => setSplits(s => ({ ...s, [compId]: [...s[compId], { product: '', pct: '' }] }))
  const removeSplitRow = (compId, idx) => setSplits(s => ({ ...s, [compId]: s[compId].filter((_, i) => i !== idx) }))

  const maxSplitRow = (compId, idx) => {
    const rows = splits[compId]
    const othersPct = rows.reduce((sum, r, i) => i === idx ? sum : sum + (Number(r.pct) || 0), 0)
    const remainder = Math.max(0, 100 - othersPct)
    setSplitRow(compId, idx, 'pct', String(remainder))
  }

  const create = async (e) => {
    e.preventDefault()
    setError(null)
    if (!tanker) return
    const items = []
    for (const c of tanker.compartments) {
      for (const row of (splits[c.id] || [])) {
        const pct = Number(row.pct)
        if (!row.product || !pct) continue
        items.push({ tanker_compartment_id: c.id, product: row.product, gallons: Math.round(c.capacity_gallons * pct / 100) })
      }
    }
    if (items.length === 0) { setError('Add at least one product split for at least one compartment.'); return }
    setSaving(true)
    try {
      await api.fleet.createLoad({ tanker_id: Number(tankerId), loading_rack_id: Number(rackId), items })
      setTankerId(''); setRackId(''); setSplits({})
      load()
    } catch (e) { setError(e.message) }
    finally { setSaving(false) }
  }

  const removeLoad = async (l) => {
    if (!window.confirm(`Delete this load (${l.tanker_label} from ${l.loading_rack_name})? This also deletes any delivery runs built from it. This cannot be undone.`)) return
    try { await api.fleet.deleteLoad(l.id); load() } catch (e) { setError(e.message) }
  }

  return (
    <div>
      <form onSubmit={create} style={card}>
        <div style={{ display: 'flex', gap: 10, alignItems: 'flex-end', flexWrap: 'wrap', marginBottom: 16 }}>
          <Field label="Tanker">
            <select required value={tankerId} onChange={e => onPickTanker(e.target.value)} style={inputStyle}>
              <option value="">Select…</option>
              {tankers?.map(t => <option key={t.id} value={t.id}>{t.label}</option>)}
            </select>
          </Field>
          <Field label="Loading rack">
            <select required value={rackId} onChange={e => setRackId(e.target.value)} style={inputStyle}>
              <option value="">Select…</option>
              {racks?.map(r => <option key={r.id} value={r.id}>{r.name}</option>)}
            </select>
          </Field>
        </div>

        {tanker?.compartments.map(c => {
          const rows = splits[c.id] || []
          const totalPct = rows.reduce((sum, r) => sum + (Number(r.pct) || 0), 0)
          return (
            <div key={c.id} style={{ background: 'var(--brand-bg, #0f1117)', border: '1px solid var(--brand-border, #2d3348)', borderRadius: 10, padding: 14, marginBottom: 12 }}>
              <div style={{ fontWeight: 700, marginBottom: 2 }}>{c.label} <span style={{ color: 'var(--brand-text-dimmer, #64748b)', fontWeight: 400 }}>— {c.capacity_gallons.toLocaleString()} gal capacity</span></div>
              <div style={{ fontSize: 11, color: totalPct === 100 ? '#86efac' : 'var(--brand-text-dimmer, #64748b)', marginBottom: 10 }}>
                {totalPct}% allocated{totalPct === 100 ? ' ✓' : ` — ${100 - totalPct}% remaining`}
              </div>
              {rows.map((row, idx) => (
                <div key={idx} style={{ display: 'flex', gap: 8, marginBottom: 6, alignItems: 'center' }}>
                  <input value={row.product} onChange={e => setSplitRow(c.id, idx, 'product', e.target.value)} style={{ ...inputStyle, width: 120 }} placeholder="e.g. Diesel" />
                  <input type="number" min="0" max="100" value={row.pct} onChange={e => setSplitRow(c.id, idx, 'pct', e.target.value)} style={{ ...inputStyle, width: 70 }} placeholder="%" />
                  <button type="button" onClick={() => maxSplitRow(c.id, idx)} style={btnGhost}>Max</button>
                  <span style={{ fontSize: 11, color: 'var(--brand-text-dimmer, #64748b)', width: 90 }}>
                    {row.pct ? `${Math.round(c.capacity_gallons * Number(row.pct) / 100).toLocaleString()} gal` : ''}
                  </span>
                  {rows.length > 1 && <button type="button" onClick={() => removeSplitRow(c.id, idx)} style={btnGhost}>✕</button>}
                </div>
              ))}
              <button type="button" onClick={() => addSplitRow(c.id)} style={{ ...btnGhost, marginTop: 4 }}>+ Add product</button>
            </div>
          )
        })}

        {tanker && <button type="submit" disabled={saving} style={btn}>{saving ? 'Saving…' : 'Confirm load'}</button>}
      </form>

      {error && <ErrorBox message={error} />}

      <div style={{ fontSize: 13, fontWeight: 700, color: 'var(--brand-text-dim, #94a3b8)', marginBottom: 10 }}>Open loads (not yet fully allocated to a delivery run)</div>
      {loads?.map(l => (
        <div key={l.id} style={card}>
          <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 8, flexWrap: 'wrap', gap: 8 }}>
            <div style={{ fontWeight: 700 }}>{l.tanker_label} <span style={{ color: 'var(--brand-text-dimmer, #64748b)', fontWeight: 400 }}>from {l.loading_rack_name}</span></div>
            <div style={{ display: 'flex', gap: 10, alignItems: 'center' }}>
              <div style={{ fontSize: 11, color: 'var(--brand-text-dimmer, #64748b)' }}>{new Date(l.loaded_at).toLocaleString()}</div>
              <button onClick={() => removeLoad(l)} style={{ ...btnGhost, color: '#fca5a5' }}>Delete</button>
            </div>
          </div>
          <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap' }}>
            {l.items.map(i => (
              <div key={i.id} style={{ background: 'var(--brand-bg, #0f1117)', border: '1px solid var(--brand-border, #2d3348)', borderRadius: 8, padding: '6px 10px', fontSize: 12 }}>
                {i.compartment_label} — {i.product}: <strong>{Math.round(i.gallons_remaining).toLocaleString()}</strong> / {Math.round(i.gallons).toLocaleString()} gal left
              </div>
            ))}
          </div>
        </div>
      ))}
      {loads?.length === 0 && <div style={{ ...card, color: 'var(--brand-text-faint, #475569)', textAlign: 'center' }}>No open loads — confirm one above.</div>}
    </div>
  )
}

// ── Delivery Runs — pick a load, add stops in order, allocate gallons per
//    stop from the load's remaining items, dispatch ─────────────────────────
function RunsTab() {
  const [loads, setLoads] = useState(null)
  const [stations, setStations] = useState(null)
  const [runs, setRuns] = useState(null)
  const [loadId, setLoadId] = useState('')
  const [stops, setStops] = useState([]) // [{ station_id, items: [{ tanker_load_item_id, gallons }] }]
  const [error, setError] = useState(null)
  const [saving, setSaving] = useState(false)

  const load = () => {
    api.fleet.loads(true).then(setLoads).catch(() => {})
    api.supplier.stations().then(setStations).catch(() => {})
    api.fleet.runs(true).then(setRuns).catch(e => setError(e.message))
  }
  useEffect(load, [])

  const activeLoad = loads?.find(l => String(l.id) === String(loadId))

  // How much of a given load item is still free across the current DRAFT
  // (remaining on the load itself, minus whatever's already typed into
  // other stops in this not-yet-submitted run).
  const draftRemaining = (itemId) => {
    const item = activeLoad?.items.find(i => i.id === itemId)
    if (!item) return 0
    const allocated = stops.reduce((sum, s) => sum + s.items.filter(x => x.tanker_load_item_id === itemId).reduce((a, x) => a + (Number(x.gallons) || 0), 0), 0)
    return item.gallons_remaining - allocated
  }

  const addStop = () => setStops(s => [...s, { station_id: '', items: [{ tanker_load_item_id: '', gallons: '' }] }])
  const removeStop = (i) => setStops(s => s.filter((_, idx) => idx !== i))
  const updateStop = (i, field, value) => setStops(s => s.map((row, idx) => idx === i ? { ...row, [field]: value } : row))
  const updateStopItem = (si, ii, field, value) => setStops(s => s.map((row, idx) => idx === si ? { ...row, items: row.items.map((it, j) => j === ii ? { ...it, [field]: value } : it) } : row))
  const addStopItem = (si) => setStops(s => s.map((row, idx) => idx === si ? { ...row, items: [...row.items, { tanker_load_item_id: '', gallons: '' }] } : row))
  const removeStopItem = (si, ii) => setStops(s => s.map((row, idx) => idx === si ? { ...row, items: row.items.filter((_, j) => j !== ii) } : row))
  const maxStopItem = (si, ii) => {
    const itemId = stops[si].items[ii].tanker_load_item_id
    if (!itemId) return
    const already = stops[si].items.filter((x, j) => j !== ii && x.tanker_load_item_id === itemId).reduce((a, x) => a + (Number(x.gallons) || 0), 0)
    const free = draftRemaining(itemId) + (Number(stops[si].items[ii].gallons) || 0) - already
    updateStopItem(si, ii, 'gallons', String(Math.max(0, Math.round(free))))
  }

  const create = async (e) => {
    e.preventDefault()
    setError(null)
    setSaving(true)
    try {
      await api.fleet.createRun({
        tanker_load_id: Number(loadId),
        stops: stops.map(s => ({
          station_id: Number(s.station_id),
          items: s.items.filter(i => i.tanker_load_item_id && Number(i.gallons) > 0)
            .map(i => ({ tanker_load_item_id: Number(i.tanker_load_item_id), gallons: Number(i.gallons) })),
        })),
      })
      setLoadId(''); setStops([])
      load()
    } catch (e) { setError(e.message) }
    finally { setSaving(false) }
  }

  const arrive = async (runId, stopId) => {
    try { await api.fleet.arriveStop(runId, stopId); load() } catch (e) { setError(e.message) }
  }

  const removeRun = async (runId) => {
    if (!window.confirm(`Delete run #${runId}? Any gallons it drew from its load will be returned (the load becomes open again). This cannot be undone.`)) return
    try { await api.fleet.deleteRun(runId); load() } catch (e) { setError(e.message) }
  }

  return (
    <div>
      <form onSubmit={create} style={card}>
        <Field label="Tanker load">
          <select required value={loadId} onChange={e => { setLoadId(e.target.value); setStops([]) }} style={{ ...inputStyle, width: 320 }}>
            <option value="">Select a load…</option>
            {loads?.map(l => <option key={l.id} value={l.id}>{l.tanker_label} from {l.loading_rack_name} ({new Date(l.loaded_at).toLocaleDateString()})</option>)}
          </select>
        </Field>

        {activeLoad && (
          <div style={{ marginTop: 16 }}>
            {stops.map((stop, si) => (
              <div key={si} style={{ background: 'var(--brand-bg, #0f1117)', border: '1px solid var(--brand-border, #2d3348)', borderRadius: 10, padding: 14, marginBottom: 10 }}>
                <div style={{ display: 'flex', gap: 10, alignItems: 'flex-end', marginBottom: 10, flexWrap: 'wrap' }}>
                  <Field label={`Stop ${si + 1} — station`}>
                    <select required value={stop.station_id} onChange={e => updateStop(si, 'station_id', e.target.value)} style={{ ...inputStyle, width: 220 }}>
                      <option value="">Select…</option>
                      {stations?.map(s => <option key={s.id} value={s.id}>{s.name}</option>)}
                    </select>
                  </Field>
                  <button type="button" onClick={() => removeStop(si)} style={btnGhost}>Remove stop</button>
                </div>
                {stop.items.map((item, ii) => (
                  <div key={ii} style={{ display: 'flex', gap: 8, marginBottom: 6, alignItems: 'center' }}>
                    <select value={item.tanker_load_item_id} onChange={e => updateStopItem(si, ii, 'tanker_load_item_id', e.target.value)} style={{ ...inputStyle, width: 240 }}>
                      <option value="">Select product…</option>
                      {activeLoad.items.map(li => (
                        <option key={li.id} value={li.id} disabled={draftRemaining(li.id) <= 0 && item.tanker_load_item_id !== String(li.id)}>
                          {li.compartment_label} — {li.product} ({Math.round(draftRemaining(li.id)).toLocaleString()} gal left)
                        </option>
                      ))}
                    </select>
                    <input type="number" min="1" value={item.gallons} onChange={e => updateStopItem(si, ii, 'gallons', e.target.value)} style={{ ...inputStyle, width: 100 }} placeholder="Gallons" />
                    <button type="button" onClick={() => maxStopItem(si, ii)} style={btnGhost}>Max</button>
                    {stop.items.length > 1 && <button type="button" onClick={() => removeStopItem(si, ii)} style={btnGhost}>✕</button>}
                  </div>
                ))}
                <button type="button" onClick={() => addStopItem(si)} style={btnGhost}>+ Add product to this stop</button>
              </div>
            ))}
            <div style={{ display: 'flex', gap: 10 }}>
              <button type="button" onClick={addStop} style={btnGhost}>+ Add stop</button>
              {stops.length > 0 && <button type="submit" disabled={saving} style={btn}>{saving ? 'Dispatching…' : 'Dispatch delivery run'}</button>}
            </div>
          </div>
        )}
      </form>

      {error && <ErrorBox message={error} />}

      <div style={{ fontSize: 13, fontWeight: 700, color: 'var(--brand-text-dim, #94a3b8)', marginBottom: 10 }}>Active delivery runs</div>
      {runs?.map(r => <RunCard key={r.id} run={r} onArrive={arrive} onDelete={removeRun} />)}
      {runs?.length === 0 && <div style={{ ...card, color: 'var(--brand-text-faint, #475569)', textAlign: 'center' }}>No active delivery runs.</div>}
    </div>
  )
}

function RunCard({ run, onArrive, onDelete }) {
  const totalDistance = run.stops.reduce((sum, s) => sum + (s.distance_km || 0), 0)
  const totalMinutes = run.stops.reduce((sum, s) => sum + (s.eta_minutes || 0), 0)
  const delivered = run.stops.filter(s => s.status === 'delivered').length

  return (
    <div style={card}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', marginBottom: 10, flexWrap: 'wrap', gap: 6 }}>
        <div>
          <span style={{ fontWeight: 700 }}>Run #{run.id}</span>
          {run.driver_email && <span style={{ fontSize: 11, color: 'var(--brand-text-dimmer, #64748b)', marginLeft: 8 }}>🚚 {run.driver_email}</span>}
        </div>
        <div style={{ fontSize: 11, color: 'var(--brand-text-dimmer, #64748b)', display: 'flex', gap: 10, alignItems: 'center' }}>
          <span>{delivered}/{run.stops.length} stops</span>
          {totalDistance > 0 && <span>· {Math.round(totalDistance)} km</span>}
          {totalMinutes > 0 && <span>· ~{Math.round(totalMinutes)} min total</span>}
          <span style={{
            padding: '2px 8px', borderRadius: 10,
            background: run.status === 'completed' ? '#052e16' : '#1e3a5f',
            color: run.status === 'completed' ? '#86efac' : '#93c5fd',
          }}>{run.status}</span>
          {onDelete && <button onClick={() => onDelete(run.id)} style={{ ...btnGhost, color: '#fca5a5' }}>Delete</button>}
        </div>
      </div>
      {run.stops.map(stop => (
        <div key={stop.id} style={{ borderTop: '1px solid var(--brand-border-soft, #1e2130)', padding: '10px 0' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: 8 }}>
            <div>
              <span style={{ fontWeight: 600 }}>Stop {stop.stop_order + 1}: {stop.station_name}</span>
              <span style={{
                marginLeft: 8, fontSize: 10, padding: '2px 8px', borderRadius: 10,
                background: stop.status === 'delivered' ? '#052e16' : stop.status === 'in_transit' ? '#1e3a5f' : '#1e2130',
                color: stop.status === 'delivered' ? '#86efac' : stop.status === 'in_transit' ? '#93c5fd' : '#64748b',
              }}>{stop.status}</span>
            </div>
            {stop.status === 'in_transit' && (
              <button onClick={() => onArrive(run.id, stop.id)} style={btn}>Mark arrived</button>
            )}
          </div>
          {stop.delivery && (
            <div style={{ marginTop: 8 }}>
              <div style={{ background: '#0f1117', borderRadius: 4, height: 6, overflow: 'hidden' }}>
                <div style={{
                  width: `${Math.round(Math.min(stop.delivery.progress_pct, 1) * 100)}%`, height: '100%',
                  background: stop.delivery.running_late ? '#f59e0b' : '#60a5fa', borderRadius: 4,
                }} />
              </div>
              <div style={{ fontSize: 10, color: 'var(--brand-text-dimmer, #64748b)', marginTop: 3 }}>
                {stop.delivery.running_late ? 'Running late vs. estimate' : `~${Math.round(Math.min(stop.delivery.progress_pct, 1) * 100)}% of the way there`}
                {' '}· ~{Math.round(stop.delivery.eta_minutes)} min leg
              </div>
            </div>
          )}
          <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', marginTop: 8 }}>
            {stop.items.map(i => (
              <span key={i.id} style={{ fontSize: 11, color: 'var(--brand-text-dim, #94a3b8)', background: 'var(--brand-bg, #0f1117)', border: '1px solid var(--brand-border, #2d3348)', borderRadius: 6, padding: '3px 8px' }}>
                {i.product}: {Math.round(i.gallons_delivered ?? i.gallons_planned).toLocaleString()} gal{i.gallons_delivered == null ? ' (planned)' : ''}
              </span>
            ))}
          </div>
        </div>
      ))}
    </div>
  )
}

// ── Reports — daily output + a shipment-level log with planned-vs-delivered
//    variance. Pricing is a clearly-labeled stub: there's no per-gallon
//    price source wired up yet (see cloud-api's routers/fleet.py), so we
//    show the server's own pricing_note rather than guessing at a number. ──
function ReportsTab() {
  const [daily, setDaily] = useState(null)
  const [shipments, setShipments] = useState(null)
  const [error, setError] = useState(null)

  const load = () => {
    api.fleet.reports.daily(14).then(setDaily).catch(e => setError(e.message))
    api.fleet.reports.shipments(30).then(setShipments).catch(e => setError(e.message))
  }
  useEffect(load, [])

  const allProducts = Array.from(new Set((daily?.rows || []).flatMap(r => Object.keys(r.gallons_by_product))))

  return (
    <div>
      {error && <ErrorBox message={error} />}

      <div style={card}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', marginBottom: 14, flexWrap: 'wrap', gap: 8 }}>
          <div style={{ fontWeight: 700 }}>Daily output — last {daily?.days ?? 14} days</div>
          {daily && (
            <div style={{ fontSize: 12, color: 'var(--brand-text-dim, #94a3b8)' }}>
              <strong style={{ color: 'var(--brand-text, #e2e8f0)' }}>{daily.total_gallons_delivered.toLocaleString()}</strong> gal total
              {' · '}<strong style={{ color: 'var(--brand-text, #e2e8f0)' }}>{daily.total_stops_completed}</strong> stops
            </div>
          )}
        </div>

        {daily && (
          <div style={{ overflowX: 'auto' }}>
            <table style={{ width: '100%', borderCollapse: 'collapse', minWidth: 500 }}>
              <thead>
                <tr>
                  <th style={th}>Date</th>
                  <th style={th}>Stops</th>
                  <th style={th}>Runs dispatched</th>
                  {allProducts.map(p => <th key={p} style={th}>{p} (gal)</th>)}
                </tr>
              </thead>
              <tbody>
                {daily.rows.map(row => (
                  <tr key={row.date} style={{ borderTop: '1px solid var(--brand-border-soft, #1e2130)' }}>
                    <td style={td}>{row.date}</td>
                    <td style={td}>{row.stops_completed}</td>
                    <td style={{ ...td, color: 'var(--brand-text-dimmer, #64748b)' }}>{row.runs_dispatched}</td>
                    {allProducts.map(p => (
                      <td key={p} style={{ ...td, color: row.gallons_by_product[p] ? 'var(--brand-text, #e2e8f0)' : 'var(--brand-text-faint, #475569)' }}>
                        {row.gallons_by_product[p] ? Math.round(row.gallons_by_product[p]).toLocaleString() : '—'}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}

        <div style={{ fontSize: 11, color: 'var(--brand-text-faint, #475569)', marginTop: 12, fontStyle: 'italic' }}>
          💲 {daily?.pricing_note || 'Pricing not available yet.'}
        </div>
      </div>

      <div style={card}>
        <div style={{ fontWeight: 700, marginBottom: 14 }}>Shipment log — last {shipments?.days ?? 30} days</div>
        <div style={{ overflowX: 'auto' }}>
          <table style={{ width: '100%', borderCollapse: 'collapse', minWidth: 600 }}>
            <thead>
              <tr>
                <th style={th}>Delivered</th>
                <th style={th}>Station</th>
                <th style={th}>Tanker</th>
                <th style={th}>Driver</th>
                <th style={th}>Products (planned → delivered)</th>
              </tr>
            </thead>
            <tbody>
              {shipments?.shipments.map(sh => (
                <tr key={sh.stop_id} style={{ borderTop: '1px solid var(--brand-border-soft, #1e2130)' }}>
                  <td style={td}>{new Date(sh.arrived_at).toLocaleString()}</td>
                  <td style={td}>{sh.station_name}</td>
                  <td style={{ ...td, color: 'var(--brand-text-dimmer, #64748b)' }}>{sh.tanker_label}</td>
                  <td style={{ ...td, color: 'var(--brand-text-dimmer, #64748b)' }}>{sh.driver_email || '—'}</td>
                  <td style={td}>
                    {sh.items.map((it, i) => (
                      <span key={i} style={{ marginRight: 10, whiteSpace: 'nowrap' }}>
                        {it.product}: {Math.round(it.gallons_planned).toLocaleString()} → {Math.round(it.gallons_delivered ?? it.gallons_planned).toLocaleString()}
                        {Math.abs(it.variance) > 0.5 && (
                          <span style={{ color: it.variance < 0 ? '#f87171' : '#86efac', marginLeft: 4 }}>
                            ({it.variance > 0 ? '+' : ''}{Math.round(it.variance)})
                          </span>
                        )}
                      </span>
                    ))}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {shipments?.shipments.length === 0 && <div style={{ color: 'var(--brand-text-faint, #475569)', padding: 12, fontSize: 12 }}>No completed shipments yet.</div>}
      </div>
    </div>
  )
}
