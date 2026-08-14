import React, { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { useAuth } from '../context/AuthContext.jsx'
import { api } from '../api/client.js'

// Shown to EVERY logged-in user (not just admins) when the Cloud Utility's
// license needs attention — per the dev handoff doc: "Show a clear in-app
// banner explaining why, with a renewal link/contact," even though only
// admins can actually see data while degraded. Polls occasionally rather
// than once, so it clears itself without a refresh right after an admin
// renews. Renders nothing at all in the common case (license active/unset) —
// no layout shift, no flash on every page load.
export default function LicenseBanner() {
  const { user } = useAuth()
  const [banner, setBanner] = useState(null)

  useEffect(() => {
    if (!user) return
    let cancelled = false
    const load = () => api.license.banner().then(b => { if (!cancelled) setBanner(b) }).catch(() => {})
    load()
    const id = setInterval(load, 5 * 60 * 1000)
    return () => { cancelled = true; clearInterval(id) }
  }, [user])

  if (!user || !banner || !banner.message) return null

  const severe = banner.degraded
  return (
    <div style={{
      background: severe ? '#7f1d1d' : '#78350f',
      color: severe ? '#fecaca' : '#fde68a',
      borderBottom: `1px solid ${severe ? '#991b1b' : '#92400e'}`,
      padding: '10px 16px', fontSize: 13, display: 'flex',
      alignItems: 'center', justifyContent: 'center', gap: 10, flexWrap: 'wrap', textAlign: 'center',
    }}>
      <span>{banner.message}</span>
      {user.role === 'admin' && (
        <Link to="/admin" style={{ color: 'inherit', fontWeight: 700, textDecoration: 'underline', whiteSpace: 'nowrap' }}>
          View License
        </Link>
      )}
    </div>
  )
}
