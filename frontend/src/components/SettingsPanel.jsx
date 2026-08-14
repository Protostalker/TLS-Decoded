import React, { useEffect, useState, useCallback } from 'react'
import { formatDistanceToNow, parseISO } from 'date-fns'
import { api } from '../api/client.js'
import PollLogPanel from './PollLogPanel.jsx'
import BrandLogo from './BrandLogo.jsx'
import { BRAND_PRESETS, findPreset, fileToDataUrl } from '../brandPresets.js'

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
const label = { fontSize: 12, fontWeight: 700, color: 'var(--brand-text-dim, #94a3b8)', textTransform: 'uppercase', letterSpacing: 0.4 }
const hint = { fontSize: 11, color: 'var(--brand-text-dimmer, #64748b)' }
const inputStyle = {
  background: 'var(--brand-well, #111827)', border: '1px solid var(--brand-border-soft, #374151)', borderRadius: 7,
  color: 'var(--brand-text, #e2e8f0)', fontSize: 13, padding: '8px 10px', width: '100%', boxSizing: 'border-box',
}
const btn = (primary) => ({
  padding: '8px 16px', borderRadius: 7, cursor: 'pointer', fontSize: 12, fontWeight: 700,
  border: primary ? 'none' : '1px solid var(--brand-border-soft, #374151)',
  background: primary ? 'var(--brand-primary, #3b82f6)' : 'transparent',
  color: primary ? '#fff' : 'var(--brand-text, #cbd5e1)',
})

function TankEditor({ tank, onSaved }) {
  const [capacity, setCapacity] = useState(tank.capacity_gallons ?? '')
  const [reorder, setReorder] = useState(tank.reorder_threshold_gallons ?? '')
  const [saving, setSaving] = useState(false)
  const [msg, setMsg] = useState(null)

  const dirty = Number(capacity) !== tank.capacity_gallons
    || Number(reorder) !== tank.reorder_threshold_gallons

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
      background: 'var(--brand-well, #111827)', border: '1px solid var(--brand-border, #2d3348)', borderRadius: 8,
      padding: '10px 12px', marginBottom: 8,
    }}>
      <div style={{ fontSize: 12, fontWeight: 700, color: 'var(--brand-text, #cbd5e1)', marginBottom: 6 }}>{tank.name}</div>
      <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
        <div style={{ flex: 1, minWidth: 90 }}>
          <div style={{ fontSize: 10, color: 'var(--brand-text-dimmer, #64748b)', marginBottom: 3 }}>Capacity (gal)</div>
          <input type="number" min={1} value={capacity} onChange={e => setCapacity(e.target.value)}
            style={{ ...inputStyle, padding: '6px 8px', fontSize: 12 }} />
        </div>
        <div style={{ flex: 1, minWidth: 90 }}>
          <div style={{ fontSize: 10, color: 'var(--brand-text-dimmer, #64748b)', marginBottom: 3 }}>Reorder at (gal)</div>
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
      <div style={{ fontSize: 10, color: 'var(--brand-text-dimmer, #64748b)', marginTop: 4 }}>
        Commander grade: {tank.commander_grade_id != null
          ? <span style={{ color: 'var(--brand-text-dim, #94a3b8)' }}>id {tank.commander_grade_id}</span>
          : 'not connected'} — set/change this in Commander price sync below.
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

  // Cloud sync (cloud/) — distinct from the legacy device_id field above.
  const [cloudSyncEnabled, setCloudSyncEnabled] = useState(false)
  const [cloudSyncUrl, setCloudSyncUrl] = useState('')
  const [cloudSyncDeviceId, setCloudSyncDeviceId] = useState('')
  const [cloudSyncDeviceSecret, setCloudSyncDeviceSecret] = useState('')
  const [cloudSyncInterval, setCloudSyncInterval] = useState(30)
  const [showSecret, setShowSecret] = useState(false)

  // Commander price sync — distinct from cloud sync above. Off for any
  // station that doesn't run Verifone Commander, or whose operator won't
  // allow the integration; pricing just stays fully manual in that case.
  const [commanderEnabled, setCommanderEnabled] = useState(false)
  const [commanderUrl, setCommanderUrl] = useState('')
  const [commanderTier, setCommanderTier] = useState('cash')
  const [commanderInterval, setCommanderInterval] = useState(60)
  const [testingCommander, setTestingCommander] = useState(false)
  const [commanderTestResult, setCommanderTestResult] = useState(null)
  // { [tankId]: gradeId as string, '' means unassigned } — local, dirty-tracked
  // copy of each tank's commander_grade_id, only pushed on "Save assignments".
  const [gradeAssignments, setGradeAssignments] = useState({})
  const [savingGrades, setSavingGrades] = useState(false)

  // Software updates — off by default, fully independent of everything else
  // on this panel (and of any license, since the Local Instance never has
  // one). See updater/README.md for what actually reads these settings.
  const [updateCheckEnabled, setUpdateCheckEnabled] = useState(false)
  const [updateCheckIntervalDays, setUpdateCheckIntervalDays] = useState(7)
  const [checkingNow, setCheckingNow] = useState(false)

  // Tax rate — applied automatically to every new price entry (manual or
  // Commander-synced) unless overridden per-entry. Same live-settings
  // pattern as everything else on this panel.
  const [taxRate, setTaxRate] = useState('')

  // Branding — theme colors + logo for this station's dashboard.
  const [brandPreset, setBrandPreset] = useState('default')
  const [brandPrimary, setBrandPrimary] = useState('var(--brand-primary, #3b82f6)')
  const [brandSecondary, setBrandSecondary] = useState('var(--brand-secondary, #6366f1)')
  const [brandAccent, setBrandAccent] = useState('var(--brand-primary, #3b82f6)')
  const [brandLogo, setBrandLogo] = useState('')
  const [logoError, setLogoError] = useState(null)

  const load = useCallback(async () => {
    try {
      const [s, t] = await Promise.all([api.settings(), api.tanks()])
      setSettings(s)
      setInterval_(s.poll_interval_minutes)
      setAligned(s.poll_aligned)
      setDeviceIdInput(s.device_id)
      setTanks(t)
      setGradeAssignments(Object.fromEntries(
        t.map(x => [x.id, x.commander_grade_id != null ? String(x.commander_grade_id) : ''])
      ))
      setCloudSyncEnabled(s.cloud_sync_enabled)
      setCloudSyncUrl(s.cloud_sync_url)
      setCloudSyncDeviceId(s.cloud_sync_device_id)
      setCloudSyncDeviceSecret(s.cloud_sync_device_secret)
      setCloudSyncInterval(s.cloud_sync_interval_minutes)
      setCommanderEnabled(s.commander_sync_enabled)
      setCommanderUrl(s.commander_reader_url)
      setCommanderTier(s.commander_price_tier)
      setCommanderInterval(s.commander_sync_interval_minutes)
      setUpdateCheckEnabled(s.update_check_enabled)
      setUpdateCheckIntervalDays(s.update_check_interval_days)
      setTaxRate(s.default_tax_rate_percent ?? '')
      setBrandPreset(s.brand_preset)
      setBrandPrimary(s.brand_primary_color)
      setBrandSecondary(s.brand_secondary_color)
      setBrandAccent(s.brand_accent_color)
      setBrandLogo(s.brand_logo_data_url)

      // Auto-load the grade list (for the assignment picker below) if
      // Commander sync is already configured — saves a manual "Test
      // connection" click just to see what's available to assign.
      if (s.commander_sync_enabled && s.commander_reader_url) {
        api.testCommander().then(setCommanderTestResult).catch(() => {})
      }
    } catch (e) {
      setStatus({ type: 'error', msg: e.message })
    }
  }, [])

  useEffect(() => { if (open) load() }, [open, load])

  // Lightweight status refresh while the panel is open — only updates the
  // read-only `settings` object (last-checked/connected/error), never the
  // editable form fields above, so it can't clobber an in-progress edit.
  // This is what makes the Commander heartbeat visible without reopening
  // the panel: the poller writes a fresh status every ~5 min, this just
  // needs to notice.
  useEffect(() => {
    if (!open) return
    const t = setInterval(() => {
      api.settings().then(setSettings).catch(() => {})
    }, 30_000)
    return () => clearInterval(t)
  }, [open])

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

  const saveCloudSync = () => save({
    cloud_sync_enabled: cloudSyncEnabled,
    cloud_sync_url: cloudSyncUrl,
    cloud_sync_device_id: cloudSyncDeviceId,
    cloud_sync_device_secret: cloudSyncDeviceSecret,
    cloud_sync_interval_minutes: cloudSyncInterval,
  }, 'Cloud sync settings saved — the sync service picks this up within ~15s, no restart needed.')

  const saveCommander = () => save({
    commander_sync_enabled: commanderEnabled,
    commander_reader_url: commanderUrl,
    commander_price_tier: commanderTier,
    commander_sync_interval_minutes: commanderInterval,
  }, 'Commander price sync settings saved — the poller picks this up within ~15s, no restart needed.')

  const handleTestCommander = async () => {
    setTestingCommander(true); setCommanderTestResult(null); setStatus(null)
    try {
      const r = await api.testCommander()
      setCommanderTestResult(r)
      const s = await api.settings()
      setSettings(s)
    } catch (e) {
      setStatus({ type: 'error', msg: e.message })
    } finally {
      setTestingCommander(false)
    }
  }

  const saveUpdateChecking = () => save({
    update_check_enabled: updateCheckEnabled,
    update_check_interval_days: updateCheckIntervalDays,
  }, updateCheckEnabled
    ? 'Update checking enabled — see updater/README.md to wire up the recurring check (hourly cron/Task Scheduler entry).'
    : 'Update checking disabled.')

  const handleCheckForUpdatesNow = async () => {
    setCheckingNow(true); setStatus(null)
    try {
      const r = await api.checkForUpdatesNow()
      setStatus(r.status === 'requested'
        ? { type: 'ok', msg: 'Check requested — picked up on the updater’s next run (see updater/README.md for the schedule).' }
        : { type: 'error', msg: r.detail || 'Enable update checking above first.' })
      const s = await api.settings()
      setSettings(s)
    } catch (e) {
      setStatus({ type: 'error', msg: e.message })
    } finally {
      setCheckingNow(false)
    }
  }

  const commanderCurl = `curl ${(commanderUrl || 'http://<commander-reader-host>:8200').replace(/\/$/, '')}/health`

  const copyCommanderCurl = () => {
    navigator.clipboard?.writeText(commanderCurl)
    setStatus({ type: 'ok', msg: 'Command copied to clipboard.' })
  }

  const commanderGrades = commanderTestResult?.grades ?? []
  const assignedGradeIds = new Set(
    Object.values(gradeAssignments).filter(v => v !== '').map(String)
  )
  const gradesDirty = (tanks ?? []).some(
    t => (gradeAssignments[t.id] ?? '') !== (t.commander_grade_id != null ? String(t.commander_grade_id) : '')
  )

  const saveGradeAssignments = async () => {
    setSavingGrades(true); setStatus(null)
    try {
      const changed = (tanks ?? []).filter(
        t => (gradeAssignments[t.id] ?? '') !== (t.commander_grade_id != null ? String(t.commander_grade_id) : '')
      )
      const updated = await Promise.all(changed.map(t => {
        const v = gradeAssignments[t.id]
        return api.updateTank(t.id, { commander_grade_id: v === '' ? null : Number(v) })
      }))
      setTanks(ts => ts.map(t => updated.find(u => u.id === t.id) ?? t))
      setStatus({ type: 'ok', msg: `Grade assignment${changed.length === 1 ? '' : 's'} saved — Commander sync picks this up within ~15s.` })
    } catch (e) {
      setStatus({ type: 'error', msg: e.message })
    } finally {
      setSavingGrades(false)
    }
  }

  const saveTaxRate = () => save(
    { default_tax_rate_percent: taxRate === '' ? null : Number(taxRate) },
    'Tax rate saved — applied automatically to new price entries from now on.',
  )

  const applyPreset = (id) => {
    const p = findPreset(id)
    setBrandPreset(id)
    if (id !== 'custom') {
      setBrandPrimary(p.primary)
      setBrandSecondary(p.secondary)
      setBrandAccent(p.accent)
    }
  }

  const handleLogoUpload = async (e) => {
    setLogoError(null)
    const file = e.target.files?.[0]
    if (!file) return
    if (file.size > 1_800_000) {
      setLogoError('Image is too large — please use a file under ~1.5MB.')
      return
    }
    const dataUrl = await fileToDataUrl(file)
    if (!dataUrl) {
      setLogoError('Could not read that file as an image.')
      return
    }
    setBrandLogo(dataUrl)
    setBrandPreset('custom')
  }

  const saveBranding = () => save({
    brand_preset: brandPreset,
    brand_primary_color: brandPrimary,
    brand_secondary_color: brandSecondary,
    brand_accent_color: brandAccent,
    brand_logo_data_url: brandLogo,
  }, 'Branding saved.')

  return (
    <div style={{
      position: 'fixed', inset: 0, background: '#00000099', zIndex: 100,
      display: 'flex', justifyContent: 'flex-end',
    }} onClick={onClose}>
      <div
        onClick={e => e.stopPropagation()}
        style={{
          width: 'min(420px, 100vw)', height: '100vh', overflowY: 'auto',
          background: 'var(--brand-surface-2, #161b27)', borderLeft: '1px solid var(--brand-border, #2d3348)',
          padding: '24px 22px', boxSizing: 'border-box',
        }}
      >
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 20 }}>
          <div style={{ fontWeight: 800, fontSize: 17, color: 'var(--brand-text, #e2e8f0)' }}>Settings</div>
          <button onClick={onClose} style={{
            background: 'none', border: 'none', color: 'var(--brand-text-dimmer, #64748b)', fontSize: 20, cursor: 'pointer',
          }}>×</button>
        </div>

        {!settings && <div style={{ color: 'var(--brand-text-dimmer, #64748b)', fontSize: 12 }}>Loading…</div>}

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

            <div style={{ borderTop: '1px solid var(--brand-border, #2d3348)', margin: '4px 0 20px' }} />

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

            <div style={{ borderTop: '1px solid var(--brand-border, #2d3348)', margin: '4px 0 20px' }} />

            {/* Device ID / cloud */}
            <div style={row}>
              <label style={label}>Device ID (hex, legacy)</label>
              <div style={hint}>
                Original placeholder display value, not used by anything active. Superseded by the
                real device credential in the Cloud sync section below.
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
              <label style={{ ...label, display: 'flex', alignItems: 'center', gap: 8, cursor: 'pointer' }}>
                <input
                  type="checkbox"
                  checked={cloudSyncEnabled}
                  onChange={e => setCloudSyncEnabled(e.target.checked)}
                />
                Cloud sync
              </label>
              <div style={hint}>
                Pushes this station's data to a cloud hub for remote/multi-station viewing.
                Fully optional — this station keeps working exactly as-is with it off. Get the
                URL and device credential from an admin (Admin → Stations → Provision in the
                cloud portal).
              </div>

              <div style={{ marginTop: 10 }}>
                <div style={{ fontSize: 10, color: 'var(--brand-text-dimmer, #64748b)', marginBottom: 3 }}>Cloud URL</div>
                <input
                  value={cloudSyncUrl}
                  onChange={e => setCloudSyncUrl(e.target.value)}
                  placeholder="https://your-cloud-host:8100"
                  style={inputStyle}
                />
              </div>

              <div style={{ marginTop: 10 }}>
                <div style={{ fontSize: 10, color: 'var(--brand-text-dimmer, #64748b)', marginBottom: 3 }}>Device ID</div>
                <input
                  value={cloudSyncDeviceId}
                  onChange={e => setCloudSyncDeviceId(e.target.value)}
                  placeholder="stn_…"
                  style={{ ...inputStyle, fontFamily: 'monospace' }}
                />
              </div>

              <div style={{ marginTop: 10 }}>
                <div style={{ fontSize: 10, color: 'var(--brand-text-dimmer, #64748b)', marginBottom: 3 }}>Device secret</div>
                <div style={{ display: 'flex', gap: 8 }}>
                  <input
                    type={showSecret ? 'text' : 'password'}
                    value={cloudSyncDeviceSecret}
                    onChange={e => setCloudSyncDeviceSecret(e.target.value)}
                    style={{ ...inputStyle, fontFamily: 'monospace', flex: 1 }}
                  />
                  <button style={btn(false)} onClick={() => setShowSecret(s => !s)}>
                    {showSecret ? 'Hide' : 'Show'}
                  </button>
                </div>
              </div>

              <div style={{ marginTop: 10 }}>
                <div style={{ fontSize: 10, color: 'var(--brand-text-dimmer, #64748b)', marginBottom: 3 }}>Sync interval (minutes)</div>
                <input
                  type="number" min={1} max={1440}
                  value={cloudSyncInterval}
                  onChange={e => setCloudSyncInterval(Number(e.target.value))}
                  style={inputStyle}
                />
                <div style={hint}>Default 30 — how often data is pushed. Doesn't need to match the poll interval.</div>
              </div>

              <button
                disabled={saving}
                style={{ ...btn(true), width: '100%', marginTop: 10 }}
                onClick={saveCloudSync}
              >
                Save cloud sync settings
              </button>

              <div style={{
                marginTop: 10, fontSize: 11, display: 'flex', alignItems: 'center', gap: 6,
              }}>
                <span style={{
                  width: 7, height: 7, borderRadius: '50%', display: 'inline-block',
                  background: settings.cloud_sync_last_synced_at ? '#22c55e' : 'var(--brand-text-faint, #475569)',
                }} />
                {settings.cloud_sync_last_synced_at
                  ? <span style={{ color: 'var(--brand-text-dim, #94a3b8)' }}>
                      Last synced to cloud {formatDistanceToNow(parseISO(settings.cloud_sync_last_synced_at), { addSuffix: true })}
                    </span>
                  : <span style={{ color: 'var(--brand-text-dimmer, #64748b)' }}>
                      {cloudSyncEnabled ? 'Not synced yet — first push happens within ~15s of saving.' : 'Never synced.'}
                    </span>}
              </div>
            </div>

            <div style={{ borderTop: '1px solid var(--brand-border, #2d3348)', margin: '4px 0 20px' }} />

            {/* Commander price sync */}
            <div style={row}>
              <label style={{ ...label, display: 'flex', alignItems: 'center', gap: 8, cursor: 'pointer' }}>
                <input
                  type="checkbox"
                  checked={commanderEnabled}
                  onChange={e => setCommanderEnabled(e.target.checked)}
                />
                Commander price sync
              </label>
              <div style={hint}>
                Pulls the live pump (sale) price hourly from a commander-reader instance in front
                of a Verifone Commander. Fully optional — if this station doesn't run Commander, or
                the operator won't allow the integration, leave this off and keep entering both cost
                and sale price manually via each tank's Pricing panel, exactly as before. Assign
                which Commander grade belongs to which tank below, once connected.
              </div>

              <div style={{ marginTop: 10 }}>
                <div style={{ fontSize: 10, color: 'var(--brand-text-dimmer, #64748b)', marginBottom: 3 }}>commander-reader URL</div>
                <input
                  value={commanderUrl}
                  onChange={e => setCommanderUrl(e.target.value)}
                  placeholder="http://<commander-reader-host>:8200"
                  style={inputStyle}
                />
              </div>

              <div style={{ display: 'flex', gap: 10, marginTop: 10 }}>
                <div style={{ flex: 1 }}>
                  <div style={{ fontSize: 10, color: 'var(--brand-text-dimmer, #64748b)', marginBottom: 3 }}>Price tier</div>
                  <select value={commanderTier} onChange={e => setCommanderTier(e.target.value)} style={inputStyle}>
                    <option value="cash">Cash</option>
                    <option value="credit">Credit</option>
                  </select>
                </div>
                <div style={{ flex: 1 }}>
                  <div style={{ fontSize: 10, color: 'var(--brand-text-dimmer, #64748b)', marginBottom: 3 }}>Sync interval (minutes)</div>
                  <input
                    type="number" min={1} max={1440}
                    value={commanderInterval}
                    onChange={e => setCommanderInterval(Number(e.target.value))}
                    style={inputStyle}
                  />
                </div>
              </div>
              <div style={hint}>Default 60 — how often the sale price is refreshed. Independent of the TLS poll interval above.</div>

              <button
                disabled={saving}
                style={{ ...btn(true), width: '100%', marginTop: 10 }}
                onClick={saveCommander}
              >
                Save Commander sync settings
              </button>

              <div style={{
                marginTop: 12, background: 'var(--brand-well, #111827)', border: '1px solid var(--brand-border, #2d3348)',
                borderRadius: 8, padding: '10px 12px',
              }}>
                <div style={{ fontSize: 10, color: 'var(--brand-text-dimmer, #64748b)', marginBottom: 6 }}>
                  Check it yourself, from the Docker host:
                </div>
                <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
                  <code style={{
                    flex: 1, fontFamily: 'monospace', fontSize: 11, color: 'var(--brand-text, #cbd5e1)',
                    background: 'var(--brand-surface-2, #0b0f19)', padding: '6px 8px', borderRadius: 6,
                    overflowX: 'auto', whiteSpace: 'nowrap',
                  }}>{commanderCurl}</code>
                  <button style={{ ...btn(false), padding: '6px 10px', fontSize: 11 }} onClick={copyCommanderCurl}>Copy</button>
                </div>
                <div style={{ fontSize: 10, color: 'var(--brand-text-dimmer, #64748b)', marginTop: 6 }}>
                  Should return <code>{'{"connected": true, ...}'}</code>. Useful if the button below says
                  unreachable but you suspect it's a Docker networking quirk rather than commander-reader
                  actually being down — the host machine and the containers don't always see the network
                  the same way.
                </div>
              </div>

              <button
                disabled={testingCommander || !commanderUrl}
                style={{ ...btn(false), width: '100%', marginTop: 10 }}
                onClick={handleTestCommander}
              >
                {testingCommander ? 'Testing…' : '⚡ Test connection now'}
              </button>

              {commanderTestResult && (
                <div style={{
                  marginTop: 8, fontSize: 11, padding: '8px 10px', borderRadius: 7,
                  background: commanderTestResult.connected ? '#052e16' : '#450a0a',
                  color: commanderTestResult.connected ? '#86efac' : '#fca5a5',
                }}>
                  {commanderTestResult.connected
                    ? `Connected — ${commanderTestResult.grades_count ?? '?'} grade(s) in the response.`
                    : (commanderTestResult.error || 'Could not connect.')}
                </div>
              )}

              {/* Grade assignment — modular: driven entirely by whatever tanks
                  exist and whatever grades this station's Commander actually
                  returns, never hardcoded to Unleaded/Super/Diesel or to a
                  fixed grade count. Lines up 1:1 with the same tanks the
                  Pricing panel shows margin for. */}
              {commanderGrades.length > 0 && (
                <div style={{
                  marginTop: 12, background: 'var(--brand-well, #111827)', border: '1px solid var(--brand-border, #2d3348)',
                  borderRadius: 8, padding: '10px 12px',
                }}>
                  <div style={{ fontSize: 11, fontWeight: 700, color: 'var(--brand-text-dim, #94a3b8)', marginBottom: 8 }}>
                    Assign grades to tanks
                  </div>
                  {(tanks ?? []).map(t => (
                    <div key={t.id} style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 6 }}>
                      <div style={{ flex: 1, fontSize: 12, color: 'var(--brand-text, #cbd5e1)' }}>{t.name}</div>
                      <select
                        value={gradeAssignments[t.id] ?? ''}
                        onChange={e => setGradeAssignments(g => ({ ...g, [t.id]: e.target.value }))}
                        style={{ ...inputStyle, flex: 2, padding: '5px 8px', fontSize: 12 }}
                      >
                        <option value="">— N/A (not connected) —</option>
                        {commanderGrades.map(g => (
                          <option key={g.id} value={g.id}>
                            {g.id} — {g.name}{g.cash != null ? ` — $${g.cash.toFixed(3)}` : ''}
                          </option>
                        ))}
                      </select>
                    </div>
                  ))}

                  <button
                    disabled={savingGrades || !gradesDirty}
                    style={{ ...btn(true), width: '100%', marginTop: 8, opacity: gradesDirty ? 1 : 0.4 }}
                    onClick={saveGradeAssignments}
                  >
                    Save grade assignments
                  </button>

                  <div style={{ fontSize: 10, color: 'var(--brand-text-dimmer, #64748b)', marginTop: 8 }}>
                    Unassigned grades (N/A):{' '}
                    {commanderGrades.filter(g => !assignedGradeIds.has(String(g.id))).length === 0
                      ? 'none'
                      : commanderGrades
                          .filter(g => !assignedGradeIds.has(String(g.id)))
                          .map(g => `${g.id} (${g.name})`)
                          .join(', ')}
                  </div>
                </div>
              )}

              <div style={{
                marginTop: 10, fontSize: 11, display: 'flex', alignItems: 'center', gap: 6,
              }}>
                <span style={{
                  width: 7, height: 7, borderRadius: '50%', display: 'inline-block',
                  background: settings.commander_last_connected ? '#22c55e'
                    : settings.commander_last_connected === false ? '#ef4444'
                    : 'var(--brand-text-faint, #475569)',
                }} />
                {settings.commander_last_check_at
                  ? <span style={{ color: 'var(--brand-text-dim, #94a3b8)' }}>
                      Last checked {formatDistanceToNow(parseISO(settings.commander_last_check_at), { addSuffix: true })}
                      {' — '}{settings.commander_last_connected ? 'connected' : (settings.commander_last_error || 'not connected')}
                    </span>
                  : <span style={{ color: 'var(--brand-text-dimmer, #64748b)' }}>Never checked yet.</span>}
              </div>
            </div>

            <div style={{ borderTop: '1px solid var(--brand-border, #2d3348)', margin: '4px 0 20px' }} />

            {/* Software updates — opt-in, independent of licensing (there is
                none on this side) and of cloud sync. See updater/README.md. */}
            <div style={row}>
              <label style={{ ...label, display: 'flex', alignItems: 'center', gap: 8, cursor: 'pointer' }}>
                <input
                  type="checkbox"
                  checked={updateCheckEnabled}
                  onChange={e => setUpdateCheckEnabled(e.target.checked)}
                />
                Check for software updates
              </label>
              <div style={hint}>
                Off by default. When on, a script on this station's host checks for new releases
                (git pull + rebuild) on the interval below — see updater/README.md for how to wire
                up the recurring check. Fully independent of Cloud sync and of any Cloud Utility
                license: this station can opt into free updates whether or not it's connected to a
                cloud hub at all.
              </div>

              <div style={{ marginTop: 10 }}>
                <div style={{ fontSize: 10, color: 'var(--brand-text-dimmer, #64748b)', marginBottom: 3 }}>Check interval (days)</div>
                <input
                  type="number" min={1} max={90}
                  value={updateCheckIntervalDays}
                  onChange={e => setUpdateCheckIntervalDays(Number(e.target.value))}
                  style={inputStyle}
                />
              </div>

              <button
                disabled={saving}
                style={{ ...btn(true), width: '100%', marginTop: 10 }}
                onClick={saveUpdateChecking}
              >
                Save update-check settings
              </button>

              <button
                disabled={checkingNow || !updateCheckEnabled}
                style={{ ...btn(false), width: '100%', marginTop: 8 }}
                onClick={handleCheckForUpdatesNow}
                title={!updateCheckEnabled ? 'Enable update checking above first' : undefined}
              >
                {checkingNow ? 'Requesting…' : '⚡ Check for updates now'}
              </button>

              <div style={{ marginTop: 10, fontSize: 11, color: 'var(--brand-text-dim, #94a3b8)' }}>
                {settings.update_current_ref && <div>Running: <code style={{ fontFamily: 'monospace' }}>{settings.update_current_ref}</code></div>}
                <div>
                  Last checked: {settings.update_last_checked_at
                    ? formatDistanceToNow(parseISO(settings.update_last_checked_at), { addSuffix: true })
                    : 'never'}
                  {settings.update_last_result ? ` — ${settings.update_last_result}` : ''}
                </div>
                {settings.update_last_applied_at && (
                  <div>Last updated: {formatDistanceToNow(parseISO(settings.update_last_applied_at), { addSuffix: true })}</div>
                )}
                {settings.update_check_pending && <div style={{ color: '#fde68a' }}>A check is queued for the updater's next run.</div>}
              </div>
            </div>

            <div style={{ borderTop: '1px solid var(--brand-border, #2d3348)', margin: '4px 0 20px' }} />

            {/* Tax rate */}
            <div style={row}>
              <label style={label}>Tax rate</label>
              <div style={hint}>
                Applied automatically to every new price entry — manual or Commander-synced — so
                it's set once here instead of typed into the Pricing panel every time.
              </div>
              <div style={{ display: 'flex', gap: 8, marginTop: 8 }}>
                <input
                  type="number" step="0.0001" min={0}
                  value={taxRate}
                  onChange={e => setTaxRate(e.target.value)}
                  placeholder="e.g. 9.75"
                  style={inputStyle}
                />
                <button
                  disabled={saving}
                  style={{ ...btn(true), padding: '8px 16px' }}
                  onClick={saveTaxRate}
                >
                  Save
                </button>
              </div>
            </div>

            <div style={{ borderTop: '1px solid var(--brand-border, #2d3348)', margin: '4px 0 20px' }} />

            {/* Branding */}
            <div style={row}>
              <label style={label}>Branding</label>
              <div style={hint}>
                Theme the dashboard with a preset's colors or your own — none of these bundled
                presets use a real brand's logo artwork; upload your own logo file below for that.
              </div>

              <div style={{ display: 'flex', alignItems: 'center', gap: 10, margin: '10px 0' }}>
                <BrandLogo logoDataUrl={brandLogo} size={40} />
                <div style={{ fontSize: 11, color: 'var(--brand-text-dimmer, #64748b)' }}>Preview</div>
              </div>

              <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, marginBottom: 10 }}>
                {BRAND_PRESETS.map(p => (
                  <button
                    key={p.id}
                    onClick={() => applyPreset(p.id)}
                    style={{
                      display: 'flex', alignItems: 'center', gap: 6, padding: '5px 8px',
                      borderRadius: 7, cursor: 'pointer', fontSize: 11,
                      border: brandPreset === p.id ? '1.5px solid var(--brand-primary, #3b82f6)' : '1px solid var(--brand-border-soft, #374151)',
                      background: brandPreset === p.id ? 'var(--brand-primary-soft, #0f1c33)' : 'transparent',
                      color: 'var(--brand-text, #cbd5e1)',
                    }}
                  >
                    <span style={{ display: 'flex' }}>
                      {[p.primary, p.secondary, p.accent].map((c, i) => (
                        <span key={i} style={{
                          width: 10, height: 10, borderRadius: '50%', background: c,
                          border: '1px solid #00000055', marginLeft: i > 0 ? -3 : 0,
                        }} />
                      ))}
                    </span>
                    {p.name}
                  </button>
                ))}
              </div>

              <div style={{ display: 'flex', gap: 10, marginBottom: 10 }}>
                <div style={{ flex: 1 }}>
                  <div style={{ fontSize: 10, color: 'var(--brand-text-dimmer, #64748b)', marginBottom: 3 }}>Primary</div>
                  <input type="color" value={brandPrimary}
                    onChange={e => { setBrandPrimary(e.target.value); setBrandPreset('custom') }}
                    style={{ width: '100%', height: 32, border: '1px solid var(--brand-border-soft, #374151)', borderRadius: 6, background: 'transparent' }} />
                </div>
                <div style={{ flex: 1 }}>
                  <div style={{ fontSize: 10, color: 'var(--brand-text-dimmer, #64748b)', marginBottom: 3 }}>Secondary</div>
                  <input type="color" value={brandSecondary}
                    onChange={e => { setBrandSecondary(e.target.value); setBrandPreset('custom') }}
                    style={{ width: '100%', height: 32, border: '1px solid var(--brand-border-soft, #374151)', borderRadius: 6, background: 'transparent' }} />
                </div>
                <div style={{ flex: 1 }}>
                  <div style={{ fontSize: 10, color: 'var(--brand-text-dimmer, #64748b)', marginBottom: 3 }}>Accent</div>
                  <input type="color" value={brandAccent}
                    onChange={e => { setBrandAccent(e.target.value); setBrandPreset('custom') }}
                    style={{ width: '100%', height: 32, border: '1px solid var(--brand-border-soft, #374151)', borderRadius: 6, background: 'transparent' }} />
                </div>
              </div>

              <div style={{ marginBottom: 10 }}>
                <div style={{ fontSize: 10, color: 'var(--brand-text-dimmer, #64748b)', marginBottom: 3 }}>Custom logo (optional)</div>
                <input type="file" accept="image/*" onChange={handleLogoUpload} style={{ fontSize: 11, color: 'var(--brand-text-dim, #94a3b8)' }} />
                {brandLogo && (
                  <button style={{ ...btn(false), marginLeft: 8, padding: '4px 8px', fontSize: 10 }}
                    onClick={() => setBrandLogo('')}>
                    Remove logo
                  </button>
                )}
                {logoError && <div style={{ color: '#fca5a5', fontSize: 11, marginTop: 4 }}>{logoError}</div>}
              </div>

              <button disabled={saving} style={{ ...btn(true), width: '100%' }} onClick={saveBranding}>
                Save branding
              </button>
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
