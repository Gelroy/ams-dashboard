import { useState, type FormEvent } from 'react'
import { useNavigate } from 'react-router-dom'

import { isNewPasswordChallenge, login } from '../api'
import { setTokens } from '../auth'

export function LoginPage() {
  const navigate = useNavigate()
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  async function onSubmit(e: FormEvent) {
    e.preventDefault()
    setError(null)
    setBusy(true)
    try {
      const resp = await login(username, password)
      if (isNewPasswordChallenge(resp)) {
        // FORCE_CHANGE_PASSWORD users (newly admin-created via Cognito) land here.
        navigate('/password-change', {
          state: { session: resp.session, username: resp.username },
          replace: true,
        })
        return
      }
      // Send the id_token (not access_token) because Django's
      // CognitoJWTAuthentication verifies the `aud` claim, which Cognito only
      // sets on id_tokens. Refresh token is stored too so api.ts can silently
      // refresh the id_token when it expires (every 60 min by default).
      setTokens(resp.id_token, resp.refresh_token ?? null)
      navigate('/', { replace: true })
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Login failed')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="auth-page">
      <form onSubmit={onSubmit} className="auth-form">
        <h1>AMS Dashboard</h1>
        <label>
          Email
          <input
            type="email"
            autoComplete="username"
            value={username}
            onChange={(e) => setUsername(e.target.value)}
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
        {error && <p className="auth-error">{error}</p>}
        <button type="submit" disabled={busy}>
          {busy ? 'Signing in…' : 'Sign in'}
        </button>
      </form>
    </div>
  )
}
