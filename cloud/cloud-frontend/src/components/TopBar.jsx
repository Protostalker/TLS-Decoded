import React from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { useAuth } from '../context/AuthContext.jsx'

export default function TopBar({ title, backTo }) {
  const { user, logout } = useAuth()
  const navigate = useNavigate()

  return (
    <header style={{
      background: '#161b27', borderBottom: '1px solid #1e2130',
      padding: '0 24px', height: 60,
      display: 'flex', alignItems: 'center', justifyContent: 'space-between',
    }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 14 }}>
        {backTo && (
          <Link to={backTo} style={{
            color: '#64748b', textDecoration: 'none', fontSize: 13, marginRight: 4,
          }}>← Back</Link>
        )}
        <div style={{
          width: 32, height: 32, borderRadius: 8,
          background: 'linear-gradient(135deg,#3b82f6,#6366f1)',
          display: 'flex', alignItems: 'center', justifyContent: 'center',
          fontSize: 18, fontWeight: 800, color: '#fff',
        }}>T</div>
        <div>
          <div style={{ fontWeight: 800, fontSize: 16, letterSpacing: -0.3 }}>
            {title ?? 'TLS-Decoded Cloud'}
          </div>
          <div style={{ fontSize: 10, color: '#475569' }}>Fuel Tank Monitor</div>
        </div>
      </div>

      {user && (
        <div style={{ display: 'flex', alignItems: 'center', gap: 16, fontSize: 12 }}>
          {user.role === 'admin' && (
            <Link to="/admin" style={{ color: '#93c5fd', textDecoration: 'none' }}>Admin</Link>
          )}
          <Link to="/" style={{ color: '#93c5fd', textDecoration: 'none' }}>Stations</Link>
          <span style={{ color: '#64748b' }}>{user.email}</span>
          <button
            onClick={async () => { await logout(); navigate('/login') }}
            style={{
              background: '#1e2130', border: '1px solid #2d3348', borderRadius: 8,
              padding: '6px 12px', cursor: 'pointer', color: '#94a3b8', fontSize: 12,
            }}
          >Sign out</button>
        </div>
      )}
    </header>
  )
}
