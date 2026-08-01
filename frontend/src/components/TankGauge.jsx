import React from 'react'
import useIsMobile from '../hooks/useIsMobile.js'

const W = 140
const H = 260
const RX = 60
const CX = W / 2
const TOP_Y = 30
const BOT_Y = H - 20
const BODY_H = BOT_Y - TOP_Y

function fillColor(pct) {
  if (pct > 0.4) return '#22c55e'
  if (pct > 0.2) return '#eab308'
  return '#ef4444'
}

function CompactSquareGauge({ tank, volume, capacity, ullage, temp, height, pct, pctLbl, color }) {
  return (
    <div style={{
      display: 'flex', flexDirection: 'column', gap: 8,
      background: '#1e2130', borderRadius: 18, padding: '16px',
      border: '1.5px solid #2d3348', width: '100%', boxSizing: 'border-box',
    }}>
      <div style={{ fontWeight: 700, fontSize: 13, color: '#94a3b8' }}>{tank.name}</div>

      {/* Rounded-square progress fill */}
      <div style={{
        position: 'relative', width: '100%', aspectRatio: '1 / 1', borderRadius: 14,
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
          <div style={{ fontSize: 24, fontWeight: 800, color: '#f8fafc', textShadow: '0 1px 3px #000a' }}>
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

export default function TankGauge({ tank }) {
  const isMobile = useIsMobile()
  const r = tank.latest_reading
  const volume   = r?.volume_gallons  ?? 0
  const capacity = tank.capacity_gallons ?? 1
  const ullage   = r?.ullage_gallons  ?? 0
  const temp     = r?.temperature_f   ?? null
  const height   = r?.height_inches   ?? null

  const pct    = Math.min(1, Math.max(0, volume / capacity))
  const pctLbl = Math.round(pct * 100)
  const color  = fillColor(pct)

  const fillH = BODY_H * pct
  const fillY = BOT_Y - fillH

  if (isMobile) {
    return (
      <CompactSquareGauge
        tank={tank} volume={volume} capacity={capacity} ullage={ullage}
        temp={temp} height={height} pct={pct} pctLbl={pctLbl} color={color}
      />
    )
  }

  return (
    <div style={{
      display: 'flex', flexDirection: 'column', alignItems: 'center',
      background: '#1e2130', borderRadius: 12, padding: '16px 12px',
      minWidth: 170, gap: 8,
      border: '1.5px solid #2d3348',
    }}>
      <div style={{ fontWeight: 700, fontSize: 14, color: '#94a3b8', textAlign: 'center' }}>
        {tank.name}
      </div>

      <svg width={W} height={H} viewBox={`0 0 ${W} ${H}`}>
        <defs>
          <clipPath id={`clip-${tank.id}`}>
            <rect x={CX - RX} y={TOP_Y} width={RX * 2} height={BODY_H} />
          </clipPath>
          <linearGradient id={`sheen-${tank.id}`} x1="0" x2="1" y1="0" y2="0">
            <stop offset="0%"   stopColor="#ffffff" stopOpacity="0.04" />
            <stop offset="100%" stopColor="#000000" stopOpacity="0.12" />
          </linearGradient>
          <linearGradient id={`fill-${tank.id}`} x1="0" x2="0" y1="0" y2="1">
            <stop offset="0%"   stopColor={color} stopOpacity="0.95" />
            <stop offset="100%" stopColor={color} stopOpacity="0.70" />
          </linearGradient>
        </defs>

        {/* Cylinder body background */}
        <rect x={CX-RX} y={TOP_Y} width={RX*2} height={BODY_H}
          fill="#111827" stroke="#374151" strokeWidth={1.5} />

        {/* Fuel fill */}
        <rect x={CX-RX} y={fillY} width={RX*2} height={fillH}
          fill={`url(#fill-${tank.id})`}
          clipPath={`url(#clip-${tank.id})`} />

        {/* Glass sheen */}
        <rect x={CX-RX} y={TOP_Y} width={RX*2} height={BODY_H}
          fill={`url(#sheen-${tank.id})`}
          clipPath={`url(#clip-${tank.id})`} />

        {/* Caps */}
        <ellipse cx={CX} cy={TOP_Y} rx={RX} ry={14}
          fill="#1f2937" stroke="#374151" strokeWidth={1.5} />
        <ellipse cx={CX} cy={BOT_Y} rx={RX} ry={14}
          fill="#111827" stroke="#374151" strokeWidth={1.5} />

        {/* Product label */}
        <text x={CX} y={(TOP_Y+BOT_Y)/2 - 20}
          textAnchor="middle" fill="#cbd5e1" fontSize={11}>
          {tank.product ?? ''}
        </text>

        {/* Percentage */}
        <text x={CX} y={(TOP_Y+BOT_Y)/2 + 8}
          textAnchor="middle" fill="#f1f5f9" fontSize={28} fontWeight="bold">
          {pctLbl}%
        </text>

        {/* Volume */}
        <text x={CX} y={(TOP_Y+BOT_Y)/2 + 26}
          textAnchor="middle" fill="#94a3b8" fontSize={10}>
          {volume.toLocaleString(undefined, {maximumFractionDigits:0})} gal
        </text>
      </svg>

      {/* Stats row */}
      <div style={{ display:'flex', gap:12, fontSize:11, color:'#64748b' }}>
        <span title="Ullage (space remaining)">
          ↑ {ullage.toLocaleString(undefined, {maximumFractionDigits:0})} gal
        </span>
        {temp !== null && <span>🌡 {temp.toFixed(1)}°F</span>}
      </div>

      {height !== null && (
        <div style={{ fontSize:11, color:'#475569' }}>
          {height.toFixed(2)}&Prime; product height
        </div>
      )}
    </div>
  )
}
