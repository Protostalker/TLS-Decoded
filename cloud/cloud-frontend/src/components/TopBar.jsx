import React, { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { useAuth } from '../context/AuthContext.jsx'
import BrandLogo from './BrandLogo.jsx'
import LicenseBanner from './LicenseBanner.jsx'
import NotificationBell from './NotificationBell.jsx'
import useIsMobile from '../hooks/useIsMobile.js'

// logoDataUrl is only ever passed by StationDashboardPage (T1) — every other
// caller (T2 station list, Admin, Login) renders the default gradient badge
// since --brand-* CSS vars are unset there. See brandTheme.js for scoping.
export default function TopBar({ title, backTo, logoDataUrl }) {
  const { user, logout } = useAuth()
  const navigate = useNavigate()
  const isMobile = useIsMobile()
  const [menuOpen, setMenuOpen] = useState(false)

  const handleLogout = async () => {
    setMenuOpen(false)
    await logout()
    navigate('/login')
  }

  return (
    <>
    <header style={{
      background: 'var(--brand-surface-2, #161b27)', borderBottom: '1px solid var(--brand-border-soft, #1e2130)',
      padding: '0 16px', height: 60,
      display: 'flex', alignItems: 'center', justifyContent: 'space-between',
      position: 'relative',
    }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 14 }}>
        {backTo && (
          <Link to={backTo} style={{
            color: 'var(--brand-text-dimmer, #64748b)', textDecoration: 'none', fontSize: 13, marginRight: 4,
          }}>← Back</Link>
        )}
        <BrandLogo logoDataUrl={logoDataUrl} size={32} />
        <div>
          <div style={{ fontWeight: 800, fontSize: isMobile ? 14 : 16, letterSpacing: -0.3, color: 'var(--brand-text, #e2e8f0)' }}>
            {title ?? 'TLS-Decoded Cloud'}
          </div>
          <div style={{ fontSize: 10, color: 'var(--brand-text-faint, #475569)' }}>Fuel Tank Monitor</div>
        </div>
      </div>

      {user && !isMobile && (
        <div style={{ display: 'flex', alignItems: 'center', gap: 16, fontSize: 12 }}>
          {user.role === 'admin' && (
            <Link to="/admin" style={{ color: '#93c5fd', textDecoration: 'none' }}>Admin</Link>
          )}
          {user.role === 'supplier' ? (
            <Link to="/supplier" style={{ color: '#93c5fd', textDecoration: 'none' }}>Fuel Supply</Link>
          ) : (
            <Link to="/" style={{ color: '#93c5fd', textDecoration: 'none' }}>Stations</Link>
          )}
          {user.role !== 'supplier' && <NotificationBell />}
          <span style={{ color: 'var(--brand-text-dimmer, #64748b)' }}>{user.email}</span>
          <button
            onClick={handleLogout}
            style={{
              background: 'var(--brand-surface, #1e2130)', border: '1px solid var(--brand-border, #2d3348)', borderRadius: 8,
              padding: '6px 12px', cursor: 'pointer', color: 'var(--brand-text-dim, #94a3b8)', fontSize: 12,
            }}
          >Sign out</button>
        </div>
      )}

      {user && isMobile && (
        <div style={{ position: 'relative' }}>
          <button
            onClick={() => setMenuOpen(o => !o)}
            style={{
              background: 'var(--brand-surface, #1e2130)', border: '1px solid var(--brand-border, #2d3348)',
              borderRadius: 8, padding: '6px 10px', cursor: 'pointer',
              color: 'var(--brand-text-dim, #94a3b8)', fontSize: 18, lineHeight: 1,
              minWidth: 44, minHeight: 44, display: 'flex', alignItems: 'center', justifyContent: 'center',
            }}
            aria-label="Menu"
          >
            {menuOpen ? '✕' : '☰'}
          </button>

          {menuOpen && (
            <div style={{
              position: 'absolute', top: 50, right: 0, zIndex: 1000,
              background: 'var(--brand-surface-2, #161b27)',
              border: '1px solid var(--brand-border, #2d3348)',
              borderRadius: 10, padding: '8px 0', minWidth: 180,
              boxShadow: '0 8px 24px rgba(0,0,0,0.4)',
            }}>
              <div style={{ padding: '6px 16px', fontSize: 11, color: 'var(--brand-text-dimmer, #64748b)', borderBottom: '1px solid var(--brand-border-soft, #1e2130)', marginBottom: 4 }}>
                {user.email}
              </div>
              {user.role === 'supplier' ? (
                <MenuLink to="/supplier" onClick={() => setMenuOpen(false)}>Fuel Supply</MenuLink>
              ) : (
                <MenuLink to="/" onClick={() => setMenuOpen(false)}>Stations</MenuLink>
              )}
              {user.role === 'admin' && (
                <MenuLink to="/admin" onClick={() => setMenuOpen(false)}>Admin</MenuLink>
              )}
              <button
                onClick={handleLogout}
                style={{
                  display: 'block', width: '100%', textAlign: 'left',
                  padding: '10px 16px', background: 'none', border: 'none',
                  color: '#fca5a5', fontSize: 13, cursor: 'pointer',
                }}
              >
                Sign out
              </button>
            </div>
          )}
        </div>
      )}
    </header>
    <LicenseBanner />
    </>
  )
}

function MenuLink({ to, onClick, children }) {
  return (
    <Link
      to={to}
      onClick={onClick}
      style={{
        display: 'block', padding: '10px 16px',
        color: '#93c5fd', textDecoration: 'none', fontSize: 13,
      }}
    >
      {children}
    </Link>
  )
}
