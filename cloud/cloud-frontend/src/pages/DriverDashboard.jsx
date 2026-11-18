/**
 * Driver Dashboard — a driver's own view of their day. Deliberately small:
 * just the runs assigned to them (DeliveryRun.driver_user_id), each stop's
 * status and progress, and a "Mark arrived" action identical in effect to
 * the supplier's own Fleet page (routers/driver.py reuses fleet.py's
 * arrive_stop_core so behavior matches byte-for-byte). No pricing, no
 * other stations, no fleet management — see routers/driver.py.
 */
import React, { useEffect, useState } from 'react'
import { api } from '../api/client.js'
import TopBar from '../components/TopBar.jsx'
import Footer from '../components/Footer.jsx'

const card = { background: 'var(--brand-surface-2, #161b27)', border: '1px solid var(--brand-border-soft, #1e2130)', borderRadius: 14, padding: 18, marginBottom: 16 }
const btn = { background: '#3b82f6', border: 'none', borderRadius: 8, padding: '8px 14px', color: '#fff', fontSize: 13, fontWeight: 600, cursor: 'pointer' }

export default function DriverDashboard() {
  const [runs, setRuns] = useState(null)
  const [report, setReport] = useState(null)
  const [error, setError] = useState(null)

  const load = () => {
    api.driver.runs().then(setRuns).catch(e => setError(e.message))
    api.driver.todayReport().then(setReport).catch(() => {})
  }
  useEffect(load, [])

  const arrive = async (runId, stopId) => {
    try { await api.driver.arriveStop(runId, stopId); load() } catch (e) { setError(e.message) }
  }

  return (
    <div style={{ minHeight: '100vh', background: 'var(--brand-bg, #0f1117)' }}>
      <TopBar title="My Deliveries" />
      <main style={{ padding: 24, maxWidth: 800, margin: '0 auto' }}>

        {report && <TodaySummary report={report} />}

        {error && <ErrorBox message={error} />}

        {runs === null && !error && (
          <div style={{ color: 'var(--brand-text-dimmer, #64748b)', padding: 40, textAlign: 'center' }}>Loading…</div>
        )}

        {runs?.length === 0 && (
          <div style={{ ...card, color: 'var(--brand-text-faint, #475569)', textAlign: 'center' }}>
            No deliveries assigned to you right now.
          </div>
        )}

        {runs?.map(r => <RunCard key={r.id} run={r} onArrive={arrive} />)}
      </main>
      <Footer />
    </div>
  )
}

function TodaySummary({ report }) {
  const products = Object.entries(report.gallons_delivered_by_product || {})
  return (
    <div style={{ ...card, display: 'flex', gap: 24, flexWrap: 'wrap', alignItems: 'center' }}>
      <Stat label="Completed today" value={report.completed_stops} color="#86efac" />
      <Stat label="Still ahead" value={report.pending_stops} color="#93c5fd" />
      {products.length > 0 && (
        <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap' }}>
          {products.map(([product, gal]) => (
            <div key={product} style={{ fontSize: 12, color: 'var(--brand-text-dim, #94a3b8)' }}>
              <span style={{ fontWeight: 700, color: 'var(--brand-text, #e2e8f0)' }}>{Math.round(gal).toLocaleString()}</span> gal {product} delivered
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

function Stat({ label, value, color }) {
  return (
    <div>
      <div style={{ fontSize: 24, fontWeight: 800, color }}>{value}</div>
      <div style={{ fontSize: 11, color: 'var(--brand-text-dimmer, #64748b)' }}>{label}</div>
    </div>
  )
}

function RunCard({ run, onArrive }) {
  const nextStop = run.stops.find(s => s.status !== 'delivered')
  const totalDistance = run.stops.reduce((sum, s) => sum + (s.distance_km || 0), 0)
  const totalMinutes = run.stops.reduce((sum, s) => sum + (s.eta_minutes || 0), 0)
  const delivered = run.stops.filter(s => s.status === 'delivered').length

  return (
    <div style={card}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', marginBottom: 10, flexWrap: 'wrap', gap: 6 }}>
        <div style={{ fontWeight: 700 }}>Run #{run.id}</div>
        <div style={{ fontSize: 11, color: 'var(--brand-text-dimmer, #64748b)', display: 'flex', gap: 10, alignItems: 'center' }}>
          <span>{delivered}/{run.stops.length} stops</span>
          {totalDistance > 0 && <span>· {Math.round(totalDistance)} km</span>}
          {totalMinutes > 0 && <span>· ~{Math.round(totalMinutes)} min total</span>}
          <span>{run.status}</span>
        </div>
      </div>
      {run.stops.map(stop => (
        <div key={stop.id} style={{
          borderTop: '1px solid var(--brand-border-soft, #1e2130)', padding: '10px 0',
          opacity: stop.status === 'delivered' ? 0.6 : 1,
        }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: 8 }}>
            <div>
              <span style={{ fontWeight: 600 }}>Stop {stop.stop_order + 1}: {stop.station_name}</span>
              <span style={{
                marginLeft: 8, fontSize: 10, padding: '2px 8px', borderRadius: 10,
                background: stop.status === 'delivered' ? '#052e16' : stop.status === 'in_transit' ? '#1e3a5f' : '#1e2130',
                color: stop.status === 'delivered' ? '#86efac' : stop.status === 'in_transit' ? '#93c5fd' : '#64748b',
              }}>{stop.status}</span>
              {stop === nextStop && stop.status !== 'delivered' && (
                <span style={{ marginLeft: 8, fontSize: 10, color: '#fde68a' }}>← up next</span>
              )}
            </div>
            {stop.status === 'in_transit' && (
              <button onClick={() => onArrive(run.id, stop.id)} style={btn}>Mark arrived</button>
            )}
          </div>
          {stop.delivery && (
            <div style={{ marginTop: 8 }}>
              <div style={{ background: '#0f1117', borderRadius: 4, height: 6, overflow: 'hidden' }}>
                <div style={{
                  width: `${Math.round(Math.min(stop.delivery.progress_pct, 1) * 100)}%`, height: '100%',
                  background: stop.delivery.running_late ? '#f59e0b' : '#60a5fa', borderRadius: 4,
                }} />
              </div>
              <div style={{ fontSize: 10, color: 'var(--brand-text-dimmer, #64748b)', marginTop: 3 }}>
                {stop.delivery.running_late ? 'Running late vs. estimate' : `~${Math.round(Math.min(stop.delivery.progress_pct, 1) * 100)}% of the way there`}
                {' '}· ~{Math.round(stop.delivery.eta_minutes)} min leg
              </div>
            </div>
          )}
          <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', marginTop: 8 }}>
            {stop.items.map(i => (
              <span key={i.id} style={{ fontSize: 11, color: 'var(--brand-text-dim, #94a3b8)', background: 'var(--brand-bg, #0f1117)', border: '1px solid var(--brand-border, #2d3348)', borderRadius: 6, padding: '3px 8px' }}>
                {i.product}: {Math.round(i.gallons_delivered ?? i.gallons_planned).toLocaleString()} gal{i.gallons_delivered == null ? ' (planned)' : ''}
              </span>
            ))}
          </div>
        </div>
      ))}
    </div>
  )
}

function ErrorBox({ message }) {
  return <div style={{ background: 'var(--brand-danger-bg, #450a0a)', border: '1px solid #ef4444', borderRadius: 10, padding: '10px 14px', color: 'var(--brand-danger-text, #fca5a5)', fontSize: 12, marginBottom: 16 }}>{message}</div>
}
