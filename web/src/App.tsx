import type { ReactNode } from 'react'
import { Navigate, Outlet, Route, Routes } from 'react-router-dom'

import { getToken } from './auth'
import { SidebarNav } from './components/SidebarNav'
import { ActivitiesPage } from './pages/ActivitiesPage'
import { AnalyticsPage } from './pages/AnalyticsPage'
import { BasketsPage } from './pages/BasketsPage'
import { CriticalPage } from './pages/CriticalPage'
import { CustomerDetailPage } from './pages/CustomerDetailPage'
import { CustomersPage } from './pages/CustomersPage'
import { LoginPage } from './pages/LoginPage'
import { NewPasswordPage } from './pages/NewPasswordPage'
import { PatchExecutionPage } from './pages/PatchExecutionPage'
import { PlaceholderPage } from './pages/PlaceholderPage'
import { StaffPage } from './pages/StaffPage'
import { VersionsPage } from './pages/VersionsPage'
import './App.css'

/** Redirects to /login when there's no access token in storage. */
function RequireAuth({ children }: { children: ReactNode }) {
  if (!getToken()) {
    return <Navigate to="/login" replace />
  }
  return <>{children}</>
}

/** Shell layout used by every authenticated page. */
function AppLayout() {
  return (
    <div className="shell">
      <SidebarNav />
      <main className="content">
        <Outlet />
      </main>
    </div>
  )
}

function App() {
  return (
    <Routes>
      {/* Public auth pages — no sidebar, no auth required. */}
      <Route path="/login" element={<LoginPage />} />
      <Route path="/password-change" element={<NewPasswordPage />} />

      {/* Everything else is gated. */}
      <Route
        element={
          <RequireAuth>
            <AppLayout />
          </RequireAuth>
        }
      >
        <Route path="/" element={<Navigate to="/customers" replace />} />
        <Route path="/critical" element={<CriticalPage />} />
        <Route path="/activities" element={<ActivitiesPage />} />
        <Route path="/customers" element={<CustomersPage />} />
        <Route path="/customers/:id" element={<CustomerDetailPage />} />
        <Route path="/versions" element={<VersionsPage />} />
        <Route path="/baskets" element={<BasketsPage />} />
        <Route path="/patch-execution" element={<PatchExecutionPage />} />
        <Route path="/analytics" element={<AnalyticsPage />} />
        <Route path="/staff" element={<StaffPage />} />
        <Route path="/settings" element={<PlaceholderPage title="Settings" />} />
        <Route path="*" element={<PlaceholderPage title="Not found" />} />
      </Route>
    </Routes>
  )
}

export default App
