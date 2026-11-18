import React, { createContext, useContext, useEffect, useState, useCallback } from 'react'
import { api } from '../api/client.js'

const AuthContext = createContext(null)

// Admin "log in as" — the admin's own token is stashed here (sessionStorage,
// not persisted beyond the tab) while impersonating, so returnToAdmin() can
// swap straight back without the admin re-authenticating. See admin.py's
// POST /admin/users/{id}/impersonate — it's a completely normal session for
// the target user, nothing about their account changes.
const RETURN_TOKEN_KEY = 'tls_admin_return_token'

export function AuthProvider({ children }) {
  const [user, setUser] = useState(null)
  const [loading, setLoading] = useState(true)
  const [impersonating, setImpersonating] = useState(() => !!sessionStorage.getItem(RETURN_TOKEN_KEY))

  const refresh = useCallback(async () => {
    try {
      const me = await api.me()
      setUser(me)
    } catch {
      setUser(null)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { refresh() }, [refresh])

  const login = async (email, password, duration) => {
    const res = await api.login(email, password, duration)
    setUser(res.user)
    return res.user
  }

  const loginWithMagicLink = async (token) => {
    const res = await api.magicLogin(token)
    setUser(res.user)
    return res.user
  }

  const logout = async () => {
    sessionStorage.removeItem(RETURN_TOKEN_KEY)
    setImpersonating(false)
    try { await api.logout() } catch { /* ignore */ }
    setUser(null)
  }

  // Admin-only: switch the active session to this user's, stashing the
  // admin's own token first so returnToAdmin() can come back. Does NOT
  // touch the target user's password or revoke anything of theirs.
  const impersonate = async (userId) => {
    const res = await api.admin.impersonate(userId)
    const current = api.getSessionToken()
    if (current && !sessionStorage.getItem(RETURN_TOKEN_KEY)) {
      sessionStorage.setItem(RETURN_TOKEN_KEY, current)
    }
    api.setSessionToken(res.token)
    setUser(res.user)
    setImpersonating(true)
    return res.user
  }

  const returnToAdmin = async () => {
    const original = sessionStorage.getItem(RETURN_TOKEN_KEY)
    if (!original) return
    sessionStorage.removeItem(RETURN_TOKEN_KEY)
    api.setSessionToken(original)
    setImpersonating(false)
    await refresh()
  }

  return (
    <AuthContext.Provider value={{ user, loading, login, loginWithMagicLink, logout, refresh, impersonate, returnToAdmin, impersonating }}>
      {children}
    </AuthContext.Provider>
  )
}

export function useAuth() {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error('useAuth must be used inside AuthProvider')
  return ctx
}
