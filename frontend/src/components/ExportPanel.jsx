import React, { useState } from 'react'
import { api } from '../api/client.js'

function currentMonthValue() {
  const d = new Date()
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`
}

function download(url) {
  const a = document.createElement('a')
  a.href = url
  a.rel = 'noopener'
  document.body.appendChild(a)
  a.click()
  a.remove()
}

const btnStyle = {
  padding: '7px 14px', borderRadius: 7, cursor: 'pointer',
  border: '1px solid var(--brand-border, #2d3348)', fontSize: 12, fontWeight: 600,
  background: 'var(--brand-border, #2d3348)', color: 'var(--brand-text, #cbd5e1)',
}

export default function ExportPanel({ tank }) {
  const [month, setMonth] = useState(currentMonthValue())

  const [year, mo] = month.split('-').map(Number)

  return (
    <div style={{
      background: 'var(--brand-surface, #1e2130)', borderRadius: 12,
      padding: '16px', border: '1.5px solid var(--brand-border, #2d3348)',
      display: 'flex', alignItems: 'center', gap: 12, flexWrap: 'wrap',
    }}>
      <div style={{ fontWeight: 700, fontSize: 13, color: 'var(--brand-text, #e2e8f0)', marginRight: 4 }}>
        Export monthly readings
      </div>

      <input
        type="month"
        value={month}
        onChange={e => setMonth(e.target.value)}
        style={{
          background: 'var(--brand-well, #111827)', border: '1px solid var(--brand-border-soft, #374151)', borderRadius: 6,
          color: 'var(--brand-text, #e2e8f0)', fontSize: 12, padding: '6px 10px',
        }}
      />

      <button
        style={btnStyle}
        disabled={!tank}
        onClick={() => tank && download(api.exportUrl(tank.id, year, mo))}
      >
        ↓ {tank ? tank.name : 'Tank'} CSV
      </button>

      <button
        style={{ ...btnStyle, background: '#1d4ed833', border: '1px solid #3b82f655', color: '#93c5fd' }}
        onClick={() => download(api.exportAllUrl(year, mo))}
      >
        ↓ All Tanks CSV
      </button>

      <button
        style={{ ...btnStyle, background: '#05301633', border: '1px solid #22c55e55', color: '#86efac' }}
        onClick={() => download(api.exportMonthlySummaryUrl(year, mo))}
        title="Day-by-day GAL / ADDED / SOLD ledger, shaped like the existing spreadsheet"
      >
        ↓ Monthly Ledger CSV
      </button>
    </div>
  )
}
