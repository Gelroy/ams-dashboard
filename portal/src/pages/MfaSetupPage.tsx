import { QRCodeSVG } from 'qrcode.react'
import { useState } from 'react'
import { Navigate, useLocation } from 'react-router-dom'

import { confirmMfaSetup, type MfaSetupChallenge } from '../api'
import { AuthCard } from '../components/AuthCard'
import { CodeField } from '../components/CodeField'
import { useAdvance, type FlowState } from '../flow'

export function MfaSetupPage() {
  const advance = useAdvance()
  const state = useLocation().state as FlowState<MfaSetupChallenge> | null
  const [code, setCode] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  if (state?.challenge?.challenge !== 'MFA_SETUP') {
    return <Navigate to="/login" replace />
  }
  const { challenge, email } = state
  // Shown for typing into an authenticator when the camera isn't an option.
  const spacedSecret = challenge.secret_code.replace(/(.{4})/g, '$1 ').trim()

  async function submit() {
    setError(null)
    setBusy(true)
    try {
      advance(await confirmMfaSetup(challenge, code), email)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not verify the code.')
      setBusy(false)
    }
  }

  return (
    <AuthCard
      title="Set up two-step sign-in"
      intro={
        <>
          The portal protects your organization&rsquo;s information with a second step. You will
          need an authenticator app, such as Microsoft Authenticator or Google Authenticator.
        </>
      }
      error={error}
      busy={busy}
      submitLabel="Verify and finish"
      busyLabel="Verifying…"
      onSubmit={submit}
    >
      <ol className="steps">
        <li>
          Open your authenticator app and add an account by scanning this code.
          <div className="qr">
            <QRCodeSVG value={challenge.otpauth_uri} size={176} marginSize={2} />
          </div>
          <details>
            <summary>Can&rsquo;t scan it?</summary>
            Enter this key in the app instead:
            <code className="secret">{spacedSecret}</code>
          </details>
        </li>
        <li>Enter the 6-digit code the app shows.</li>
      </ol>
      <CodeField value={code} onChange={setCode} autoFocus={false} />
    </AuthCard>
  )
}
