import type { ReactNode } from 'react'
import { Navigate, Route, Routes } from 'react-router-dom'

import { getToken } from './auth'
import { HomePage } from './pages/HomePage'
import { LoginPage } from './pages/LoginPage'
import { MfaSetupPage } from './pages/MfaSetupPage'
import { MfaVerifyPage } from './pages/MfaVerifyPage'
import { NewPasswordPage } from './pages/NewPasswordPage'

function RequireAuth({ children }: { children: ReactNode }) {
  return getToken() ? <>{children}</> : <Navigate to="/login" replace />
}

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route path="/new-password" element={<NewPasswordPage />} />
      <Route path="/mfa-setup" element={<MfaSetupPage />} />
      <Route path="/mfa" element={<MfaVerifyPage />} />
      <Route
        path="/"
        element={
          <RequireAuth>
            <HomePage />
          </RequireAuth>
        }
      />
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  )
}
