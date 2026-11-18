import React from 'react'
import { Routes, Route } from 'react-router-dom'
import { AuthProvider } from './context/AuthContext.jsx'
import { ProtectedRoute, AdminRoute, SupplierRoute } from './components/ProtectedRoute.jsx'
import LoginPage from './pages/LoginPage.jsx'
import StationsPage from './pages/StationsPage.jsx'
import StationDashboardPage from './pages/StationDashboardPage.jsx'
import AdminPage from './pages/AdminPage.jsx'
import SupplierDashboard from './pages/SupplierDashboard.jsx'
import MapPage from './pages/MapPage.jsx'
import FleetPage from './pages/FleetPage.jsx'

export default function App() {
  return (
    <AuthProvider>
      <Routes>
        <Route path="/login" element={<LoginPage />} />
        <Route path="/" element={<ProtectedRoute><StationsPage /></ProtectedRoute>} />
        <Route path="/map" element={<ProtectedRoute><MapPage /></ProtectedRoute>} />
        <Route path="/stations/:id" element={<ProtectedRoute><StationDashboardPage /></ProtectedRoute>} />
        <Route path="/admin" element={<AdminRoute><AdminPage /></AdminRoute>} />
        <Route path="/supplier" element={<SupplierRoute><SupplierDashboard /></SupplierRoute>} />
        <Route path="/fleet" element={<SupplierRoute><FleetPage /></SupplierRoute>} />
      </Routes>
    </AuthProvider>
  )
}
