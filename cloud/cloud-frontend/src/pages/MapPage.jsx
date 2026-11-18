import React, { useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { MapContainer, TileLayer, CircleMarker, Marker, Popup } from 'react-leaflet'
import L from 'leaflet'
import 'leaflet/dist/leaflet.css'
import { api } from '../api/client.js'
import TopBar from '../components/TopBar.jsx'
import Footer from '../components/Footer.jsx'
import { useAuth } from '../context/AuthContext.jsx'

// A tiny emoji-in-a-div marker for in-transit deliveries — no image asset
// to resolve under Vite, unlike Leaflet's default pin icon.
const truckIcon = L.divIcon({
  html: '<div style="font-size:18px;line-height:1;transform:translate(-2px,-2px)">🚚</div>',
  className: '', iconSize: [22, 22], iconAnchor: [11, 11],
})
const rackIcon = L.divIcon({
  html: '<div style="font-size:18px;line-height:1;transform:translate(-2px,-2px)">🛢️</div>',
  className: '', iconSize: [22, 22], iconAnchor: [11, 11],
})

// Poll cadence for the map — delivery progress bars need to actually move;
// station urgency/sync data is cheap to refetch at the same cadence.
const POLL_MS = 30_000

const card = {
  background: 'var(--brand-surface-2, #161b27)', border: '1px solid var(--brand-border-soft, #1e2130)', borderRadius: 14, padding: 18,
}

// Continental-US-ish default center/zoom used only when there are zero
// pinned stations to derive a view from (brand new account, nobody's set a
// pin yet) — picked purely so the map doesn't open on the ocean.
const DEFAULT_CENTER = [39.5, -98.35]
const DEFAULT_ZOOM = 4

// Urgency color scale — urgency_pct is "lowest tank fill fraction across the
// station's active tanks" from GET /stations/map (0 = empty, 1 = full).
// null means no readings/tanks yet to judge by, shown neutral gray.
function urgencyColor(pct) {
  if (pct === null || pct === undefined) return '#64748b'
  if (pct < 0.15) return '#ef4444'   // red — reorder territory
  if (pct < 0.35) return '#f59e0b'   // amber — getting there
  return '#22c55e'                   // green — comfortable
}

function fmtRelative(iso) {
  if (!iso) return 'never synced'
  const ms = Date.now() - new Date(iso).getTime()
  const mins = Math.round(ms / 60000)
  if (mins < 1) return 'just now'
  if (mins < 60) return `${mins}m ago`
  const hrs = Math.round(mins / 60)
  if (hrs < 24) return `${hrs}h ago`
  return `${Math.round(hrs / 24)}d ago`
}

export default function MapPage() {
  const { user } = useAuth()
  const [stations, setStations] = useState(null)
  const [racks, setRacks] = useState(null)
  const [error, setError] = useState(null)
  const canSeeRacks = user?.role === 'supplier' || user?.role === 'admin'

  useEffect(() => {
    const load = () => api.stationsMap().then(setStations).catch(e => setError(e.message))
    load()
    const timer = setInterval(load, POLL_MS)
    return () => clearInterval(timer)
  }, [])

  useEffect(() => {
    if (!canSeeRacks) return
    // Racks don't move and don't need the 30s poll cadence stations use —
    // a one-time fetch per page load is plenty.
    api.fleet.racks().then(setRacks).catch(() => setRacks([]))
  }, [canSeeRacks])

  const homeTo = user?.role === 'admin' ? undefined : (user?.role === 'supplier' ? '/supplier' : '/')

  const pinnedStations = stations || []
  const pinnedRacks = (racks || []).filter(r => r.lat != null && r.lng != null)
  const hasAnyPins = pinnedStations.length > 0 || pinnedRacks.length > 0

  const center = useMemo(() => {
    const points = [...pinnedStations, ...pinnedRacks]
    if (points.length === 0) return DEFAULT_CENTER
    const lat = points.reduce((sum, p) => sum + p.lat, 0) / points.length
    const lng = points.reduce((sum, p) => sum + p.lng, 0) / points.length
    return [lat, lng]
  }, [pinnedStations, pinnedRacks])

  return (
    <div style={{ minHeight: '100vh', background: 'var(--brand-bg, #0f1117)' }}>
      <TopBar title="Station Map" backTo={homeTo} />
      <main style={{ padding: 24, maxWidth: 1260, margin: '0 auto' }}>
        {error && (
          <div style={{ ...card, border: '1px solid #ef4444', color: '#fca5a5', marginBottom: 16 }}>{error}</div>
        )}

        {stations === null && !error && (
          <div style={{ color: 'var(--brand-text-dimmer, #64748b)', padding: 40, textAlign: 'center' }}>Loading…</div>
        )}

        {stations && !hasAnyPins && !error && (
          <div style={{ ...card, textAlign: 'center', color: 'var(--brand-text-dimmer, #64748b)' }}>
            No stations have a map pin yet.{user?.role === 'admin' ? ' Set one from the Admin page.' : ' Ask an admin to set one.'}
          </div>
        )}

        {stations && hasAnyPins && (
          <div style={{ ...card, padding: 0, overflow: 'hidden' }}>
            <div style={{ height: 560, position: 'relative' }}>
              <MapContainer
                center={center}
                zoom={(pinnedStations.length + pinnedRacks.length) === 1 ? 12 : DEFAULT_ZOOM}
                style={{ height: '100%', width: '100%' }}
                scrollWheelZoom
              >
                <TileLayer
                  attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
                  url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
                />
                {stations.map(s => (
                  <CircleMarker
                    key={s.id}
                    center={[s.lat, s.lng]}
                    radius={11}
                    pathOptions={{
                      color: urgencyColor(s.urgency_pct),
                      fillColor: urgencyColor(s.urgency_pct),
                      fillOpacity: 0.85,
                      weight: 2,
                    }}
                  >
                    <Popup>
                      <div style={{ minWidth: 160 }}>
                        <div style={{ fontWeight: 700, marginBottom: 4 }}>{s.name}</div>
                        {s.address && <div style={{ fontSize: 12, color: '#555', marginBottom: 6 }}>{s.address}</div>}
                        <div style={{ fontSize: 12, marginBottom: 6 }}>
                          {s.urgency_pct !== null ? `Lowest tank: ${Math.round(s.urgency_pct * 100)}% full` : 'No readings yet'}
                        </div>
                        <div style={{ fontSize: 11, color: '#777', marginBottom: 8 }}>Synced {fmtRelative(s.last_sync_at)}</div>
                        {s.delivery && (
                          <div style={{ fontSize: 11, color: s.delivery.running_late ? '#b45309' : '#2563eb', marginBottom: 8 }}>
                            🚚 {s.delivery.origin_label ? `From ${s.delivery.origin_label} — ` : ''}
                            {s.delivery.running_late ? 'running late' : `~${Math.round(Math.min(s.delivery.progress_pct, 1) * 100)}% of the way there`}
                            {' '}(~{Math.round(s.delivery.eta_minutes)} min drive)
                          </div>
                        )}
                        <Link to={`/stations/${s.id}`} style={{ fontSize: 12, color: '#2563eb' }}>Open dashboard →</Link>
                      </div>
                    </Popup>
                  </CircleMarker>
                ))}
                {stations.filter(s => s.delivery).map(s => (
                  <Marker key={`delivery-${s.id}`} position={[s.lat, s.lng]} icon={truckIcon}>
                    <Popup>
                      <div style={{ minWidth: 160 }}>
                        <div style={{ fontWeight: 700, marginBottom: 4 }}>Delivery → {s.name}</div>
                        {s.delivery.origin_label && <div style={{ fontSize: 12, color: '#555', marginBottom: 6 }}>From {s.delivery.origin_label}</div>}
                        <div style={{ fontSize: 12, color: s.delivery.running_late ? '#b45309' : '#2563eb' }}>
                          {s.delivery.running_late ? 'Running late vs. estimate' : `~${Math.round(Math.min(s.delivery.progress_pct, 1) * 100)}% of the way there`}
                        </div>
                        <div style={{ fontSize: 11, color: '#777', marginTop: 4 }}>
                          Estimated {Math.round(s.delivery.eta_minutes)} min drive
                          {s.delivery.route_distance_km && ` · ${Math.round(s.delivery.route_distance_km)} km`}
                        </div>
                      </div>
                    </Popup>
                  </Marker>
                ))}
                {pinnedRacks.map(r => (
                  <Marker key={`rack-${r.id}`} position={[r.lat, r.lng]} icon={rackIcon}>
                    <Popup>
                      <div style={{ minWidth: 140 }}>
                        <div style={{ fontWeight: 700, marginBottom: 4 }}>{r.name}</div>
                        <div style={{ fontSize: 11, color: '#777' }}>Loading rack</div>
                        {r.address && <div style={{ fontSize: 12, color: '#555', marginTop: 4 }}>{r.address}</div>}
                      </div>
                    </Popup>
                  </Marker>
                ))}
              </MapContainer>

              <div style={{
                position: 'absolute', bottom: 12, left: 12, zIndex: 500,
                background: 'rgba(22,27,39,0.92)', border: '1px solid #1e2130', borderRadius: 10,
                padding: '8px 12px', fontSize: 11, color: '#94a3b8',
                display: 'flex', gap: 14, alignItems: 'center',
              }}>
                <Legend color="#ef4444" label="< 15% full" />
                <Legend color="#f59e0b" label="< 35% full" />
                <Legend color="#22c55e" label="comfortable" />
                <Legend color="#64748b" label="no data" />
                <span style={{ display: 'flex', alignItems: 'center', gap: 6 }}>🚚 delivery in transit</span>
                {canSeeRacks && <span style={{ display: 'flex', alignItems: 'center', gap: 6 }}>🛢️ loading rack</span>}
              </div>
            </div>
          </div>
        )}
      </main>
      <Footer />
    </div>
  )
}

function Legend({ color, label }) {
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
      <span style={{ width: 10, height: 10, borderRadius: '50%', background: color, display: 'inline-block' }} />
      {label}
    </div>
  )
}
