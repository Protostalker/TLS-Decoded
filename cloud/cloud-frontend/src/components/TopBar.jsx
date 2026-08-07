import React from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { useAuth } from '../context/AuthContext.jsx'
import BrandLogo from './BrandLogo.jsx'

// logoDataUrl is only ever passed by StationDashboardPage (T1) — every other
// caller (T2 station list, Admin, Login) renders the default gradient badge
// since --brand-* CSS vars are unset there. See brandTheme.js for scoping.
export default function TopBar({ title, backTo, logoDataUrl }) {
  const { user, logout } = useAuth()
  const navigate = useNavigate()

  return (
    <header style={{
      background: 'var(--brand-surface-2, #161b27)', borderBottom: '1px solid var(--brand-border-soft, #1e2130)',
      padding: '0 24px', height: 60,
      display: 'flex', alignItems: 'center', justifyContent: 'space-between',
    }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 14 }}>
        {backTo && (
          <Link to={backTo} style={{
            color: 'var(--brand-text-dimmer, #64748b)', textDecoration: 'none', fontSize: 13, marginRight: 4,
          }}>← Back</Link>
        )}
        <BrandLogo logoDataUrl={logoDataUrl} size={32} />
        <div>
          <div style={{ fontWeight: 800, fontSize: 16, letterSpacing: -0.3, color: 'var(--brand-text, #e2e8f0)' }}>
            {title ?? 'TLS-Decoded Cloud'}
          </div>
          <div style={{ fontSize: 10, color: 'var(--brand-text-faint, #475569)' }}>Fuel Tank Monitor</div>
        </div>
      </div>

      {user && (
        <div style={{ display: 'flex', alignItems: 'center', gap: 16, fontSize: 12 }}>
          {user.role === 'admin' && (
            <Link to="/admin" style={{ color: '#93c5fd', textDecoration: 'none' }}>Admin</Link>
          )}
          <Link to="/" style={{ color: '#93c5fd', textDecoration: 'none' }}>Stations</Link>
          <span style={{ color: 'var(--brand-text-dimmer, #64748b)' }}>{user.email}</span>
          <button
            onClick={async () => { await logout(); navigate('/login') }}
            style={{
              background: 'var(--brand-surface, #1e2130)', border: '1px solid var(--brand-border, #2d3348)', borderRadius: 8,
              padding: '6px 12px', cursor: 'pointer', color: 'var(--brand-text-dim, #94a3b8)', fontSize: 12,
            }}
          >Sign out</button>
        </div>
      )}
    </header>
  )
}
