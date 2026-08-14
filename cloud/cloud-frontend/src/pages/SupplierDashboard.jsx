/**
 * Supplier Dashboard — urgency-sorted station list.
 *
 * Each card shows:
 *   • Station name + customer
 *   • Color-coded urgency indicator (red <20%, yellow 20-40%, green >40%)
 *   • Per-tank fill bars with %, gallons, and product name
 *   • "Mark Fuel Ordered" button → 6h snooze
 *   • "Ordered · back in Xh Xm" snooze badge when active
 *
 * Auto-refreshes every 60 s. Snooze countdown updates every 30 s client-side.
 */
import React, { useCallback, useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../api/client.js'
import TopBar from '../components/TopBar.jsx'
import Footer from '../components/Footer.jsx'
import StalenessBadge from '../components/StalenessBadge.jsx'
import useIsMobile from '../hooks/useIsMobile.js'

const POLL_MS = 60_000
const SNOOZE_TICK_MS = 30_000

// ── Urgency colour coding ─────────────────────────────────────────────────────
function urgencyColor(pct) {
  if (pct == null) return '#64748b'
  if (pct < 0.20) return '#ef4444'
  if (pct < 0.40) return '#eab308'
  return '#22c55e'
}

function urgencyLabel(pct) {
  if (pct == null) return 'No data'
  if (pct < 0.20) return 'Critical'
  if (pct < 0.40) return 'Low'
  return 'OK'
}

// ── Countdown helper ──────────────────────────────────────────────────────────
function snoozeRemaining(snoozedUntil) {
  if (!snoozedUntil) return null
  const ms = new Date(snoozedUntil) - Date.now()
  if (ms <= 0) return null
  const h = Math.floor(ms / 3_600_000)
  const m = Math.floor((ms % 3_600_000) / 60_000)
  return h > 0 ? `${h}h ${m}m` : `${m}m`
}

// ── Page ─────────────────────────────────────────────────────────────────────
export default function SupplierDashboard() {
  const [stations, setStations] = useState(null)
  const [error, setError] = useState(null)
  const [orderModal, setOrderModal] = useState(null) // station object when open
  const [tick, setTick] = useState(0)                // forces countdown re-render
  const isMobile = useIsMobile()
  const timer = useRef(null)
  const tickTimer = useRef(null)

  const load = useCallback(async () => {
    try {
      const data = await api.supplier.stations()
      setStations(data)
      setError(null)
    } catch (e) {
      setError(e.message)
    }
  }, [])

  useEffect(() => {
    load()
    timer.current = setInterval(load, POLL_MS)
    tickTimer.current = setInterval(() => setTick(t => t + 1), SNOOZE_TICK_MS)
    return () => { clearInterval(timer.current); clearInterval(tickTimer.current) }
  }, [load])

  return (
    <div style={{ minHeight: '100vh', background: '#0f1117', color: '#e2e8f0' }}>
      <TopBar title="Fuel Supply" />
      <main style={{ padding: isMobile ? '16px 12px' : '24px', maxWidth: 920, margin: '0 auto' }}>

        {/* Header row */}
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 20 }}>
          <div style={{ fontSize: 12, color: '#64748b' }}>
            Stations sorted by urgency — lowest fuel first
          </div>
          <button onClick={load} style={ghostBtn}>⟳ Refresh</button>
        </div>

        {error && <ErrorBox message={error} />}

        {stations === null && !error && (
          <div style={{ color: '#64748b', padding: 40, textAlign: 'center' }}>Loading…</div>
        )}

        {stations?.length === 0 && (
          <div style={{ color: '#64748b', padding: 40, textAlign: 'center' }}>
            No stations are assigned to your account.
          </div>
        )}

        {stations?.map(s => (
          <StationCard
            key={s.id}
            station={s}
            tick={tick}
            onOrder={() => setOrderModal(s)}
            isMobile={isMobile}
          />
        ))}
      </main>

      <Footer />

      {orderModal && (
        <OrderModal
          station={orderModal}
          onClose={() => setOrderModal(null)}
          onDone={() => { setOrderModal(null); load() }}
        />
      )}
    </div>
  )
}

// ── Station card ─────────────────────────────────────────────────────────────
function StationCard({ station, tick, onOrder, isMobile }) {
  const color = urgencyColor(station.urgency_pct)
  const label = urgencyLabel(station.urgency_pct)
  const pctDisp = station.urgency_pct != null ? `${Math.round(station.urgency_pct * 100)}%` : '—'
  const volDisp = station.urgency_volume != null
    ? `${Math.round(station.urgency_volume).toLocaleString()} gal`
    : '—'
  const remaining = snoozeRemaining(station.snoozed_until)
  const snoozed = station.snooze_active && remaining

  return (
    <div style={{
      background: '#161b27', border: `1px solid #1e2130`,
      borderLeft: `4px solid ${color}`, borderRadius: 14, padding: 18, marginBottom: 16,
      opacity: snoozed ? 0.7 : 1,
    }}>
      {/* Top row */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', flexWrap: 'wrap', gap: 10 }}>
        <div>
          <Link to={`/stations/${station.id}`} style={{ textDecoration: 'none' }}>
            <div style={{ fontWeight: 800, fontSize: 16, color: '#e2e8f0' }}>{station.name}</div>
          </Link>
          <div style={{ fontSize: 11, color: '#64748b', marginTop: 2 }}>{station.customer_name}</div>
        </div>

        {/* Urgency badge */}
        <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
          <div style={{
            background: color + '22', border: `1px solid ${color}55`,
            borderRadius: 20, padding: '4px 12px',
            display: 'flex', alignItems: 'center', gap: 8,
          }}>
            <div style={{ width: 8, height: 8, borderRadius: '50%', background: color, flexShrink: 0 }} />
            <span style={{ fontWeight: 700, fontSize: 15, color }}>{pctDisp}</span>
            <span style={{ fontSize: 11, color: color + 'cc' }}>{volDisp}</span>
            <span style={{ fontSize: 10, color: '#94a3b8' }}>{label}</span>
          </div>
          <StalenessBadge lastSyncAt={station.last_sync_at} label="synced" />
        </div>
      </div>

      {/* Tank fill bars */}
      {station.tanks?.length > 0 && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 6, marginTop: 14 }}>
          {station.tanks.map(t => (
            <TankBar key={t.tank_local_id} tank={t} />
          ))}
        </div>
      )}

      {/* Action row */}
      <div style={{ display: 'flex', gap: 10, alignItems: 'center', marginTop: 14, flexWrap: 'wrap' }}>
        {snoozed ? (
          <div style={{
            background: '#1e3a5f', border: '1px solid #2563eb44', borderRadius: 8,
            padding: '6px 14px', fontSize: 12, color: '#93c5fd', fontWeight: 600,
          }}>
            ✓ Ordered · back in {remaining}
            {station.latest_order?.eta_note && (
              <span style={{ color: '#64748b', fontWeight: 400 }}> · ETA: {station.latest_order.eta_note}</span>
            )}
          </div>
        ) : (
          <button onClick={onOrder} style={{
            background: '#1d4ed8', border: 'none', borderRadius: 8,
            padding: '8px 18px', color: '#fff', fontSize: 13, fontWeight: 600, cursor: 'pointer',
            minHeight: 44,
          }}>
            Mark Fuel Ordered
          </button>
        )}
      </div>
    </div>
  )
}

// ── Per-tank fill bar ─────────────────────────────────────────────────────────
function TankBar({ tank }) {
  const pct = tank.fill_pct ?? 0
  const color = urgencyColor(tank.fill_pct)
  const pctDisp = tank.fill_pct != null ? `${Math.round(pct * 100)}%` : '—'
  const volDisp = tank.current_volume_gallons != null
    ? `${Math.round(tank.current_volume_gallons).toLocaleString()} gal`
    : '—'

  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
      <div style={{ fontSize: 11, color: '#94a3b8', width: 110, flexShrink: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
        {tank.name}{tank.product ? ` · ${tank.product}` : ''}
      </div>
      {/* Fill bar */}
      <div style={{ flex: 1, background: '#111827', borderRadius: 4, height: 8, position: 'relative', overflow: 'hidden' }}>
        <div style={{
          position: 'absolute', left: 0, top: 0, bottom: 0,
          width: `${Math.min(100, Math.round(pct * 100))}%`,
          background: color, borderRadius: 4, transition: 'width 0.3s ease',
        }} />
      </div>
      <div style={{ fontSize: 11, fontWeight: 700, color, width: 38, textAlign: 'right', flexShrink: 0 }}>
        {pctDisp}
      </div>
      <div style={{ fontSize: 11, color: '#64748b', width: 80, flexShrink: 0 }}>
        {volDisp}
      </div>
    </div>
  )
}

// ── Order modal ───────────────────────────────────────────────────────────────
function OrderModal({ station, onClose, onDone }) {
  const [eta, setEta] = useState('')
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState(null)

  const submit = async () => {
    setSaving(true); setError(null)
    try {
      await api.supplier.markOrdered(station.id, { eta_note: eta.trim() || null })
      onDone()
    } catch (e) {
      setError(e.message)
      setSaving(false)
    }
  }

  // Close on backdrop click
  const onBackdrop = (e) => { if (e.target === e.currentTarget) onClose() }

  return (
    <div
      onClick={onBackdrop}
      style={{
        position: 'fixed', inset: 0, background: '#000a', zIndex: 1000,
        display: 'flex', alignItems: 'center', justifyContent: 'center',
        padding: 16,
      }}
    >
      <div style={{
        background: '#161b27', border: '1px solid #2d3348', borderRadius: 16,
        padding: 28, width: '100%', maxWidth: 440,
      }}>
        <div style={{ fontWeight: 800, fontSize: 17, marginBottom: 6 }}>Mark Fuel Ordered</div>
        <div style={{ fontSize: 13, color: '#94a3b8', marginBottom: 20 }}>
          {station.name} — this station will move to the bottom of your list for 6 hours.
        </div>

        <label style={{ display: 'block', fontSize: 12, color: '#94a3b8', marginBottom: 6 }}>
          Delivery ETA (optional)
        </label>
        <input
          autoFocus
          type="text"
          placeholder="e.g. Tomorrow 8am, ~4 hours, Wednesday morning…"
          value={eta}
          onChange={e => setEta(e.target.value)}
          onKeyDown={e => e.key === 'Enter' && submit()}
          style={{
            width: '100%', boxSizing: 'border-box',
            background: '#0f1117', border: '1px solid #2d3348', borderRadius: 8,
            padding: '10px 12px', color: '#e2e8f0', fontSize: 13, marginBottom: 16, outline: 'none',
          }}
        />

        {error && <div style={{ color: '#fca5a5', fontSize: 12, marginBottom: 12 }}>{error}</div>}

        <div style={{ display: 'flex', gap: 10, justifyContent: 'flex-end' }}>
          <button onClick={onClose} style={ghostBtn}>Cancel</button>
          <button
            onClick={submit}
            disabled={saving}
            style={{
              background: saving ? '#1e3a5f' : '#1d4ed8', border: 'none', borderRadius: 8,
              padding: '10px 22px', color: '#fff', fontSize: 13, fontWeight: 600,
              cursor: saving ? 'default' : 'pointer', minHeight: 44,
            }}
          >
            {saving ? 'Confirming…' : 'Confirm order'}
          </button>
        </div>
      </div>
    </div>
  )
}

// ── Shared styles ─────────────────────────────────────────────────────────────
const ghostBtn = {
  background: 'transparent', border: '1px solid #2d3348', borderRadius: 8,
  padding: '6px 14px', color: '#94a3b8', fontSize: 12, cursor: 'pointer', minHeight: 36,
}

function ErrorBox({ message }) {
  return (
    <div style={{
      background: '#450a0a', border: '1px solid #ef4444', borderRadius: 10,
      padding: '12px 16px', color: '#fca5a5', fontSize: 13, marginBottom: 16,
    }}>{message}</div>
  )
}
