import React, { useEffect, useState, useCallback } from 'react'
import { api } from '../api/client.js'
import PollLogPanel from './PollLogPanel.jsx'

function nextSlotsPreview(intervalMinutes) {
  if (!intervalMinutes || intervalMinutes <= 0) return ''
  const slots = []
  for (let m = 0; m < 120 && slots.length < 4; m += intervalMinutes) {
    const h = Math.floor(m / 60)
    const mm = m % 60
    slots.push(`${String(h).padStart(2, '0')}:${String(mm).padStart(2, '0')}`)
  }
  return slots.join(', ') + ' …'
}

const row = { display: 'flex', flexDirection: 'column', gap: 6, marginBottom: 18 }
const label = { fontSize: 12, fontWeight: 700, color: '#94a3b8', textTransform: 'uppercase', letterSpacing: 0.4 }
const hint = { fontSize: 11, color: '#64748b' }
const inputStyle = {
  background: '#111827', border: '1px solid #374151', borderRadius: 7,
  color: '#e2e8f0', fontSize: 13, padding: '8px 10px', width: '100%', boxSizing: 'border-box',
}
const btn = (primary) => ({
  padding: '8px 16px', borderRadius: 7, cursor: 'pointer', fontSize: 12, fontWeight: 700,
  border: primary ? 'none' : '1px solid #374151',
  background: primary ? '#3b82f6' : 'transparent',
  color: primary ? '#fff' : '#cbd5e1',
})

function TankEditor({ tank, onSaved }) {
  const [capacity, setCapacity] = useState(tank.capacity_gallons ?? '')
  const [reorder, setReorder] = useState(tank.reorder_threshold_gallons ?? '')
  const [saving, setSaving] = useState(false)
  const [msg, setMsg] = useState(null)

  const dirty = Number(capacity) !== tank.capacity_gallons || Number(reorder) !== tank.reorder_threshold_gallons

  const save = async () => {
    setSaving(true); setMsg(null)
    try {
      const updated = await api.updateTank(tank.id, {
        capacity_gallons: Number(capacity),
        reorder_threshold_gallons: Number(reorder),
      })
      setMsg('Saved')
      onSaved?.(updated)
    } catch (e) {
      setMsg(e.message)
    } finally {
      setSaving(false)
    }
  }

  return (
    <div style={{
      background: '#111827', border: '1px solid #2d3348', borderRadius: 8,
      padding: '10px 12px', marginBottom: 8,
    }}>
      <div style={{ fontSize: 12, fontWeight: 700, color: '#cbd5e1', marginBottom: 6 }}>{tank.name}</div>
      <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
        <div style={{ flex: 1 }}>
          <div style={{ fontSize: 10, color: '#64748b', marginBottom: 3 }}>Capacity (gal)</div>
          <input type="number" min={1} value={capacity} onChange={e => setCapacity(e.target.value)}
            style={{ ...inputStyle, padding: '6px 8px', fontSize: 12 }} />
        </div>
        <div style={{ flex: 1 }}>
          <div style={{ fontSize: 10, color: '#64748b', marginBottom: 3 }}>Reorder at (gal)</div>
          <input type="number" min={0} value={reorder} onChange={e => setReorder(e.target.value)}
            style={{ ...inputStyle, padding: '6px 8px', fontSize: 12 }} />
        </div>
        <button
          disabled={saving || !dirty}
          onClick={save}
          style={{ ...btn(true), padding: '6px 12px', fontSize: 11, opacity: dirty ? 1 : 0.4, alignSelf: 'flex-end' }}
        >
          Save
        </button>
      </div>
      {msg && <div style={{ fontSize: 10, color: msg === 'Saved' ? '#86efac' : '#fca5a5', marginTop: 4 }}>{msg}</div>}
    </div>
  )
}

export default function SettingsPanel({ open, onClose }) {
  const [settings, setSettings] = useState(null)
  const [interval, setInterval_] = useState(60)
  const [aligned, setAligned] = useState(true)
  const [deviceIdInput, setDeviceIdInput] = useState('')
  const [status, setStatus] = useState(null)
  const [saving, setSaving] = useState(false)
  const [tanks, setTanks] = useState(null)

  const load = useCallback(async () => {
    try {
      const [s, t] = await Promise.all([api.settings(), api.tanks()])
      setSettings(s)
      setInterval_(s.poll_interval_minutes)
      setAligned(s.poll_aligned)
      setDeviceIdInput(s.device_id)
      setTanks(t)
    } catch (e) {
      setStatus({ type: 'error', msg: e.message })
    }
  }, [])

  useEffect(() => { if (open) load() }, [open, load])

  if (!open) return null

  const save = async (patch, successMsg) => {
    setSaving(true); setStatus(null)
    try {
      const s = await api.updateSettings(patch)
      setSettings(s)
      setStatus({ type: 'ok', msg: successMsg })
    } catch (e) {
      setStatus({ type: 'error', msg: e.message })
    } finally {
      setSaving(false)
    }
  }

  const handlePollNow = async () => {
    setSaving(true); setStatus(null)
    try {
      await api.pollNow()
      setStatus({ type: 'ok', msg: 'Poll requested — the poller will run within ~15s.' })
    } catch (e) {
      setStatus({ type: 'error', msg: e.message })
    } finally {
      setSaving(false)
    }
  }

  const handleRegenerateDeviceId = async () => {
    setSaving(true); setStatus(null)
    try {
      const r = await api.regenerateDeviceId()
      setDeviceIdInput(r.device_id)
      setSettings(s => s && ({ ...s, device_id: r.device_id }))
      setStatus({ type: 'ok', msg: 'New device ID generated.' })
    } catch (e) {
      setStatus({ type: 'error', msg: e.message })
    } finally {
      setSaving(false)
    }
  }

  const copyDeviceId = () => {
    navigator.clipboard?.writeText(deviceIdInput)
    setStatus({ type: 'ok', msg: 'Device ID copied to clipboard.' })
  }

  return (
    <div style={{
      position: 'fixed', inset: 0, background: '#00000099', zIndex: 100,
      display: 'flex', justifyContent: 'flex-end',
    }} onClick={onClose}>
      <div
        onClick={e => e.stopPropagation()}
        style={{
          width: 'min(420px, 100vw)', height: '100vh', overflowY: 'auto',
          background: '#161b27', borderLeft: '1px solid #2d3348',
          padding: '24px 22px', boxSizing: 'border-box',
        }}
      >
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 20 }}>
          <div style={{ fontWeight: 800, fontSize: 17, color: '#e2e8f0' }}>Settings</div>
          <button onClick={onClose} style={{
            background: 'none', border: 'none', color: '#64748b', fontSize: 20, cursor: 'pointer',
          }}>×</button>
        </div>

        {!settings && <div style={{ color: '#64748b', fontSize: 12 }}>Loading…</div>}

        {settings && (
          <>
            {/* Tank sizes */}
            <div style={row}>
              <label style={label}>Tank sizes</label>
              <div style={hint}>
                Correct a tank's capacity or reorder threshold if the installed size
                differs from the initial estimate. Saved changes stick — the poller
                won't overwrite them from config again.
              </div>
              <div style={{ marginTop: 8 }}>
                {(tanks ?? []).map(t => (
                  <TankEditor
                    key={t.id}
                    tank={t}
                    onSaved={updated => setTanks(ts => ts.map(x => x.id === updated.id ? { ...x, ...updated } : x))}
                  />
                ))}
              </div>
            </div>

            <div style={{ borderTop: '1px solid #2d3348', margin: '4px 0 20px' }} />

            {/* Poll interval */}
            <div style={row}>
              <label style={label}>Poll interval</label>
              <select
                value={interval}
                onChange={e => setInterval_(Number(e.target.value))}
                style={inputStyle}
              >
                {settings.available_intervals.map(m => (
                  <option key={m} value={m}>{m} minutes</option>
                ))}
                {!settings.available_intervals.includes(interval) && (
                  <option value={interval}>{interval} minutes (custom)</option>
                )}
              </select>
              <input
                type="number" min={1} max={1440}
                value={interval}
                onChange={e => setInterval_(Number(e.target.value))}
                placeholder="Custom minutes"
                style={{ ...inputStyle, marginTop: 4 }}
              />
              <div style={hint}>How often the gauge is polled over the network.</div>
            </div>

            {/* Aligned polling */}
            <div style={row}>
              <label style={{ ...label, display: 'flex', alignItems: 'center', gap: 8, cursor: 'pointer' }}>
                <input type="checkbox" checked={aligned} onChange={e => setAligned(e.target.checked)} />
                Align polls to the clock
              </label>
              <div style={hint}>
                {aligned
                  ? `On: polls land on fixed clock marks — e.g. ${nextSlotsPreview(interval)}`
                  : 'Off: polls run every N minutes from whenever the poller last ran (legacy behavior).'}
              </div>
            </div>

            <button
              disabled={saving}
              style={{ ...btn(true), width: '100%', marginBottom: 22 }}
              onClick={() => save({ poll_interval_minutes: interval, poll_aligned: aligned }, 'Poll schedule saved.')}
            >
              Save poll schedule
            </button>

            <button
              disabled={saving}
              style={{ ...btn(false), width: '100%', marginBottom: 20 }}
              onClick={handlePollNow}
            >
              ⚡ Poll now
            </button>

            <div style={{ marginBottom: 26 }}>
              <PollLogPanel />
            </div>

            <div style={{ borderTop: '1px solid #2d3348', margin: '4px 0 20px' }} />

            {/* Device ID / cloud */}
            <div style={row}>
              <label style={label}>Device ID (hex)</label>
              <div style={hint}>
                Identifies this station for a future cloud deployment. Not active yet — proof of concept phase.
              </div>
              <input
                value={deviceIdInput}
                onChange={e => setDeviceIdInput(e.target.value)}
                style={{ ...inputStyle, fontFamily: 'monospace', marginTop: 4 }}
              />
              <div style={{ display: 'flex', gap: 8, marginTop: 8 }}>
                <button style={btn(false)} onClick={copyDeviceId}>Copy</button>
                <button style={btn(false)} onClick={handleRegenerateDeviceId} disabled={saving}>Generate new</button>
                <button
                  style={btn(true)}
                  disabled={saving || deviceIdInput === settings.device_id}
                  onClick={() => save({ device_id: deviceIdInput }, 'Device ID saved.')}
                >
                  Save
                </button>
              </div>
            </div>

            <div style={row}>
              <label style={{ ...label, display: 'flex', alignItems: 'center', gap: 8, opacity: 0.5 }}>
                <input type="checkbox" checked={settings.remote_enabled} disabled />
                Remote / cloud sync
              </label>
              <div style={hint}>Coming soon — local proof of concept first.</div>
            </div>

            {status && (
              <div style={{
                marginTop: 8, fontSize: 12, padding: '8px 10px', borderRadius: 7,
                background: status.type === 'ok' ? '#052e16' : '#450a0a',
                color: status.type === 'ok' ? '#86efac' : '#fca5a5',
              }}>
                {status.msg}
              </div>
            )}
          </>
        )}
      </div>
    </div>
  )
}
