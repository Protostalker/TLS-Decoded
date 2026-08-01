const BASE = '/api'

async function request(path, opts = {}) {
  const res = await fetch(`${BASE}${path}`, {
    headers: { 'Content-Type': 'application/json', ...opts.headers },
    ...opts,
  })
  if (!res.ok) {
    const text = await res.text().catch(() => '')
    throw new Error(`API ${res.status}: ${text}`)
  }
  return res.json()
}

export const api = {
  health: () => request('/health'),

  dashboard: () => request('/dashboard'),

  tanks: () => request('/tanks'),

  tank: (id) => request(`/tanks/${id}`),

  readings: (tankId, { from, to, limit = 500 } = {}) => {
    const params = new URLSearchParams()
    if (from) params.set('from', from.toISOString())
    if (to) params.set('to', to.toISOString())
    params.set('limit', String(limit))
    return request(`/tanks/${tankId}/readings?${params}`)
  },

  prediction: (tankId) => request(`/tanks/${tankId}/prediction`),

  deliveries: (tankId) => request(`/tanks/${tankId}/deliveries`),

  confirmDelivery: (deliveryId, gallonsReceived, note) => request(`/deliveries/${deliveryId}`, {
    method: 'PUT',
    body: JSON.stringify({ gallons_received: gallonsReceived, note }),
  }),

  logManualDelivery: (tankId, { gallonsReceived, detectedAt, note }) =>
    request(`/tanks/${tankId}/deliveries`, {
      method: 'POST',
      body: JSON.stringify({
        gallons_received: gallonsReceived,
        detected_at: detectedAt ? new Date(detectedAt).toISOString() : undefined,
        note,
      }),
    }),

  consumption: (tankId, { limit = 15 } = {}) =>
    request(`/tanks/${tankId}/consumption?limit=${limit}`),

  stats: (tankId) => request(`/tanks/${tankId}/stats`),

  updateTank: (tankId, patch) => request(`/tanks/${tankId}`, {
    method: 'PUT',
    body: JSON.stringify(patch),
  }),

  alarms: () => request('/alarms'),

  alarmHistory: () => request('/alarms/history'),

  settings: () => request('/settings'),

  updateSettings: (patch) => request('/settings', {
    method: 'PUT',
    body: JSON.stringify(patch),
  }),

  pollNow: () => request('/settings/poll-now', { method: 'POST' }),

  regenerateDeviceId: () => request('/settings/device-id/regenerate', { method: 'POST' }),

  exportUrl: (tankId, year, month) =>
    `${BASE}/tanks/${tankId}/export?year=${year}&month=${month}`,

  exportAllUrl: (year, month) =>
    `${BASE}/export?year=${year}&month=${month}`,

  exportMonthlySummaryUrl: (year, month) =>
    `${BASE}/export/monthly-summary?year=${year}&month=${month}`,
}
