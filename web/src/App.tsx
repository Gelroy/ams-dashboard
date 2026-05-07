import { Navigate, Route, Routes } from 'react-router-dom'

import { SidebarNav } from './components/SidebarNav'
import { CustomersPage } from './pages/CustomersPage'
import { PlaceholderPage } from './pages/PlaceholderPage'
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
          <Route path="/versions" element={<PlaceholderPage title="Versions" />} />
          <Route path="/baskets" element={<PlaceholderPage title="Baskets" />} />
          <Route path="/patch-execution" element={<PlaceholderPage title="Patch Execution" />} />
          <Route path="/analytics" element={<PlaceholderPage title="Analytics" />} />
          <Route path="/staff" element={<PlaceholderPage title="Staff" />} />
          <Route path="/settings" element={<PlaceholderPage title="Settings" />} />
          <Route path="*" element={<PlaceholderPage title="Not found" />} />
        </Routes>
      </main>
    </div>
  )
}

export default App
