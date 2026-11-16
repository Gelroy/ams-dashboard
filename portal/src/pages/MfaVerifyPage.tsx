import { useState } from 'react'
import { Link, Navigate, useLocation } from 'react-router-dom'

import { verifyMfa, type MfaChallenge } from '../api'
import { AuthCard } from '../components/AuthCard'
import { CodeField } from '../components/CodeField'
import { useAdvance, type FlowState } from '../flow'

export function MfaVerifyPage() {
  const advance = useAdvance()
  const state = useLocation().state as FlowState<MfaChallenge> | null
  const [code, setCode] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  if (state?.challenge?.challenge !== 'SOFTWARE_TOKEN_MFA') {
    return <Navigate to="/login" replace />
  }
  const { challenge, email } = state

  async function submit() {
    setError(null)
    setBusy(true)
    try {
      advance(await verifyMfa(challenge, code), email)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not verify the code.')
      setCode('')
      setBusy(false)
    }
  }

  return (
    <AuthCard
      title="Enter your code"
      intro={
        <>
          Open your authenticator app and enter the current code for <strong>{email}</strong>.
        </>
      }
      error={error}
      busy={busy}
      submitLabel="Sign in"
      busyLabel="Verifying…"
      onSubmit={submit}
      footer={<Link to="/login">Use a different account</Link>}
    >
      <CodeField value={code} onChange={setCode} />
    </AuthCard>
  )
}
