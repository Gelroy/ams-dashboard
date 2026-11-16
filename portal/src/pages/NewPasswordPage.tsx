import { useState } from 'react'
import { Navigate, useLocation } from 'react-router-dom'

import { submitNewPassword, type NewPasswordChallenge } from '../api'
import { AuthCard } from '../components/AuthCard'
import { useAdvance, type FlowState } from '../flow'

export function NewPasswordPage() {
  const advance = useAdvance()
  const state = useLocation().state as FlowState<NewPasswordChallenge> | null
  const [password, setPassword] = useState('')
  const [confirm, setConfirm] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  // Reached without a challenge (reload, bookmark): start over.
  if (state?.challenge?.challenge !== 'NEW_PASSWORD_REQUIRED') {
    return <Navigate to="/login" replace />
  }
  const { challenge, email } = state

  async function submit() {
    setError(null)
    if (password !== confirm) {
      setError('The two passwords do not match.')
      return
    }
    setBusy(true)
    try {
      advance(await submitNewPassword(challenge, email, password), email)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not set the password.')
      setBusy(false)
    }
  }

  return (
    <AuthCard
      title="Choose a password"
      intro={
        <>
          Welcome. Replace the temporary password for <strong>{email}</strong> with one of your
          own.
        </>
      }
      error={error}
      busy={busy}
      submitLabel="Save and continue"
      busyLabel="Saving…"
      onSubmit={submit}
    >
      <label>
        New password
        <input
          type="password"
          autoComplete="new-password"
          minLength={12}
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          required
          autoFocus
        />
        <span className="hint">
          At least 12 characters, with upper- and lower-case letters and a number.
        </span>
      </label>
      <label>
        Confirm new password
        <input
          type="password"
          autoComplete="new-password"
          value={confirm}
          onChange={(e) => setConfirm(e.target.value)}
          required
        />
      </label>
    </AuthCard>
  )
}
