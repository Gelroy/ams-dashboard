import { Navigate, Route, Routes } from 'react-router-dom'

import { SidebarNav } from './components/SidebarNav'
import { AnalyticsPage } from './pages/AnalyticsPage'
import { BasketsPage } from './pages/BasketsPage'
import { CustomerDetailPage } from './pages/CustomerDetailPage'
import { CustomersPage } from './pages/CustomersPage'
import { PatchExecutionPage } from './pages/PatchExecutionPage'
import { PlaceholderPage } from './pages/PlaceholderPage'
import { VersionsPage } from './pages/VersionsPage'
import './App.css'

function App() {
  return (
    <div className="shell">
      <SidebarNav />
      <main className="content">
        <Routes>
          <Route path="/" element={<Navigate to="/customers" replace />} />
          <Route path="/critical" element={<PlaceholderPage title="Critical" />} />
          <Route path="/activities" element={<PlaceholderPage title="Activities" />} />
          <Route path="/customers" element={<CustomersPage />} />
          <Route path="/customers/:id" element={<CustomerDetailPage />} />
          <Route path="/versions" element={<VersionsPage />} />
          <Route path="/baskets" element={<BasketsPage />} />
          <Route path="/patch-execution" element={<PatchExecutionPage />} />
          <Route path="/analytics" element={<AnalyticsPage />} />
          <Route path="/staff" element={<PlaceholderPage title="Staff" />} />
          <Route path="/settings" element={<PlaceholderPage title="Settings" />} />
          <Route path="*" element={<PlaceholderPage title="Not found" />} />
        </Routes>
      </main>
    </div>
  )
}

export default App
