import React from 'react'
import { format, parseISO } from 'date-fns'

const SEVERITY = {
  1: { color: '#f97316', bg: '#431407', label: 'System' },
  2: { color: '#ef4444', bg: '#450a0a', label: 'Tank' },
  3: { color: '#a855f7', bg: '#2e1065', label: 'Sensor' },
  6: { color: '#dc2626', bg: '#450a0a', label: 'Line Leak' },
}

function AlarmRow({ alarm, tankName }) {
  const sev = SEVERITY[alarm.category_code] ?? { color: '#94a3b8', bg: '#1e2130', label: 'Unknown' }
  const time = alarm.detected_at ? format(parseISO(alarm.detected_at), 'MMM d HH:mm') : '—'

  return (
    <div style={{
      display: 'flex', alignItems: 'center', gap: 12,
      padding: '10px 12px',
      background: sev.bg, borderRadius: 8, marginBottom: 8,
      border: `1px solid ${sev.color}33`,
    }}>
      {/* Severity dot */}
      <div style={{
        width: 10, height: 10, borderRadius: '50%',
        background: sev.color, flexShrink: 0,
        boxShadow: `0 0 6px ${sev.color}88`,
      }} />

      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ color: sev.color, fontWeight: 700, fontSize: 13 }}>
          {alarm.description ?? `Alarm ${alarm.alarm_code}`}
        </div>
        <div style={{ color: '#64748b', fontSize: 11, marginTop: 2 }}>
          {tankName ? `Tank: ${tankName}` : alarm.tank_id ? `Tank ${alarm.tank_id}` : 'System'}
          {' · '}
          {time}
        </div>
      </div>

      <span style={{
        fontSize: 10, fontWeight: 600, color: sev.color,
        border: `1px solid ${sev.color}55`,
        borderRadius: 10, padding: '2px 8px', flexShrink: 0,
      }}>
        {sev.label}
      </span>
    </div>
  )
}

export default function AlarmPanel({ alarms, tanks }) {
  const tankMap = Object.fromEntries((tanks || []).map(t => [t.id, t.name]))

  if (!alarms || alarms.length === 0) {
    return (
      <div style={{
        background: '#052e16', borderRadius: 10,
        padding: '14px 16px', border: '1.5px solid #166534',
        display: 'flex', alignItems: 'center', gap: 10,
      }}>
        <div style={{
          width: 10, height: 10, borderRadius: '50%',
          background: '#22c55e', boxShadow: '0 0 6px #22c55e88',
        }} />
        <span style={{ color: '#86efac', fontWeight: 600, fontSize: 13 }}>
          All tanks normal — no active alarms
        </span>
      </div>
    )
  }

  return (
    <div style={{
      background: '#1e2130', borderRadius: 10,
      padding: '14px 16px', border: '1.5px solid #2d3348',
    }}>
      <div style={{ fontWeight: 700, color: '#ef4444', fontSize: 14, marginBottom: 12 }}>
        ⚠ Active Alarms ({alarms.length})
      </div>
      {alarms.map(a => (
        <AlarmRow key={a.id} alarm={a} tankName={tankMap[a.tank_id]} />
      ))}
    </div>
  )
}
