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
  // ── Auth ──
  login: async (email, password, duration) => {
    const result = await request('/auth/login', { method: 'POST', body: JSON.stringify({ email, password, duration }) })
    setToken(result.token)
    return result
  },
  logout: async () => {
    try { await request('/auth/logout', { method: 'POST' }) } finally { setToken(null) }
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
  submitPriceUpdate: (id, tankLocalId, body) =>
    request(`/stations/${id}/tanks/${tankLocalId}/price-updates`, { method: 'POST', body: JSON.stringify(body) }),
  priceUpdates: (id) => request(`/stations/${id}/price-updates`),

  // ── Supplier ──
  supplier: {
    stations: () => request('/supplier/stations'),
    markOrdered: (stationId, body) =>
      request(`/supplier/stations/${stationId}/order`, { method: 'POST', body: JSON.stringify(body) }),
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

    users: () => request('/admin/users'),
    createUser: (body) => request('/admin/users', { method: 'POST', body: JSON.stringify(body) }),
    updateUser: (id, body) => request(`/admin/users/${id}`, { method: 'PUT', body: JSON.stringify(body) }),
    setUserPassword: (userId, password) => request(`/admin/users/${userId}/set-password`, { method: 'POST', body: JSON.stringify({ password }) }),

    createAssignment: (userId, stationId) =>
      request('/admin/assignments', { method: 'POST', body: JSON.stringify({ user_id: userId, station_id: stationId }) }),
    deleteAssignment: (userId, stationId) =>
      request(`/admin/assignments?user_id=${userId}&station_id=${stationId}`, { method: 'DELETE' }),

    userSessions: (userId) => request(`/admin/users/${userId}/sessions`),
    revokeSession: (sessionId) => request(`/admin/sessions/${sessionId}`, { method: 'DELETE' }),
    revokeAllUserSessions: (userId) => request(`/admin/users/${userId}/sessions`, { method: 'DELETE' }),
  },
}
