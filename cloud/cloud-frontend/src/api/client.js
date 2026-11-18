const BASE = '/api'
const TOKEN_KEY = 'tls_cloud_session_token'

// The primary auth path is the httpOnly cookie the login endpoint sets
// (works automatically for same-origin requests, which is how nginx serves
// this in production/Docker — see cloud/README.md). The token is *also*
// kept here and sent as a Bearer header so `npm run dev` still works when
// the Vite dev server and cloud-api are on different origins/ports and the
// browser won't send a cross-origin cookie.
function getToken() { return localStorage.getItem(TOKEN_KEY) }
function setToken(t) { t ? localStorage.setItem(TOKEN_KEY, t) : localStorage.removeItem(TOKEN_KEY) }

async function request(path, opts = {}) {
  const token = getToken()
  const res = await fetch(`${BASE}${path}`, {
    headers: {
      'Content-Type': 'application/json',
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...opts.headers,
    },
    credentials: 'include',   // send/receive the httpOnly session cookie
    ...opts,
  })
  if (!res.ok) {
    let detail = ''
    try { detail = (await res.json()).detail } catch { /* ignore */ }
    const err = new Error(detail || `${res.status}`)
    err.status = res.status
    throw err
  }
  if (res.status === 204) return null
  return res.json()
}

export const api = {
  // ── Session token (exposed for AuthContext's admin-impersonation
  // switch — swapping tokens without a real login/logout round trip) ──
  getSessionToken: () => getToken(),
  setSessionToken: (t) => setToken(t),

  // ── Auth ──
  login: async (email, password, duration) => {
    const result = await request('/auth/login', { method: 'POST', body: JSON.stringify({ email, password, duration }) })
    setToken(result.token)
    return result
  },
  logout: async () => {
    try { await request('/auth/logout', { method: 'POST' }) } finally { setToken(null) }
  },
  magicLogin: async (token) => {
    const result = await request('/auth/magic-login', { method: 'POST', body: JSON.stringify({ token }) })
    setToken(result.token)
    return result
  },
  me: () => request('/auth/me'),
  mySessions: () => request('/auth/sessions'),
  revokeMySession: (id) => request(`/auth/sessions/${id}`, { method: 'DELETE' }),

  // ── T2: stations + combined stats ──
  myStations: () => request('/me/stations'),
  combinedStats: () => request('/me/stats/summary'),
  weatherSummary: () => request('/me/weather-summary'),

  // ── T1: station-scoped ──
  stationDashboard: (id) => request(`/stations/${id}/dashboard`),
  stationTanks: (id) => request(`/stations/${id}/tanks`),
  stationTankReadings: (id, tankLocalId, limit = 300) =>
    request(`/stations/${id}/tanks/${tankLocalId}/readings?limit=${limit}`),
  stationTankDeliveries: (id, tankLocalId) => request(`/stations/${id}/tanks/${tankLocalId}/deliveries`),
  stationTankPrices: (id, tankLocalId) => request(`/stations/${id}/tanks/${tankLocalId}/prices`),
  stationTankStats: (id, tankLocalId) => request(`/stations/${id}/tanks/${tankLocalId}/stats`),
  stationStatsSummary: (id) => request(`/stations/${id}/stats/summary`),
  stationWeather: (id) => request(`/stations/${id}/weather`),
  stationForecast: (id, range = '24h') => request(`/stations/${id}/forecast?range=${encodeURIComponent(range)}`),
  stationsMap: () => request('/stations/map'),
  submitPriceUpdate: (id, tankLocalId, body) =>
    request(`/stations/${id}/tanks/${tankLocalId}/price-updates`, { method: 'POST', body: JSON.stringify(body) }),
  priceUpdates: (id) => request(`/stations/${id}/price-updates`),

  // ── T1: tank config / grade corrections (admin only, cloud -> station) ──
  submitTankConfigUpdate: (id, tankLocalId, body) =>
    request(`/stations/${id}/tanks/${tankLocalId}/config-updates`, { method: 'POST', body: JSON.stringify(body) }),
  reorderTanks: (id, orderedTankLocalIds, note) =>
    request(`/stations/${id}/tanks/reorder`, { method: 'POST', body: JSON.stringify({ ordered_tank_local_ids: orderedTankLocalIds, note }) }),
  tankUpdates: (id) => request(`/stations/${id}/tank-updates`),
  setCloudLabel: (id, tankLocalId, body) =>
    request(`/stations/${id}/tanks/${tankLocalId}/cloud-label`, { method: 'PUT', body: JSON.stringify(body) }),
  clearCloudLabel: (id, tankLocalId) =>
    request(`/stations/${id}/tanks/${tankLocalId}/cloud-label`, { method: 'DELETE' }),
  cloudReorderTanks: (id, orderedTankLocalIds, note) =>
    request(`/stations/${id}/tanks/cloud-reorder`, { method: 'POST', body: JSON.stringify({ ordered_tank_local_ids: orderedTankLocalIds, note }) }),
  clearCloudOrder: (id) =>
    request(`/stations/${id}/tanks/cloud-order`, { method: 'DELETE' }),

  // ── Supplier ──
  supplier: {
    stations: () => request('/supplier/stations'),
    // body: { eta_note, origin_address } — both optional. origin_address
    // (new, for the delivery-timer phase) triggers a best-effort geocode +
    // route estimate server-side; omit it for the old free-text-only flow.
    markOrdered: (stationId, body) =>
      request(`/supplier/stations/${stationId}/order`, { method: 'POST', body: JSON.stringify(body) }),
  },

  // ── Fleet: loading racks, tankers, loads, daisy-chain delivery runs ──
  fleet: {
    racks: () => request('/fleet/racks'),
    createRack: (body) => request('/fleet/racks', { method: 'POST', body: JSON.stringify(body) }),
    updateRack: (id, body) => request(`/fleet/racks/${id}`, { method: 'PUT', body: JSON.stringify(body) }),
    deleteRack: (id) => request(`/fleet/racks/${id}`, { method: 'DELETE' }),

    tankers: () => request('/fleet/tankers'),
    createTanker: (body) => request('/fleet/tankers', { method: 'POST', body: JSON.stringify(body) }),
    addCompartment: (tankerId, body) => request(`/fleet/tankers/${tankerId}/compartments`, { method: 'POST', body: JSON.stringify(body) }),
    deleteTanker: (id) => request(`/fleet/tankers/${id}`, { method: 'DELETE' }),

    loads: (openOnly = true) => request(`/fleet/loads?open_only=${openOnly}`),
    createLoad: (body) => request('/fleet/loads', { method: 'POST', body: JSON.stringify(body) }),
    deleteLoad: (id) => request(`/fleet/loads/${id}`, { method: 'DELETE' }),

    runs: (activeOnly = true) => request(`/fleet/runs?active_only=${activeOnly}`),
    createRun: (body) => request('/fleet/runs', { method: 'POST', body: JSON.stringify(body) }),
    arriveStop: (runId, stopId, body = { items: [] }) =>
      request(`/fleet/runs/${runId}/stops/${stopId}/arrive`, { method: 'POST', body: JSON.stringify(body) }),
    deleteRun: (id) => request(`/fleet/runs/${id}`, { method: 'DELETE' }),

    drivers: () => request('/fleet/drivers'),

    reports: {
      daily: (days = 7) => request(`/fleet/reports/daily?days=${days}`),
      shipments: (days = 30) => request(`/fleet/reports/shipments?days=${days}`),
    },
  },

  // ── Driver: a driver's own assigned runs ──
  driver: {
    runs: () => request('/driver/runs'),
    run: (id) => request(`/driver/runs/${id}`),
    arriveStop: (runId, stopId, body = { items: [] }) =>
      request(`/driver/runs/${runId}/stops/${stopId}/arrive`, { method: 'POST', body: JSON.stringify(body) }),
    todayReport: () => request('/driver/reports/today'),
  },

  // ── Notifications ──
  notifications: () => request('/notifications'),
  markNotificationRead: (id) => request(`/notifications/${id}/read`, { method: 'POST' }),
  markAllNotificationsRead: () => request('/notifications/read-all', { method: 'POST' }),

  // ── License (T3 admin gets full status; everyone gets the banner) ──
  license: {
    banner: () => request('/license/banner'),
    status: () => request('/license/status'),
    recheck: () => request('/license/recheck', { method: 'POST' }),
    config: () => request('/license/config'),
    activate: (passphrase) =>
      request('/license/activate', { method: 'POST', body: JSON.stringify({ passphrase }) }),
    deactivate: () => request('/license/deactivate', { method: 'POST' }),
  },

  // ── Web Push ──
  push: {
    vapidPublicKey: () => request('/push/vapid-public-key'),
    subscribe: (subscriptionJson) =>
      request('/push/subscribe', { method: 'POST', body: JSON.stringify({ subscription_json: subscriptionJson }) }),
    unsubscribe: (subscriptionJson) =>
      request('/push/unsubscribe', { method: 'DELETE', body: JSON.stringify({ subscription_json: subscriptionJson }) }),
  },

  // ── T3: admin ──
  admin: {
    customers: () => request('/admin/customers'),
    createCustomer: (body) => request('/admin/customers', { method: 'POST', body: JSON.stringify(body) }),

    stations: () => request('/admin/stations'),
    createStation: (body) => request('/admin/stations', { method: 'POST', body: JSON.stringify(body) }),
    updateStation: (id, body) => request(`/admin/stations/${id}`, { method: 'PUT', body: JSON.stringify(body) }),
    rotateCredential: (id) => request(`/admin/stations/${id}/rotate-credential`, { method: 'POST' }),
    requestUpdateCheck: (id) => request(`/admin/stations/${id}/request-update-check`, { method: 'POST' }),
    geocode: (address) => request('/admin/geocode', { method: 'POST', body: JSON.stringify({ address }) }),

    users: () => request('/admin/users'),
    createUser: (body) => request('/admin/users', { method: 'POST', body: JSON.stringify(body) }),
    updateUser: (id, body) => request(`/admin/users/${id}`, { method: 'PUT', body: JSON.stringify(body) }),
    setUserPassword: (userId, password) => request(`/admin/users/${userId}/set-password`, { method: 'POST', body: JSON.stringify({ password }) }),
    generateMagicLink: (userId) => request(`/admin/users/${userId}/magic-link`, { method: 'POST' }),
    impersonate: (userId) => request(`/admin/users/${userId}/impersonate`, { method: 'POST' }),

    createAssignment: (userId, stationId) =>
      request('/admin/assignments', { method: 'POST', body: JSON.stringify({ user_id: userId, station_id: stationId }) }),
    deleteAssignment: (userId, stationId) =>
      request(`/admin/assignments?user_id=${userId}&station_id=${stationId}`, { method: 'DELETE' }),

    userSessions: (userId) => request(`/admin/users/${userId}/sessions`),
    revokeSession: (sessionId) => request(`/admin/sessions/${sessionId}`, { method: 'DELETE' }),
    revokeAllUserSessions: (userId) => request(`/admin/users/${userId}/sessions`, { method: 'DELETE' }),
  },
}
