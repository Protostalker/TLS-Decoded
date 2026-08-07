import React from 'react'
import { format, parseISO } from 'date-fns'

const CONFIDENCE_COLORS = {
  low: { bg: '#451a1a', text: '#fca5a5', label: 'Low' },
  medium: { bg: '#422006', text: '#fcd34d', label: 'Medium' },
  high: { bg: '#052e16', text: '#86efac', label: 'High' },
}

function StatRow({ label, value, accent }) {
  return (
    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', padding: '5px 0', borderBottom: '1px solid var(--brand-border, #2d3348)' }}>
      <span style={{ color: 'var(--brand-text-dimmer, #64748b)', fontSize: 12 }}>{label}</span>
      <span style={{ color: accent || 'var(--brand-text, #e2e8f0)', fontWeight: 600, fontSize: 13 }}>
        {value ?? '—'}
      </span>
    </div>
  )
}

export default function PredictionCard({ prediction }) {
  if (!prediction) return null

  const conf = CONFIDENCE_COLORS[prediction.confidence] ?? CONFIDENCE_COLORS.low

  const reorderDate = prediction.projected_reorder_date
    ? format(parseISO(prediction.projected_reorder_date), 'MMM d, yyyy')
    : null

  const daysReorder = prediction.days_until_reorder != null
    ? `${prediction.days_until_reorder.toFixed(1)} days`
    : null

  const daysEmpty = prediction.days_until_empty != null
    ? `${prediction.days_until_empty.toFixed(1)} days`
    : null

  const rateDay = prediction.consumption_rate_gal_per_day != null
    ? `${prediction.consumption_rate_gal_per_day.toLocaleString(undefined, { maximumFractionDigits: 1 })} gal/day`
    : null

  return (
    <div style={{
      background: 'var(--brand-surface, #1a1f2e)',
      borderRadius: 10,
      padding: '14px 16px',
      border: '1.5px solid var(--brand-border, #2d3348)',
      minWidth: 200,
      flex: 1,
    }}>
      {/* Header row */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 10 }}>
        <span style={{ fontWeight: 700, color: 'var(--brand-text-dim, #94a3b8)', fontSize: 12, textTransform: 'uppercase', letterSpacing: 0.5 }}>
          Forecast
        </span>
        <span style={{
          background: conf.bg, color: conf.text,
          fontSize: 10, fontWeight: 700, padding: '2px 8px',
          borderRadius: 20, textTransform: 'uppercase', letterSpacing: 0.5,
        }}>
          {conf.label} confidence
        </span>
      </div>

      {prediction.note ? (
        <div style={{ color: 'var(--brand-text-dimmer, #64748b)', fontSize: 12, padding: '8px 0' }}>{prediction.note}</div>
      ) : (
        <>
          {/* Prominent: days until reorder */}
          <div style={{ textAlign: 'center', padding: '10px 0 8px' }}>
            <div style={{ fontSize: 36, fontWeight: 800, color: daysReorder ? '#f59e0b' : 'var(--brand-text-dimmer, #64748b)', lineHeight: 1 }}>
              {prediction.days_until_reorder != null ? Math.floor(prediction.days_until_reorder) : '—'}
            </div>
            <div style={{ color: 'var(--brand-text-dimmer, #64748b)', fontSize: 11, marginTop: 4 }}>days until reorder</div>
          </div>

          <StatRow label="Days until empty" value={daysEmpty} />
          <StatRow label="Reorder date" value={reorderDate} accent="#f59e0b" />
          <StatRow label="Consumption" value={rateDay} />
        </>
      )}
    </div>
  )
}
