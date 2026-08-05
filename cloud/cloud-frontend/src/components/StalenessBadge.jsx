import React from 'react'
import { formatDistanceToNow, parseISO } from 'date-fns'

/**
 * "data as of {last sync time}" indicator — deliberately separate from a
 * station's own local "last poll" indicator (poll lag vs. sync lag are two
 * different staleness signals; see CLOUD-ARCHITECTURE.md's data-flow notes).
 */
export default function StalenessBadge({ lastSyncAt, label = 'Cloud data as of' }) {
  if (!lastSyncAt) {
    return (
      <span style={{
        display: 'inline-flex', alignItems: 'center', gap: 6, fontSize: 11,
        color: '#fca5a5', background: '#450a0a', border: '1px solid #7f1d1d',
        borderRadius: 999, padding: '4px 10px',
      }}>
        <Dot color="#ef4444" /> Never synced from this station yet
      </span>
    )
  }

  const date = parseISO(lastSyncAt)
  const ageMs = Date.now() - date.getTime()
  const stale = ageMs > 90 * 60 * 1000  // > 3x the default 30min cadence
  const color = stale ? '#f59e0b' : '#22c55e'

  return (
    <span title={date.toLocaleString()} style={{
      display: 'inline-flex', alignItems: 'center', gap: 6, fontSize: 11,
      color: stale ? '#fbbf24' : '#86efac',
      background: stale ? '#451a03' : '#052e16',
      border: `1px solid ${stale ? '#78350f' : '#14532d'}`,
      borderRadius: 999, padding: '4px 10px',
    }}>
      <Dot color={color} /> {label} {formatDistanceToNow(date, { addSuffix: true })}
    </span>
  )
}

function Dot({ color }) {
  return (
    <span style={{
      width: 7, height: 7, borderRadius: '50%', background: color,
      boxShadow: `0 0 5px ${color}88`, display: 'inline-block',
    }} />
  )
}
