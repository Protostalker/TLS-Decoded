import React, { useEffect, useState, useCallback, useRef } from 'react'
import { format, parseISO } from 'date-fns'
import { api } from '../api/client.js'
import TankGauge from './TankGauge.jsx'
import FuelChart from './FuelChart.jsx'
import PredictionCard from './PredictionCard.jsx'
import ReadingsTable from './ReadingsTable.jsx'
import ConsumptionPanel from './ConsumptionPanel.jsx'
import DeliveryPanel from './DeliveryPanel.jsx'
import StatsPanel from './StatsPanel.jsx'
import PricingPanel from './PricingPanel.jsx'
import ExportPanel from './ExportPanel.jsx'
import SettingsPanel from './SettingsPanel.jsx'
import useIsMobile from '../hooks/useIsMobile.js'

const POLL_MS = 60_000

export default function Dashboard() {
  const [data, setData]               = useState(null)
  const [selectedTankId, setSelected] = useState(null)
  const [error, setError]             = useState(null)
  const [loading, setLoading]         = useState(true)
  const [settingsOpen, setSettingsOpen] = useState(false)
  const timer                         = useRef(null)
  const isMobile                      = useIsMobile()

  // NOTE: this must stay dependency-free (no selectedTankId here). It used to
  // read selectedTankId to decide whether to default-select a tank, but since
  // this callback is only ever created once (deps: []) and then reused by
  // setInterval every POLL_MS, that read was a stale closure — it always saw
  // the *initial* (null) value of selectedTankId, not the current one. That
  // made the "default to first tank" branch fire on *every* poll tick
  // forever, silently snapping the selection back to tank #1 (Unleaded) out
  // from under whatever the user had picked — including mid-keystroke while
  // filling out a form for a different tank. The default-selection logic now
  // lives in its own effect below, which correctly re-reads current state.
  const load = useCallback(async () => {
    try {
      const d = await api.dashboard()
      setData(d)
      setError(null)
    } catch (e) {
      setError(e.message)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    load()
    timer.current = setInterval(load, POLL_MS)
    return () => clearInterval(timer.current)
  }, [load])

  // Default to the first tank once data arrives — but only if nothing is
  // selected yet, so this never overrides a user's existing selection.
  useEffect(() => {
    if (!selectedTankId && data?.tanks?.length > 0) {
      setSelected(data.tanks[0].id)
    }
  }, [data, selectedTankId])

  const selectedTank       = data?.tanks?.find(t => t.id === selectedTankId) ?? null
  const selectedPrediction = data?.predictions?.find(p => p.tank_id === selectedTankId) ?? null

  const lastPoll = data?.last_poll_at
    ? format(parseISO(data.last_poll_at), 'MMM d, HH:mm:ss')
    : '—'

  return (
    <div style={{ minHeight:'100vh', background:'#0f1117', color:'#e2e8f0' }}>

      {/* Top bar */}
      <header style={{
        background:'#161b27', borderBottom:'1px solid #1e2130',
        padding:'0 24px', height:60,
        display:'flex', alignItems:'center', justifyContent:'space-between',
      }}>
        <div style={{ display:'flex', alignItems:'center', gap:14 }}>
          <div style={{
            width:32, height:32, borderRadius:8,
            background:'linear-gradient(135deg,#3b82f6,#6366f1)',
            display:'flex', alignItems:'center', justifyContent:'center',
            fontSize:18, fontWeight:800, color:'#fff',
          }}>T</div>
          <div>
            <div style={{ fontWeight:800, fontSize:16, letterSpacing:-0.3 }}>
              {data?.station_name ?? 'TLS-Decoded'}
            </div>
            <div style={{ fontSize:10, color:'#475569' }}>Fuel Tank Monitor</div>
          </div>
        </div>

        <div style={{ display:'flex', alignItems:'center', gap:16 }}>
          <div style={{ fontSize:11, color:'#475569' }}>
            Last poll: <span style={{ color:'#64748b' }}>{lastPoll}</span>
          </div>
          <div style={{ display:'flex', alignItems:'center', gap:6 }}>
            <div style={{
              width:8, height:8, borderRadius:'50%',
              background: error ? '#ef4444' : '#22c55e',
              boxShadow: error ? '0 0 5px #ef444488' : '0 0 5px #22c55e88',
            }} />
            <span style={{ fontSize:11, color:'#475569' }}>{error ? 'Error' : 'Live'}</span>
          </div>
          <button
            onClick={() => setSettingsOpen(true)}
            title="Settings"
            style={{
              background:'#1e2130', border:'1px solid #2d3348', borderRadius:8,
              width:32, height:32, cursor:'pointer', color:'#94a3b8', fontSize:15,
              display:'flex', alignItems:'center', justifyContent:'center',
            }}
          >⚙</button>
        </div>
      </header>

      <SettingsPanel open={settingsOpen} onClose={() => setSettingsOpen(false)} />

      <main style={{ padding: isMobile ? '16px 12px' : '24px', maxWidth:1400, margin:'0 auto' }}>

        {loading && (
          <div style={{ textAlign:'center', padding:80, color:'#475569', fontSize:16 }}>
            Connecting to tank gauge…
          </div>
        )}

        {error && !loading && (
          <div style={{
            background:'#450a0a', border:'1px solid #ef4444',
            borderRadius:10, padding:'16px 20px', color:'#fca5a5',
            fontSize:13, marginBottom:20,
          }}>
            <strong>API Error:</strong> {error} — retrying automatically…
          </div>
        )}

        {data && data.last_poll_success === false && (
          <div style={{
            background:'#450a0a', border:'1px solid #ef4444',
            borderRadius:10, padding:'14px 18px', color:'#fca5a5',
            fontSize:12, marginBottom:20,
          }}>
            <strong>Last poll failed</strong> ({data.last_poll_at ? format(parseISO(data.last_poll_at), 'MMM d, HH:mm:ss') : 'unknown time'}):
            <div style={{ fontFamily:'monospace', marginTop:6, wordBreak:'break-word', color:'#fecaca' }}>
              {data.last_poll_error || 'No error message recorded.'}
            </div>
            <div style={{ marginTop:8, fontSize:11, color:'#94a3b8' }}>
              Full history in Settings (⚙) → Poll log.
            </div>
          </div>
        )}

        {data && (
          <>
            {isMobile ? (
              <>
                {/* Mobile: tappable 2x2 grid of tank squares, no inline forecast */}
                <div style={{
                  display:'grid', gridTemplateColumns:'1fr 1fr', gap:12, marginBottom:20,
                }}>
                  {data.tanks.map(tank => {
                    const isSelected = tank.id === selectedTankId
                    return (
                      <div key={tank.id} onClick={() => setSelected(tank.id)} style={{
                        cursor:'pointer',
                        outline: isSelected ? '2px solid #3b82f6' : '2px solid transparent',
                        outlineOffset:3, borderRadius:18, transition:'outline 0.15s',
                      }}>
                        <TankGauge tank={tank} />
                      </div>
                    )
                  })}
                </div>

                {/* Forecast for whichever tank is selected above */}
                {selectedTank && (
                  <div style={{ marginBottom:20 }}>
                    <PredictionCard prediction={selectedPrediction} />
                  </div>
                )}
              </>
            ) : (
              /* Desktop: centered row, horizontally scrollable when it overflows */
              <div style={{
                display:'flex', justifyContent:'center', overflowX:'auto',
                paddingBottom:4, marginBottom:28, scrollSnapType:'x proximity',
              }}>
                <div style={{ display:'flex', gap:16, margin:'0 auto' }}>
                  {data.tanks.map(tank => {
                    const pred      = data.predictions?.find(p => p.tank_id === tank.id)
                    const isSelected = tank.id === selectedTankId
                    return (
                      <div key={tank.id} onClick={() => setSelected(tank.id)} style={{
                        cursor:'pointer', display:'flex', flexDirection:'column', gap:10,
                        outline: isSelected ? '2px solid #3b82f6' : '2px solid transparent',
                        outlineOffset:3, borderRadius:14, transition:'outline 0.15s',
                        flexShrink:0, scrollSnapAlign:'center',
                      }}>
                        <TankGauge tank={tank} />
                        <PredictionCard prediction={pred} />
                      </div>
                    )
                  })}
                </div>
              </div>
            )}

            {/* History chart for selected tank */}
            {selectedTank && <FuelChart tank={selectedTank} />}

            {/* Fun stats + pricing/margin, side by side */}
            {selectedTank && (
              <div style={{
                display:'grid',
                gridTemplateColumns: isMobile ? '1fr' : '1fr 1fr',
                gap:16, marginTop:16,
              }}>
                <StatsPanel tank={selectedTank} />
                <PricingPanel tank={selectedTank} />
              </div>
            )}

            {/* Recent readings */}
            {selectedTank && (
              <div style={{ marginTop:16 }}>
                <ReadingsTable tank={selectedTank} />
              </div>
            )}

            {/* Consumption rate + refuel (delivery) history, side by side */}
            {selectedTank && (
              <div style={{
                display:'grid',
                gridTemplateColumns: isMobile ? '1fr' : '1fr 1fr',
                gap:16, marginTop:16,
              }}>
                <ConsumptionPanel tank={selectedTank} />
                <DeliveryPanel tank={selectedTank} />
              </div>
            )}

            {/* Export */}
            <div style={{ marginTop:16 }}>
              <ExportPanel tank={selectedTank} />
            </div>
          </>
        )}
      </main>
    </div>
  )
}
