import React from 'react'
import { Routes, Route } from 'react-router-dom'
import { AuthProvider } from './context/AuthContext.jsx'
import { ProtectedRoute, AdminRoute } from './components/ProtectedRoute.jsx'
import LoginPage from './pages/LoginPage.jsx'
import StationsPage from './pages/StationsPage.jsx'
import StationDashboardPage from './pages/StationDashboardPage.jsx'
import AdminPage from './pages/AdminPage.jsx'

export default function App() {
  return (
    <AuthProvider>
      <Routes>
        <Route path="/login" element={<LoginPage />} />
        <Route path="/" element={<ProtectedRoute><StationsPage /></ProtectedRoute>} />
        <Route path="/stations/:id" element={<ProtectedRoute><StationDashboardPage /></ProtectedRoute>} />
        <Route path="/admin" element={<AdminRoute><AdminPage /></AdminRoute>} />
      </Routes>
    </AuthProvider>
  )
}
