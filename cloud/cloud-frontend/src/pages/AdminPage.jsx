import React, { useEffect, useState } from 'react'
import { api } from '../api/client.js'
import TopBar from '../components/TopBar.jsx'
import StalenessBadge from '../components/StalenessBadge.jsx'
import Footer from '../components/Footer.jsx'

const TABS = ['Customers', 'Stations', 'Users', 'License']

export default function AdminPage() {
  const [tab, setTab] = useState('Customers')

  return (
    <div style={{ minHeight: '100vh', background: '#0f1117' }}>
      <TopBar title="Admin — T3" backTo="/" />
      <main style={{ padding: 24, maxWidth: 1100, margin: '0 auto' }}>
        <div style={{ display: 'flex', gap: 8, marginBottom: 20 }}>
          {TABS.map(t => (
            <button key={t} onClick={() => setTab(t)} style={{
              background: tab === t ? '#3b82f6' : '#161b27',
              border: '1px solid #1e2130', borderRadius: 8, padding: '8px 16px',
              color: tab === t ? '#fff' : '#94a3b8', fontSize: 13, cursor: 'pointer', fontWeight: 600,
            }}>{t}</button>
          ))}
        </div>

        {tab === 'Customers' && <CustomersTab />}
        {tab === 'Stations' && <StationsTab />}
        {tab === 'Users' && <UsersTab />}
        {tab === 'License' && <LicenseTab />}
      </main>
      <Footer />
    </div>
  )
}

const card = { background: '#161b27', border: '1px solid #1e2130', borderRadius: 14, padding: 18, marginBottom: 16 }
const inputStyle = {
  background: '#0f1117', border: '1px solid #2d3348', borderRadius: 8,
  padding: '8px 10px', color: '#e2e8f0', fontSize: 13, outline: 'none',
}
const btn = {
  background: '#3b82f6', border: 'none', borderRadius: 8, padding: '8px 14px',
  color: '#fff', fontSize: 13, fontWeight: 600, cursor: 'pointer',
}
const btnGhost = {
  background: 'transparent', border: '1px solid #2d3348', borderRadius: 8, padding: '6px 10px',
  color: '#94a3b8', fontSize: 12, cursor: 'pointer',
}
const th = { padding: '8px 10px', fontWeight: 600, color: '#64748b', textAlign: 'left', fontSize: 11 }
const td = { padding: '8px 10px', fontSize: 13 }

// ── Customers ─────────────────────────────────────────────────────────────

function CustomersTab() {
  const [customers, setCustomers] = useState(null)
  const [name, setName] = useState('')
  const [error, setError] = useState(null)

  const load = () => { api.admin.customers().then(setCustomers).catch(e => setError(e.message)) }
  useEffect(load, [])

  const create = async (e) => {
    e.preventDefault()
    setError(null)
    try {
      await api.admin.createCustomer({ name })
      setName('')
      load()
    } catch (e) { setError(e.message) }
  }

  return (
    <div>
      <form onSubmit={create} style={{ ...card, display: 'flex', gap: 10, alignItems: 'flex-end' }}>
        <Field label="New customer name">
          <input required value={name} onChange={e => setName(e.target.value)} style={inputStyle} />
        </Field>
        <button type="submit" style={btn}>Create</button>
      </form>

      {error && <ErrorBox message={error} />}

      <div style={card}>
        <div style={{ overflowX: 'auto' }}>
          <table style={{ width: '100%', borderCollapse: 'collapse', minWidth: 400 }}>
            <thead><tr><th style={th}>Name</th><th style={th}>Stations</th><th style={th}>Users</th><th style={th}>Created</th></tr></thead>
            <tbody>
              {customers?.map(c => (
                <tr key={c.id} style={{ borderTop: '1px solid #1e2130' }}>
                  <td style={td}>{c.name}</td>
                  <td style={td}>{c.station_count}</td>
                  <td style={td}>{c.user_count}</td>
                  <td style={{ ...td, color: '#64748b' }}>{new Date(c.created_at).toLocaleDateString()}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {customers?.length === 0 && <div style={{ color: '#475569', padding: 12, fontSize: 12 }}>No customers yet.</div>}
      </div>
    </div>
  )
}

// ── Stations ──────────────────────────────────────────────────────────────

function StationsTab() {
  const [stations, setStations] = useState(null)
  const [customers, setCustomers] = useState(null)
  const [form, setForm] = useState({ customer_id: '', name: '', sync_interval_minutes: 30, zip_code: '', timezone: '' })
  const [error, setError] = useState(null)
  const [newCredential, setNewCredential] = useState(null)

  const load = () => {
    api.admin.stations().then(setStations).catch(e => setError(e.message))
    api.admin.customers().then(setCustomers).catch(() => {})
  }
  useEffect(load, [])

  const create = async (e) => {
    e.preventDefault()
    setError(null)
    try {
      const cred = await api.admin.createStation({
        customer_id: Number(form.customer_id), name: form.name,
        sync_interval_minutes: Number(form.sync_interval_minutes) || 30,
        zip_code: form.zip_code || null,
        timezone: form.timezone || null,
      })
      setNewCredential(cred)
      setForm({ customer_id: '', name: '', sync_interval_minutes: 30, zip_code: '', timezone: '' })
      load()
    } catch (e) { setError(e.message) }
  }

  const saveZip = async (station, zip) => {
    setError(null)
    try {
      await api.admin.updateStation(station.id, { zip_code: zip })
      load()
    } catch (e) { setError(e.message) }
  }

  const saveTimezone = async (station, tz) => {
    setError(null)
    try {
      await api.admin.updateStation(station.id, { timezone: tz })
      load()
    } catch (e) { setError(e.message) }
  }

  const rotate = async (id) => {
    setError(null)
    try {
      const cred = await api.admin.rotateCredential(id)
      setNewCredential(cred)
    } catch (e) { setError(e.message) }
  }

  const toggleActive = async (s) => {
    await api.admin.updateStation(s.id, { active: !s.active })
    load()
  }

  const [checkRequested, setCheckRequested] = useState({})
  const requestUpdateCheck = async (id) => {
    setError(null)
    try {
      await api.admin.requestUpdateCheck(id)
      setCheckRequested(prev => ({ ...prev, [id]: true }))
      load()
    } catch (e) { setError(e.message) }
  }

  return (
    <div>
      <form onSubmit={create} style={{ ...card, display: 'flex', gap: 10, alignItems: 'flex-end', flexWrap: 'wrap' }}>
        <Field label="Customer">
          <select required value={form.customer_id} onChange={e => setForm({ ...form, customer_id: e.target.value })} style={inputStyle}>
            <option value="">Select…</option>
            {customers?.map(c => <option key={c.id} value={c.id}>{c.name}</option>)}
          </select>
        </Field>
        <Field label="Station name">
          <input required value={form.name} onChange={e => setForm({ ...form, name: e.target.value })} style={inputStyle} placeholder="e.g. Gardena #1" />
        </Field>
        <Field label="Sync interval (min)">
          <input type="number" min="1" value={form.sync_interval_minutes}
                 onChange={e => setForm({ ...form, sync_interval_minutes: e.target.value })} style={{ ...inputStyle, width: 90 }} />
        </Field>
        <Field label="Zip (optional — for weather)">
          <input value={form.zip_code} onChange={e => setForm({ ...form, zip_code: e.target.value })}
                 style={{ ...inputStyle, width: 100 }} placeholder="90248" />
        </Field>
        <Field label="Timezone (for 'today' math)">
          <input value={form.timezone} onChange={e => setForm({ ...form, timezone: e.target.value })}
                 style={{ ...inputStyle, width: 170 }} placeholder="America/Los_Angeles" />
        </Field>
        <button type="submit" style={btn}>Provision station</button>
      </form>

      {error && <ErrorBox message={error} />}

      {newCredential && (
        <div style={{
          ...card, border: '1px solid #3b82f6', background: '#0f1c33',
        }}>
          <div style={{ fontWeight: 700, marginBottom: 8, color: '#93c5fd' }}>
            Device credential — shown once, copy it now
          </div>
          <div style={{ fontSize: 12, color: '#94a3b8', marginBottom: 8 }}>
            Enter these into the station's sync service config (CLOUD_INGEST_URL / STATION_DEVICE_ID / STATION_DEVICE_SECRET
            env vars in docker-compose.yml). This secret cannot be retrieved again — only rotated.
          </div>
          <CredentialRow label="Station ID" value={newCredential.station_id} />
          <CredentialRow label="Device ID" value={newCredential.device_id} />
          <CredentialRow label="Device secret" value={newCredential.device_secret} />
          <button onClick={() => setNewCredential(null)} style={{ ...btnGhost, marginTop: 8 }}>Dismiss</button>
        </div>
      )}

      <div style={card}>
        <div style={{ overflowX: 'auto' }}>
          <table style={{ width: '100%', borderCollapse: 'collapse', minWidth: 700 }}>
            <thead>
              <tr>
                <th style={th}>Name</th><th style={th}>Customer</th><th style={th}>Sync interval</th>
                <th style={th}>Zip</th><th style={th}>Timezone</th><th style={th}>Last sync</th><th style={th}>Status</th><th style={th}></th>
              </tr>
            </thead>
            <tbody>
              {stations?.map(s => (
                <tr key={s.id} style={{ borderTop: '1px solid #1e2130' }}>
                  <td style={td}>{s.name}</td>
                  <td style={td}>{s.customer_name}</td>
                  <td style={td}>{s.sync_interval_minutes} min</td>
                  <td style={td}><ZipEditor station={s} onSave={saveZip} /></td>
                  <td style={td}><TimezoneEditor station={s} onSave={saveTimezone} /></td>
                  <td style={td}><StalenessBadge lastSyncAt={s.last_sync_at} label="synced" /></td>
                  <td style={td}>{s.active ? <span style={{ color: '#86efac' }}>active</span> : <span style={{ color: '#fca5a5' }}>inactive</span>}</td>
                  <td style={{ ...td, display: 'flex', gap: 6, flexWrap: 'wrap' }}>
                    <button onClick={() => rotate(s.id)} style={btnGhost}>Rotate credential</button>
                    <button onClick={() => toggleActive(s)} style={btnGhost}>{s.active ? 'Deactivate' : 'Activate'}</button>
                    <button
                      onClick={() => requestUpdateCheck(s.id)}
                      disabled={!!checkRequested[s.id]}
                      title="Only takes effect if this station has 'Check for software updates' enabled locally — see its own Settings page."
                      style={btnGhost}
                    >
                      {checkRequested[s.id] ? 'Update check requested' : 'Check for updates'}
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {stations?.length === 0 && <div style={{ color: '#475569', padding: 12, fontSize: 12 }}>No stations provisioned yet.</div>}
      </div>
    </div>
  )
}

function ZipEditor({ station, onSave }) {
  const [value, setValue] = useState(station.zip_code || '')
  const [saving, setSaving] = useState(false)
  const dirty = value !== (station.zip_code || '')

  const save = async () => {
    setSaving(true)
    try { await onSave(station, value) } finally { setSaving(false) }
  }

  return (
    <div style={{ display: 'flex', gap: 4, alignItems: 'center' }}>
      <input
        value={value}
        onChange={e => setValue(e.target.value)}
        placeholder="90248"
        style={{ ...inputStyle, width: 70, padding: '4px 6px', fontSize: 11 }}
      />
      {dirty && (
        <button onClick={save} disabled={saving} style={{ ...btnGhost, padding: '3px 8px', fontSize: 10 }}>
          Save
        </button>
      )}
    </div>
  )
}

function TimezoneEditor({ station, onSave }) {
  const [value, setValue] = useState(station.timezone || '')
  const [saving, setSaving] = useState(false)
  const dirty = value !== (station.timezone || '')

  const save = async () => {
    setSaving(true)
    try { await onSave(station, value) } finally { setSaving(false) }
  }

  return (
    <div style={{ display: 'flex', gap: 4, alignItems: 'center' }}>
      <input
        value={value}
        onChange={e => setValue(e.target.value)}
        placeholder="America/Los_Angeles"
        style={{ ...inputStyle, width: 150, padding: '4px 6px', fontSize: 11 }}
      />
      {dirty && (
        <button onClick={save} disabled={saving} style={{ ...btnGhost, padding: '3px 8px', fontSize: 10 }}>
          Save
        </button>
      )}
    </div>
  )
}

function CredentialRow({ label, value }) {
  return (
    <div style={{ display: 'flex', gap: 10, alignItems: 'center', fontSize: 12, marginBottom: 4 }}>
      <span style={{ color: '#64748b', width: 100 }}>{label}</span>
      <code style={{
        background: '#0f1117', border: '1px solid #2d3348', borderRadius: 6,
        padding: '4px 8px', color: '#e2e8f0', fontFamily: 'monospace', wordBreak: 'break-all',
      }}>{value}</code>
    </div>
  )
}

// ── Users ─────────────────────────────────────────────────────────────────

function UsersTab() {
  const [users, setUsers] = useState(null)
  const [customers, setCustomers] = useState(null)
  const [stations, setStations] = useState(null)
  const [form, setForm] = useState({ email: '', password: '', role: 'user', customer_id: '' })
  const [error, setError] = useState(null)
  const [expandedUser, setExpandedUser] = useState(null)

  const load = () => {
    api.admin.users().then(setUsers).catch(e => setError(e.message))
    api.admin.customers().then(setCustomers).catch(() => {})
    api.admin.stations().then(setStations).catch(() => {})
  }
  useEffect(load, [])

  const create = async (e) => {
    e.preventDefault()
    setError(null)
    try {
      await api.admin.createUser({
        email: form.email, password: form.password, role: form.role,
        customer_id: form.customer_id ? Number(form.customer_id) : null,
      })
      setForm({ email: '', password: '', role: 'user', customer_id: '' })
      load()
    } catch (e) { setError(e.message) }
  }

  const toggleActive = async (u) => { await api.admin.updateUser(u.id, { active: !u.active }); load() }

  return (
    <div>
      <form onSubmit={create} style={{ ...card, display: 'flex', gap: 10, alignItems: 'flex-end', flexWrap: 'wrap' }}>
        <Field label="Email">
          <input type="email" required value={form.email} onChange={e => setForm({ ...form, email: e.target.value })} style={inputStyle} />
        </Field>
        <Field label="Password">
          <input type="password" required value={form.password} onChange={e => setForm({ ...form, password: e.target.value })} style={inputStyle} />
        </Field>
        <Field label="Role">
          <select value={form.role} onChange={e => setForm({ ...form, role: e.target.value })} style={inputStyle}>
            <option value="user">user</option>
            <option value="admin">admin</option>
            <option value="supplier">supplier</option>
          </select>
        </Field>
        <Field label="Customer">
          <select value={form.customer_id} onChange={e => setForm({ ...form, customer_id: e.target.value })} style={inputStyle}>
            <option value="">—</option>
            {customers?.map(c => <option key={c.id} value={c.id}>{c.name}</option>)}
          </select>
        </Field>
        <button type="submit" style={btn}>Create user</button>
      </form>

      {error && <ErrorBox message={error} />}

      <div style={card}>
        <div style={{ overflowX: 'auto' }}>
          <table style={{ width: '100%', borderCollapse: 'collapse', minWidth: 560 }}>
            <thead>
              <tr>
                <th style={th}>Email</th><th style={th}>Role</th><th style={th}>Customer</th>
                <th style={th}>Status</th><th style={th}>Stations</th><th style={th}></th>
              </tr>
            </thead>
            <tbody>
              {users?.map(u => (
                <React.Fragment key={u.id}>
                  <tr style={{ borderTop: '1px solid #1e2130' }}>
                    <td style={td}>{u.email}</td>
                    <td style={td}>{u.role}</td>
                    <td style={td}>{u.customer_name ?? '—'}</td>
                    <td style={td}>{u.active ? <span style={{ color: '#86efac' }}>active</span> : <span style={{ color: '#fca5a5' }}>disabled</span>}</td>
                    <td style={td}>{u.assigned_station_ids.length}</td>
                    <td style={{ ...td, display: 'flex', gap: 6 }}>
                      <button onClick={() => setExpandedUser(expandedUser === u.id ? null : u.id)} style={btnGhost}>
                        {expandedUser === u.id ? 'Close' : 'Manage'}
                      </button>
                      <button onClick={() => toggleActive(u)} style={btnGhost}>{u.active ? 'Disable' : 'Enable'}</button>
                    </td>
                  </tr>
                  {expandedUser === u.id && (
                    <tr>
                      <td colSpan={6} style={{ padding: 0 }}>
                        <UserDetail user={u} stations={stations} onChange={load} />
                      </td>
                    </tr>
                  )}
                </React.Fragment>
              ))}
            </tbody>
          </table>
        </div>
        {users?.length === 0 && <div style={{ color: '#475569', padding: 12, fontSize: 12 }}>No users yet.</div>}
      </div>
    </div>
  )
}

function SetPasswordForm({ userId }) {
  const [pw, setPw] = useState('')
  const [confirm, setConfirm] = useState('')
  const [saving, setSaving] = useState(false)
  const [msg, setMsg] = useState(null)   // { text, ok }

  const submit = async (e) => {
    e.preventDefault()
    setMsg(null)
    if (pw !== confirm) { setMsg({ text: 'Passwords do not match', ok: false }); return }
    setSaving(true)
    try {
      await api.admin.setUserPassword(userId, pw)
      setPw(''); setConfirm('')
      setMsg({ text: 'Password updated', ok: true })
    } catch (e) {
      setMsg({ text: e.message, ok: false })
    } finally {
      setSaving(false)
    }
  }

  return (
    <form onSubmit={submit} style={{ marginTop: 16 }}>
      <div style={{ fontSize: 12, fontWeight: 700, color: '#94a3b8', marginBottom: 8 }}>Set password</div>
      <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', alignItems: 'flex-end' }}>
        <input
          type="password" required minLength={8}
          placeholder="New password (≥8 chars)"
          value={pw} onChange={e => setPw(e.target.value)}
          style={{ ...inputStyle, minWidth: 180 }}
        />
        <input
          type="password" required
          placeholder="Confirm password"
          value={confirm} onChange={e => setConfirm(e.target.value)}
          style={{ ...inputStyle, minWidth: 180 }}
        />
        <button type="submit" disabled={saving} style={{ ...btn, minHeight: 44 }}>
          {saving ? 'Saving…' : 'Set password'}
        </button>
      </div>
      {msg && (
        <div style={{ fontSize: 11, marginTop: 6, color: msg.ok ? '#86efac' : '#fca5a5' }}>{msg.text}</div>
      )}
    </form>
  )
}

function UserDetail({ user, stations, onChange }) {
  const [sessions, setSessions] = useState(null)
  const [pickStation, setPickStation] = useState('')

  const loadSessions = () => { api.admin.userSessions(user.id).then(setSessions).catch(() => {}) }
  useEffect(loadSessions, [user.id])

  const assign = async () => {
    if (!pickStation) return
    await api.admin.createAssignment(user.id, Number(pickStation))
    setPickStation('')
    onChange()
  }

  const unassign = async (stationId) => {
    await api.admin.deleteAssignment(user.id, stationId)
    onChange()
  }

  const revokeAll = async () => { await api.admin.revokeAllUserSessions(user.id); loadSessions() }
  const revokeOne = async (id) => { await api.admin.revokeSession(id); loadSessions() }

  const assignedStations = stations?.filter(s => user.assigned_station_ids.includes(s.id)) ?? []
  const availableStations = stations?.filter(s => !user.assigned_station_ids.includes(s.id)) ?? []

  return (
    <div style={{ background: '#0f1117', padding: 18 }}>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(260px, 1fr))', gap: 20, marginBottom: 0 }}>
        <div>
          <div style={{ fontSize: 12, fontWeight: 700, color: '#94a3b8', marginBottom: 10 }}>Station assignments</div>
          {assignedStations.map(s => (
            <div key={s.id} style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', fontSize: 12, padding: '6px 0', borderBottom: '1px solid #1e2130' }}>
              <span>{s.name} <span style={{ color: '#64748b' }}>({s.customer_name})</span></span>
              <button onClick={() => unassign(s.id)} style={btnGhost}>Remove</button>
            </div>
          ))}
          {assignedStations.length === 0 && <div style={{ color: '#475569', fontSize: 12 }}>No stations assigned.</div>}
          <div style={{ display: 'flex', gap: 8, marginTop: 10 }}>
            <select value={pickStation} onChange={e => setPickStation(e.target.value)} style={{ ...inputStyle, flex: 1 }}>
              <option value="">Assign a station…</option>
              {availableStations.map(s => <option key={s.id} value={s.id}>{s.name}</option>)}
            </select>
            <button onClick={assign} style={btn}>Assign</button>
          </div>
        </div>

        <div>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 10 }}>
            <div style={{ fontSize: 12, fontWeight: 700, color: '#94a3b8' }}>Sessions</div>
            <button onClick={revokeAll} style={btnGhost}>Revoke all</button>
          </div>
          {sessions?.map(s => (
            <div key={s.id} style={{ fontSize: 11, padding: '6px 0', borderBottom: '1px solid #1e2130' }}>
              <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                <span style={{ color: s.revoked_at ? '#64748b' : '#e2e8f0' }}>
                  {s.user_agent || 'unknown device'} · {s.ip_address || '—'}
                </span>
                {!s.revoked_at && <button onClick={() => revokeOne(s.id)} style={btnGhost}>Revoke</button>}
              </div>
              <div style={{ color: '#475569', marginTop: 2 }}>
                last used {s.last_used_at ? new Date(s.last_used_at).toLocaleString() : '—'} ·{' '}
                expires {s.expires_at ? new Date(s.expires_at).toLocaleDateString() : 'never'}
                {s.revoked_at && <span style={{ color: '#fca5a5' }}> · revoked</span>}
              </div>
            </div>
          ))}
          {sessions?.length === 0 && <div style={{ color: '#475569', fontSize: 12 }}>No sessions.</div>}
        </div>
      </div>

      <SetPasswordForm userId={user.id} />
    </div>
  )
}

// ── Shared bits ───────────────────────────────────────────────────────────

// ── License ───────────────────────────────────────────────────────────────
//
// Admin-only page per the dev handoff doc's open-question answer: "admin
// users will also have access to a license page, where it says when they
// applied the license, and when it expires, and if they are in grace mode."

const STATUS_COLOR = {
  active: '#86efac', grace: '#fde68a', degraded: '#fca5a5', unconfigured: '#64748b',
}

function LicenseTab() {
  const [status, setStatus] = useState(null)
  const [config, setConfig] = useState(null)
  const [error, setError] = useState(null)
  const [rechecking, setRechecking] = useState(false)

  const load = () => {
    api.license.status().then(setStatus).catch(e => setError(e.message))
    api.license.config().then(setConfig).catch(() => {})
  }
  useEffect(load, [])

  const recheck = async () => {
    setRechecking(true)
    setError(null)
    try {
      const s = await api.license.recheck()
      setStatus(s)
    } catch (e) { setError(e.message) }
    finally { setRechecking(false) }
  }

  if (!status) return error ? <ErrorBox message={error} /> : null

  const fmt = (d) => d ? new Date(d).toLocaleString() : '—'

  return (
    <div>
      {error && <ErrorBox message={error} />}

      <div style={card}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 14 }}>
          <span style={{
            display: 'inline-block', padding: '4px 12px', borderRadius: 999, fontSize: 12, fontWeight: 700,
            color: '#0f1117', background: STATUS_COLOR[status.status] || '#64748b',
          }}>
            {status.status.toUpperCase()}
          </span>
          <span style={{ color: '#94a3b8', fontSize: 13 }}>
            {status.customer_name || 'No license configured'}
          </span>
          <button onClick={recheck} disabled={rechecking} style={{ ...btnGhost, marginLeft: 'auto' }}>
            {rechecking ? 'Checking…' : 'Re-check now'}
          </button>
        </div>

        {status.status === 'degraded' && (
          <div style={{
            background: '#450a0a', border: '1px solid #7f1d1d', borderRadius: 10, padding: 12, marginBottom: 14,
            color: '#fecaca', fontSize: 13,
          }}>
            Degraded mode — only admins can see data right now. Non-admin users and suppliers see nothing until this
            is resolved. Activate a valid license below, then click "Re-check now" — full functionality returns
            immediately, no data is lost.
          </div>
        )}
        {status.status === 'grace' && (
          <div style={{
            background: '#451a03', border: '1px solid #92400e', borderRadius: 10, padding: 12, marginBottom: 14,
            color: '#fde68a', fontSize: 13,
          }}>
            License check is currently failing — {status.grace_days_remaining ?? '?'} of {status.grace_days_total} grace
            day(s) remaining before this account enters degraded mode.
          </div>
        )}

        <table style={{ width: '100%', borderCollapse: 'collapse' }}>
          <tbody>
            <Row label="Customer" value={status.customer_name || '—'} />
            <Row label="Station scope" value={status.station_scope || '—'} />
            <Row label="Applied (activated)" value={fmt(status.activated_at)} />
            <Row label="Expires" value={status.expires_at ? fmt(status.expires_at) : 'Never'} />
            <Row label="Last check" value={fmt(status.last_check_at)} />
            <Row label="Last check result" value={status.last_check_detail || (status.last_check_ok ? 'OK' : '—')} />
          </tbody>
        </table>
      </div>

      <LicenseActivationCard config={config} onChanged={load} />
    </div>
  )
}

// Submit/replace/clear the license passphrase from here — CLOUD_LICENSE_KEY
// only ever seeds this once, on a brand new deployment with an empty
// database; every change after that (activating, switching to a new code)
// goes through this form. One passphrase, phoned home to the license
// server — no keys, no files.
function LicenseActivationCard({ config, onChanged }) {
  const [passphrase, setPassphrase] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [msg, setMsg] = useState(null)

  const activate = async (e) => {
    e.preventDefault()
    setMsg(null)
    setSubmitting(true)
    try {
      await api.license.activate(passphrase.trim())
      setPassphrase('')
      setMsg({ type: 'ok', text: 'License activated.' })
      onChanged()
    } catch (e) { setMsg({ type: 'error', text: e.message }) }
    finally { setSubmitting(false) }
  }

  const deactivate = async () => {
    if (!confirm('Clear the configured license? This account goes back to "unconfigured" until a new one is activated.')) return
    setSubmitting(true)
    setMsg(null)
    try {
      await api.license.deactivate()
      setMsg({ type: 'ok', text: 'License cleared.' })
      onChanged()
    } catch (e) { setMsg({ type: 'error', text: e.message }) }
    finally { setSubmitting(false) }
  }

  return (
    <div style={card}>
      <div style={{ fontWeight: 700, marginBottom: 4 }}>
        {config?.configured ? 'Replace license' : 'Activate a license'}
      </div>
      <div style={{ fontSize: 12, color: '#64748b', marginBottom: 14 }}>
        {config?.configured
          ? `Currently configured: passphrase ending …${config.passphrase_hint || '????'}.`
          : 'No license configured yet.'}
        {' '}Enter a passphrase below to activate or replace it — no env var edits or restart needed. Env vars
        only seed this once, on a fresh deployment.
      </div>

      <form onSubmit={activate}>
        <Field label="License passphrase">
          <input
            required value={passphrase} onChange={e => setPassphrase(e.target.value)}
            placeholder="e.g. GARDENA-2026" style={{ ...inputStyle, width: '100%', fontFamily: 'monospace' }}
          />
        </Field>

        <div style={{ display: 'flex', gap: 8, marginTop: 12 }}>
          <button type="submit" disabled={submitting} style={btn}>
            {submitting ? 'Activating…' : 'Activate'}
          </button>
          {config?.configured && (
            <button type="button" onClick={deactivate} disabled={submitting} style={btnGhost}>
              Clear configured license
            </button>
          )}
        </div>
      </form>

      {msg && (
        <div style={{
          marginTop: 10, fontSize: 12, padding: '8px 10px', borderRadius: 7,
          background: msg.type === 'ok' ? '#052e16' : '#450a0a',
          color: msg.type === 'ok' ? '#86efac' : '#fca5a5',
        }}>
          {msg.text}
        </div>
      )}
    </div>
  )
}

function Row({ label, value }) {
  return (
    <tr style={{ borderTop: '1px solid #1e2130' }}>
      <td style={{ ...td, color: '#64748b', width: 200 }}>{label}</td>
      <td style={td}>{value}</td>
    </tr>
  )
}

function Field({ label, children }) {
  return (
    <label style={{ display: 'flex', flexDirection: 'column', gap: 4, fontSize: 11, color: '#94a3b8' }}>
      {label}
      {children}
    </label>
  )
}

function ErrorBox({ message }) {
  return (
    <div style={{
      background: '#450a0a', border: '1px solid #ef4444', borderRadius: 10,
      padding: '10px 14px', color: '#fca5a5', fontSize: 12, marginBottom: 16,
    }}>{message}</div>
  )
}
