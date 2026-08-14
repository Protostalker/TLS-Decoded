/**
 * NotificationBell — bell icon in TopBar showing unread count.
 *
 * Clicking the bell opens a dropdown panel listing the last 50 notifications,
 * with mark-as-read on individual items and a "mark all read" button.
 *
 * Also manages the Web Push subscription lifecycle:
 *   1. On mount, fetch VAPID public key (null → skip everything)
 *   2. Register service worker (public/sw.js)
 *   3. Subscribe the browser to push with the VAPID key
 *   4. POST the subscription object to /api/push/subscribe
 *
 * If the user's browser doesn't support notifications or they deny permission,
 * we silently skip push — the in-app bell always works regardless.
 */
import React, { useCallback, useEffect, useRef, useState } from 'react'
import { api } from '../api/client.js'

const POLL_MS = 30_000

// ── Helpers ───────────────────────────────────────────────────────────────────
function urlBase64ToUint8Array(base64String) {
  const padding = '='.repeat((4 - (base64String.length % 4)) % 4)
  const base64 = (base64String + padding).replace(/-/g, '+').replace(/_/g, '/')
  const rawData = atob(base64)
  return Uint8Array.from([...rawData].map(c => c.charCodeAt(0)))
}

function timeAgo(isoString) {
  const diff = Date.now() - new Date(isoString)
  const m = Math.floor(diff / 60_000)
  if (m < 1) return 'just now'
  if (m < 60) return `${m}m ago`
  const h = Math.floor(m / 60)
  if (h < 24) return `${h}h ago`
  return `${Math.floor(h / 24)}d ago`
}

// ── Component ─────────────────────────────────────────────────────────────────
export default function NotificationBell() {
  const [notifications, setNotifications] = useState([])
  const [open, setOpen] = useState(false)
  const ref = useRef(null)
  const timer = useRef(null)

  const unread = notifications.filter(n => !n.read_at).length

  // ── Fetch notifications ───────────────────────────────────────────────────
  const load = useCallback(async () => {
    try {
      const data = await api.notifications()
      setNotifications(data)
    } catch { /* silent */ }
  }, [])

  useEffect(() => {
    load()
    timer.current = setInterval(load, POLL_MS)
    return () => clearInterval(timer.current)
  }, [load])

  // ── Close on outside click ────────────────────────────────────────────────
  useEffect(() => {
    function handler(e) {
      if (ref.current && !ref.current.contains(e.target)) setOpen(false)
    }
    if (open) document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [open])

  // ── Web Push setup (best-effort, fire-and-forget) ─────────────────────────
  useEffect(() => {
    setupPush().catch(() => { /* silently skip if anything fails */ })
  }, [])

  // ── Actions ───────────────────────────────────────────────────────────────
  const markRead = async (id) => {
    try {
      await api.markNotificationRead(id)
      setNotifications(ns => ns.map(n => n.id === id ? { ...n, read_at: new Date().toISOString() } : n))
    } catch { /* silent */ }
  }

  const markAllRead = async () => {
    try {
      await api.markAllNotificationsRead()
      const now = new Date().toISOString()
      setNotifications(ns => ns.map(n => ({ ...n, read_at: n.read_at ?? now })))
    } catch { /* silent */ }
  }

  return (
    <div ref={ref} style={{ position: 'relative' }}>
      {/* Bell button */}
      <button
        onClick={() => { setOpen(o => !o); if (!open && unread > 0) markAllRead() }}
        aria-label="Notifications"
        style={{
          position: 'relative', background: 'none', border: 'none',
          cursor: 'pointer', padding: '4px 6px', display: 'flex', alignItems: 'center',
          color: '#94a3b8', fontSize: 18, lineHeight: 1,
          minWidth: 36, minHeight: 36, justifyContent: 'center',
        }}
      >
        🔔
        {unread > 0 && (
          <span style={{
            position: 'absolute', top: 0, right: 0,
            background: '#ef4444', color: '#fff',
            borderRadius: '50%', fontSize: 10, fontWeight: 700,
            minWidth: 16, height: 16, lineHeight: '16px', textAlign: 'center',
            padding: '0 3px', boxSizing: 'border-box',
          }}>
            {unread > 9 ? '9+' : unread}
          </span>
        )}
      </button>

      {/* Dropdown panel */}
      {open && (
        <div style={{
          position: 'absolute', top: 44, right: 0, zIndex: 2000,
          background: '#161b27', border: '1px solid #2d3348',
          borderRadius: 12, boxShadow: '0 12px 40px rgba(0,0,0,0.5)',
          width: 320, maxHeight: 420, display: 'flex', flexDirection: 'column',
        }}>
          {/* Header */}
          <div style={{
            display: 'flex', justifyContent: 'space-between', alignItems: 'center',
            padding: '12px 16px', borderBottom: '1px solid #1e2130',
          }}>
            <div style={{ fontWeight: 700, fontSize: 13 }}>Notifications</div>
            {notifications.some(n => !n.read_at) && (
              <button
                onClick={markAllRead}
                style={{ background: 'none', border: 'none', color: '#93c5fd', fontSize: 11, cursor: 'pointer', padding: 0 }}
              >
                Mark all read
              </button>
            )}
          </div>

          {/* List */}
          <div style={{ overflowY: 'auto', flex: 1 }}>
            {notifications.length === 0 && (
              <div style={{ padding: '24px 16px', textAlign: 'center', color: '#64748b', fontSize: 13 }}>
                No notifications yet
              </div>
            )}
            {notifications.map(n => (
              <NotificationRow key={n.id} notification={n} onRead={() => markRead(n.id)} />
            ))}
          </div>
        </div>
      )}
    </div>
  )
}

function NotificationRow({ notification: n, onRead }) {
  const unread = !n.read_at
  return (
    <div
      onClick={unread ? onRead : undefined}
      style={{
        padding: '12px 16px', borderBottom: '1px solid #1e2130',
        cursor: unread ? 'pointer' : 'default',
        background: unread ? '#1a2035' : 'transparent',
        transition: 'background 0.15s',
      }}
    >
      <div style={{ display: 'flex', gap: 8, alignItems: 'flex-start' }}>
        {unread && (
          <div style={{ width: 7, height: 7, borderRadius: '50%', background: '#3b82f6', flexShrink: 0, marginTop: 5 }} />
        )}
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ fontSize: 12, color: '#e2e8f0', lineHeight: 1.4 }}>{n.message}</div>
          {n.eta_note && (
            <div style={{ fontSize: 11, color: '#64748b', marginTop: 3 }}>ETA: {n.eta_note}</div>
          )}
          <div style={{ fontSize: 10, color: '#475569', marginTop: 4 }}>{timeAgo(n.created_at)}</div>
        </div>
      </div>
    </div>
  )
}

// ── Web Push setup ────────────────────────────────────────────────────────────
async function setupPush() {
  if (!('serviceWorker' in navigator) || !('PushManager' in window)) return
  const { vapid_public_key } = await api.push.vapidPublicKey()
  if (!vapid_public_key) return

  const reg = await navigator.serviceWorker.register('/sw.js')
  await navigator.serviceWorker.ready

  const permission = await Notification.requestPermission()
  if (permission !== 'granted') return

  const sub = await reg.pushManager.subscribe({
    userVisibleOnly: true,
    applicationServerKey: urlBase64ToUint8Array(vapid_public_key),
  })

  await api.push.subscribe(JSON.stringify(sub))
}
