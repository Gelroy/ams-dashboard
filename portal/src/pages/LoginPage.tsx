import { useState } from 'react'
import { Navigate } from 'react-router-dom'

import { login } from '../api'
import { getToken } from '../auth'
import { AuthCard } from '../components/AuthCard'
import { useAdvance } from '../flow'

export function LoginPage() {
  const advance = useAdvance()
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  if (getToken()) return <Navigate to="/" replace />

  async function submit() {
    setError(null)
    setBusy(true)
    try {
      advance(await login(email, password), email.trim().toLowerCase())
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Sign-in failed.')
      setBusy(false)
    }
  }

  return (
    <AuthCard
      title="Sign in"
      error={error}
      busy={busy}
      submitLabel="Continue"
      busyLabel="Signing in…"
      onSubmit={submit}
      footer="Access is by invitation. If you need an account, contact your AMS support team."
    >
      <label>
        Email
        <input
          type="email"
          autoComplete="username"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          required
          autoFocus
        />
      </label>
      <label>
        Password
        <input
          type="password"
          autoComplete="current-password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          required
        />
      </label>
    </AuthCard>
  )
}
