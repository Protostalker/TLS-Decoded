import React from 'react'
import { Navigate } from 'react-router-dom'
import { useAuth } from '../context/AuthContext.jsx'

export function ProtectedRoute({ children }) {
  const { user, loading } = useAuth()
  if (loading) return <Centered>Loading…</Centered>
  if (!user) return <Navigate to="/login" replace />
  return children
}

export function AdminRoute({ children }) {
  const { user, loading } = useAuth()
  if (loading) return <Centered>Loading…</Centered>
  if (!user) return <Navigate to="/login" replace />
  if (user.role !== 'admin') return <Navigate to="/" replace />
  return children
}

export function SupplierRoute({ children }) {
  const { user, loading } = useAuth()
  if (loading) return <Centered>Loading…</Centered>
  if (!user) return <Navigate to="/login" replace />
  if (user.role !== 'supplier' && user.role !== 'admin') return <Navigate to="/" replace />
  return children
}

function Centered({ children }) {
  return (
    <div style={{ minHeight: '100vh', display: 'flex', alignItems: 'center', justifyContent: 'center', color: '#64748b' }}>
      {children}
    </div>
  )
}
