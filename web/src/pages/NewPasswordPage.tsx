import { useState, type FormEvent } from 'react'
import { Navigate, useLocation, useNavigate } from 'react-router-dom'

import { respondToNewPassword } from '../api'
import { setTokens } from '../auth'

interface ChallengeState {
  session: string
  username: string
}

export function NewPasswordPage() {
  const navigate = useNavigate()
  const location = useLocation()
  const state = location.state as ChallengeState | null

  const [newPassword, setNewPassword] = useState('')
  const [confirmPassword, setConfirmPassword] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  // If the user landed here without a challenge in tow (bookmark, refresh,
  // etc.), bounce them back to login.
  if (!state?.session || !state.username) {
    return <Navigate to="/login" replace />
  }

  async function onSubmit(e: FormEvent) {
    e.preventDefault()
    setError(null)
    if (newPassword !== confirmPassword) {
      setError('Passwords do not match.')
      return
    }
    setBusy(true)
    try {
      const resp = await respondToNewPassword(state!.session, state!.username, newPassword)
      // See LoginPage.tsx — id_token (not access_token) is what Django's
      // CognitoJWTAuthentication can verify. Refresh token is captured so
      // silent refresh works after the new password is set.
      setTokens(resp.id_token, resp.refresh_token ?? null)
      navigate('/', { replace: true })
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Could not set new password.')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="auth-page">
      <form onSubmit={onSubmit} className="auth-form">
        <h1>Set a new password</h1>
        <p>First-time sign-in for {state.username}. Cognito requires a new password.</p>
        <label>
          New password
          <input
            type="password"
            autoComplete="new-password"
            value={newPassword}
            onChange={(e) => setNewPassword(e.target.value)}
            required
            autoFocus
          />
        </label>
        <label>
          Confirm new password
          <input
            type="password"
            autoComplete="new-password"
            value={confirmPassword}
            onChange={(e) => setConfirmPassword(e.target.value)}
            required
          />
        </label>
        {error && <p className="auth-error">{error}</p>}
        <button type="submit" disabled={busy}>
          {busy ? 'Saving…' : 'Save and continue'}
        </button>
      </form>
    </div>
  )
}
