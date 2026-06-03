import type { ReactNode } from 'react'
import { useEffect, useState } from 'react'
import { Navigate, Outlet, Route, Routes, useLocation } from 'react-router-dom'

import { getMe, type MeResponse } from './api'
import { getToken } from './auth'
import { ErrorBoundary } from './components/ErrorBoundary'
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

/** Shell layout used by every authenticated page. The ErrorBoundary inside
 * the content area catches render-time exceptions per route — a bug in
 * /patch-execution won't blank /customers. The `key={pathname}` ensures the
 * boundary resets when the user navigates away. */
function AppLayout() {
  const location = useLocation()
  // /api/me drives the read-only banner. We fetch it once per authenticated
  // mount; the answer is small (~100 bytes) and stable for the session. If
  // the call fails (network, 401 mid-refresh) we just suppress the banner —
  // the backend is still the source of truth on every write.
  const [me, setMe] = useState<MeResponse | null>(null)
  useEffect(() => {
    let cancelled = false
    getMe()
      .then((r) => {
        if (!cancelled) setMe(r)
      })
      .catch(() => {
        // Swallow — banner just stays hidden.
      })
    return () => {
      cancelled = true
    }
  }, [])

  return (
    <div className="shell">
      <SidebarNav />
      <main className="content">
        {me && !me.is_admin && (
          <div
            className="readonly-banner"
            title="Ask an existing admin to add you to the 'admin' Cognito group to enable editing."
          >
            Read-only access — write actions will fail. Ask an admin to grant write access.
          </div>
        )}
        <ErrorBoundary key={location.pathname}>
          <Outlet />
        </ErrorBoundary>
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
