import React from 'react'

function fillColor(pct) {
  if (pct > 0.4) return '#22c55e'
  if (pct > 0.2) return '#eab308'
  return '#ef4444'
}

// Reused visual pattern from the station-local T1 gauge (see frontend/src/components/TankGauge.jsx)
// — same component code the design doc calls for, adapted here to the cloud
// API's `local_id` field name instead of the local api's `id`.
export default function TankGauge({ tank }) {
  const r = tank.latest_reading
  const volume = r?.volume_gallons ?? 0
  const capacity = tank.capacity_gallons ?? 1
  const ullage = r?.ullage_gallons ?? 0
  const temp = r?.temperature_f ?? null

  const pct = Math.min(1, Math.max(0, volume / capacity))
  const pctLbl = Math.round(pct * 100)
  const color = fillColor(pct)

  return (
    <div style={{
      display: 'flex', flexDirection: 'column', gap: 8,
      background: '#1e2130', borderRadius: 16, padding: 16,
      border: '1.5px solid #2d3348', minWidth: 160,
    }}>
      <div style={{ fontWeight: 700, fontSize: 13, color: '#94a3b8' }}>{tank.name}</div>
      <div style={{
        position: 'relative', width: '100%', aspectRatio: '1 / 1', borderRadius: 12,
        background: '#111827', border: '1px solid #374151', overflow: 'hidden',
      }}>
        <div style={{
          position: 'absolute', left: 0, right: 0, bottom: 0,
          height: `${pct * 100}%`,
          background: `linear-gradient(180deg, ${color}f2, ${color}b3)`,
          transition: 'height 0.3s ease',
        }} />
        <div style={{
          position: 'absolute', inset: 0, display: 'flex',
          flexDirection: 'column', alignItems: 'center', justifyContent: 'center',
        }}>
          <div style={{ fontSize: 22, fontWeight: 800, color: '#f8fafc', textShadow: '0 1px 3px #000a' }}>
            {pctLbl}%
          </div>
          <div style={{ fontSize: 10, color: '#e2e8f0', textShadow: '0 1px 3px #000a' }}>
            {volume.toLocaleString(undefined, { maximumFractionDigits: 0 })} gal
          </div>
        </div>
      </div>
      <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 10, color: '#64748b' }}>
        <span>↑ {ullage.toLocaleString(undefined, { maximumFractionDigits: 0 })} gal</span>
        {temp !== null && <span>🌡 {temp.toFixed(0)}°F</span>}
      </div>
    </div>
  )
}
