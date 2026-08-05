import React, { useState } from 'react'
import { useNavigate, useLocation } from 'react-router-dom'
import { useAuth } from '../context/AuthContext.jsx'

const DURATIONS = [
  { value: 'short', label: 'Until I sign out' },
  { value: '90d', label: 'Remember me for 90 days' },
  { value: 'never', label: 'Never expire' },
]

export default function LoginPage() {
  const { login } = useAuth()
  const navigate = useNavigate()
  const location = useLocation()
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [duration, setDuration] = useState('short')
  const [error, setError] = useState(null)
  const [busy, setBusy] = useState(false)

  const submit = async (e) => {
    e.preventDefault()
    setError(null)
    setBusy(true)
    try {
      await login(email, password, duration)
      navigate(location.state?.from ?? '/', { replace: true })
    } catch (err) {
      setError(err.message || 'Login failed')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div style={{
      minHeight: '100vh', display: 'flex', alignItems: 'center', justifyContent: 'center',
      background: '#0f1117', padding: 20,
    }}>
      <form onSubmit={submit} style={{
        width: 360, background: '#161b27', border: '1px solid #1e2130', borderRadius: 16,
        padding: 32, display: 'flex', flexDirection: 'column', gap: 16,
      }}>
        <div style={{ textAlign: 'center', marginBottom: 8 }}>
          <div style={{
            width: 44, height: 44, borderRadius: 12, margin: '0 auto 12px',
            background: 'linear-gradient(135deg,#3b82f6,#6366f1)',
            display: 'flex', alignItems: 'center', justifyContent: 'center',
            fontSize: 22, fontWeight: 800, color: '#fff',
          }}>T</div>
          <div style={{ fontWeight: 800, fontSize: 18 }}>TLS-Decoded Cloud</div>
          <div style={{ fontSize: 12, color: '#64748b', marginTop: 4 }}>Sign in to view your station(s)</div>
        </div>

        <Field label="Email">
          <input
            type="email" required value={email} onChange={e => setEmail(e.target.value)}
            style={inputStyle} autoFocus autoComplete="email"
          />
        </Field>

        <Field label="Password">
          <input
            type="password" required value={password} onChange={e => setPassword(e.target.value)}
            style={inputStyle} autoComplete="current-password"
          />
        </Field>

        <Field label="Stay signed in">
          <select value={duration} onChange={e => setDuration(e.target.value)} style={inputStyle}>
            {DURATIONS.map(d => <option key={d.value} value={d.value}>{d.label}</option>)}
          </select>
        </Field>

        {error && (
          <div style={{
            background: '#450a0a', border: '1px solid #ef4444', borderRadius: 8,
            padding: '8px 12px', color: '#fca5a5', fontSize: 12,
          }}>{error}</div>
        )}

        <button type="submit" disabled={busy} style={{
          background: 'linear-gradient(135deg,#3b82f6,#6366f1)', border: 'none', borderRadius: 10,
          padding: '12px', color: '#fff', fontWeight: 700, fontSize: 14,
          cursor: busy ? 'default' : 'pointer', opacity: busy ? 0.7 : 1, marginTop: 4,
        }}>
          {busy ? 'Signing in…' : 'Sign in'}
        </button>
      </form>
    </div>
  )
}

function Field({ label, children }) {
  return (
    <label style={{ display: 'flex', flexDirection: 'column', gap: 6, fontSize: 12, color: '#94a3b8' }}>
      {label}
      {children}
    </label>
  )
}

const inputStyle = {
  background: '#0f1117', border: '1px solid #2d3348', borderRadius: 8,
  padding: '10px 12px', color: '#e2e8f0', fontSize: 14, outline: 'none',
}
