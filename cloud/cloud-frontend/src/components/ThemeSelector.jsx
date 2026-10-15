import React, { useEffect, useState } from 'react'
import { THEME_MODES, getThemeMode, setThemeMode, subscribeThemeMode } from '../brandTheme.js'

// Re-renders the caller whenever the viewer switches theme.
export function useThemeMode() {
  const [mode, setMode] = useState(getThemeMode)
  useEffect(() => subscribeThemeMode(setMode), [])
  return mode
}

// Station / Dark / Light override, top right of the TopBar. Per viewer, per
// browser; never changes the station's own branding.
export default function ThemeSelector({ compact = false }) {
  const mode = useThemeMode()

  if (compact) {
    return (
      <select
        aria-label="Theme"
        value={mode}
        onChange={e => setThemeMode(e.target.value)}
        style={{
          background: 'var(--brand-surface, #1e2130)', color: 'var(--brand-text, #e2e8f0)',
          border: '1px solid var(--brand-border, #2d3348)', borderRadius: 8,
          padding: '0 8px', height: 44, fontSize: 12, cursor: 'pointer',
        }}
      >
        {THEME_MODES.map(m => <option key={m.key} value={m.key}>{m.key === 'station' ? 'Station' : m.label}</option>)}
      </select>
    )
  }

  return (
    <div role="radiogroup" aria-label="Theme" style={{
      display: 'inline-flex', border: '1px solid var(--brand-border, #2d3348)', borderRadius: 8, overflow: 'hidden',
    }}>
      {THEME_MODES.map((m, i) => {
        const active = m.key === mode
        return (
          <button
            key={m.key}
            role="radio"
            aria-checked={active}
            title={m.key === 'station' ? "Use this station's own colors" : `Force ${m.label.toLowerCase()} theme`}
            onClick={() => setThemeMode(m.key)}
            style={{
              background: active ? 'var(--brand-primary, #3b82f6)' : 'var(--brand-surface, #1e2130)',
              color: active ? '#ffffff' : 'var(--brand-text-dim, #94a3b8)',
              border: 'none', borderLeft: i ? '1px solid var(--brand-border, #2d3348)' : 'none',
              padding: '6px 10px', fontSize: 12, fontWeight: active ? 700 : 500, cursor: 'pointer',
            }}
          >{m.key === 'station' ? 'Station' : m.label}</button>
        )
      })}
    </div>
  )
}
