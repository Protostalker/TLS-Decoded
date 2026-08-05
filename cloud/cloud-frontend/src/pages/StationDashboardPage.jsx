import React, { useCallback, useEffect, useRef, useState } from 'react'
import { useParams } from 'react-router-dom'
import { format, parseISO } from 'date-fns'
import { api } from '../api/client.js'
import TopBar from '../components/TopBar.jsx'
import TankGauge from '../components/TankGauge.jsx'
import StalenessBadge from '../components/StalenessBadge.jsx'

const POLL_MS = 60_000

// T1 — the reused station dashboard, cloud-served: same tier the local
// station stack shows on its own LAN, just reading the cloud's mirrored
// copy instead of a local API, scoped to whichever station was picked in T2.
export default function StationDashboardPage() {
  const { id } = useParams()
  const [data, setData] = useState(null)
  const [selectedTankId, setSelectedTankId] = useState(null)
  const [error, setError] = useState(null)
  const [loading, setLoading] = useState(true)
  const timer = useRef(null)

  const load = useCallback(async () => {
    try {
      const d = await api.stationDashboard(id)
      setData(d)
      setError(null)
    } catch (e) {
      setError(e.message)
    } finally {
      setLoading(false)
    }
  }, [id])

  useEffect(() => {
    setData(null)
    setLoading(true)
    load()
    timer.current = setInterval(load, POLL_MS)
    return () => clearInterval(timer.current)
  }, [load])

  useEffect(() => {
    if (!selectedTankId && data?.tanks?.length > 0) {
      setSelectedTankId(data.tanks[0].local_id)
    }
  }, [data, selectedTankId])

  const selectedTank = data?.tanks?.find(t => t.local_id === selectedTankId) ?? null
  const selectedPrediction = data?.predictions?.find(p => p.tank_local_id === selectedTankId) ?? null

  return (
    <div style={{ minHeight: '100vh', background: '#0f1117' }}>
      <TopBar title={data?.station_name ?? 'Station'} backTo="/" />

      <main style={{ padding: 24, maxWidth: 1200, margin: '0 auto' }}>
        {loading && <div style={{ textAlign: 'center', padding: 80, color: '#475569' }}>Loading station…</div>}

        {error && !loading && (
          <div style={{
            background: '#450a0a', border: '1px solid #ef4444', borderRadius: 10,
            padding: '16px 20px', color: '#fca5a5', fontSize: 13, marginBottom: 20,
          }}>
            <strong>Error:</strong> {error}
          </div>
        )}

        {data && (
          <>
            {/* Two separate staleness signals, deliberately shown side by side —
                cloud sync lag vs. the station's own local poll lag. */}
            <div style={{ display: 'flex', gap: 12, alignItems: 'center', marginBottom: 20, flexWrap: 'wrap' }}>
              <StalenessBadge lastSyncAt={data.last_sync_at} label="Cloud data as of" />
              <span style={{ fontSize: 11, color: '#475569' }}>
                Station's own last poll:{' '}
                {data.last_poll_at ? format(parseISO(data.last_poll_at), 'MMM d, HH:mm:ss') : '—'}
                {data.last_poll_success === false && (
                  <span style={{ color: '#fca5a5' }}> (failed: {data.last_poll_error || 'unknown error'})</span>
                )}
              </span>
            </div>

            <div style={{
              display: 'flex', justifyContent: 'center', overflowX: 'auto',
              paddingBottom: 4, marginBottom: 24,
            }}>
              <div style={{ display: 'flex', gap: 16, margin: '0 auto' }}>
                {data.tanks.map(tank => {
                  const isSelected = tank.local_id === selectedTankId
                  return (
                    <div key={tank.local_id} onClick={() => setSelectedTankId(tank.local_id)} style={{
                      cursor: 'pointer',
                      outline: isSelected ? '2px solid #3b82f6' : '2px solid transparent',
                      outlineOffset: 3, borderRadius: 16, transition: 'outline 0.15s',
                    }}>
                      <TankGauge tank={tank} />
                    </div>
                  )
                })}
              </div>
            </div>

            {selectedTank && (
              <PredictionCard prediction={selectedPrediction} />
            )}

            {selectedTank && (
              <TankDetail stationId={id} tank={selectedTank} />
            )}
          </>
        )}
      </main>
    </div>
  )
}

function PredictionCard({ prediction }) {
  if (!prediction) return null
  return (
    <div style={{
      background: '#161b27', border: '1px solid #1e2130', borderRadius: 14,
      padding: 16, marginBottom: 16, display: 'flex', gap: 24, flexWrap: 'wrap', fontSize: 12,
    }}>
      <Field label="Consumption rate" value={prediction.consumption_rate_gal_per_day ? `${prediction.consumption_rate_gal_per_day.toFixed(0)} gal/day` : '—'} />
      <Field label="Days until reorder" value={prediction.days_until_reorder ?? '—'} />
      <Field label="Days until empty" value={prediction.days_until_empty ?? '—'} />
      <Field label="Confidence" value={prediction.confidence} />
      {prediction.note && <Field label="Note" value={prediction.note} />}
    </div>
  )
}

function TankDetail({ stationId, tank }) {
  const [stats, setStats] = useState(null)
  const [deliveries, setDeliveries] = useState(null)
  const [prices, setPrices] = useState(null)

  useEffect(() => {
    setStats(null); setDeliveries(null); setPrices(null)
    api.stationTankStats(stationId, tank.local_id).then(setStats).catch(() => {})
    api.stationTankDeliveries(stationId, tank.local_id).then(setDeliveries).catch(() => {})
    api.stationTankPrices(stationId, tank.local_id).then(setPrices).catch(() => {})
  }, [stationId, tank.local_id])

  return (
    <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16 }}>
      <Panel title="Stats">
        {!stats ? <Muted /> : (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 8, fontSize: 12 }}>
            <Row label="Today consumed" value={fmtGal(stats.today_consumed_gallons)} />
            <Row label="Today profit" value={fmtUsd(stats.today_profit_dollars)} />
            <Row label="7-day consumed" value={fmtGal(stats.week_consumed_gallons)} />
            <Row label="30-day avg/day" value={fmtGal(stats.avg_daily_gallons_30d)} />
            <Row label="Days since last delivery" value={stats.days_since_last_delivery ?? '—'} />
            <Row label="Water" value={stats.water_inches_latest !== null ? `${stats.water_inches_latest}"` : '—'}
                 warn={stats.water_alert} />
          </div>
        )}
      </Panel>

      <Panel title="Current pricing">
        {!prices ? <Muted /> : prices.length === 0 ? <Muted text="No pricing entered yet" /> : (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 8, fontSize: 12 }}>
            <Row label="Sale price/gal" value={`$${prices[0].sale_price_per_gallon.toFixed(3)}`} />
            <Row label="Cost/gal" value={`$${prices[0].cost_per_gallon.toFixed(3)}`} />
            <Row label="Margin/gal" value={`$${prices[0].margin_per_gallon.toFixed(3)}`} />
            <Row label="Effective" value={format(parseISO(prices[0].effective_at), 'MMM d, yyyy')} />
          </div>
        )}
      </Panel>

      <Panel title="Recent deliveries" span2>
        {!deliveries ? <Muted /> : deliveries.length === 0 ? <Muted text="No deliveries recorded yet" /> : (
          <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12 }}>
            <thead>
              <tr style={{ color: '#64748b', textAlign: 'left' }}>
                <th style={th}>Detected</th><th style={th}>Gallons received</th><th style={th}>Confirmed</th>
              </tr>
            </thead>
            <tbody>
              {deliveries.slice(0, 10).map(d => (
                <tr key={d.local_id} style={{ borderTop: '1px solid #1e2130' }}>
                  <td style={td}>{format(parseISO(d.detected_at), 'MMM d, HH:mm')}</td>
                  <td style={td}>{Math.round(d.effective_gallons_received ?? d.gallons_received ?? 0).toLocaleString()} gal</td>
                  <td style={td}>{d.confirmed ? 'Yes' : 'Pending'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Panel>
    </div>
  )
}

function Panel({ title, children, span2 }) {
  return (
    <div style={{
      background: '#161b27', border: '1px solid #1e2130', borderRadius: 14, padding: 16,
      gridColumn: span2 ? '1 / -1' : undefined,
    }}>
      <div style={{ fontSize: 12, fontWeight: 700, color: '#94a3b8', marginBottom: 12 }}>{title}</div>
      {children}
    </div>
  )
}

function Row({ label, value, warn }) {
  return (
    <div style={{ display: 'flex', justifyContent: 'space-between' }}>
      <span style={{ color: '#64748b' }}>{label}</span>
      <span style={{ color: warn ? '#fca5a5' : '#e2e8f0', fontWeight: 600 }}>{value}</span>
    </div>
  )
}

function Field({ label, value }) {
  return (
    <div>
      <div style={{ color: '#64748b', fontSize: 10 }}>{label}</div>
      <div style={{ color: '#e2e8f0', fontWeight: 700 }}>{value}</div>
    </div>
  )
}

function Muted({ text = 'Loading…' }) {
  return <div style={{ color: '#475569', fontSize: 12 }}>{text}</div>
}

const th = { padding: '6px 8px', fontWeight: 600 }
const td = { padding: '6px 8px' }

function fmtGal(v) { return v === null || v === undefined ? '—' : `${Math.round(v).toLocaleString()} gal` }
function fmtUsd(v) { return v === null || v === undefined ? '—' : `$${v.toLocaleString(undefined, { maximumFractionDigits: 2 })}` }
