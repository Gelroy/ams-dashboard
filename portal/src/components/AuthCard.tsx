import type { FormEvent, ReactNode } from 'react'

/** Shared frame for the sign-in steps: brand mark, title, one form. */
export function AuthCard({
  title,
  intro,
  error,
  busy,
  submitLabel,
  busyLabel,
  onSubmit,
  children,
  footer,
}: {
  title: string
  intro?: ReactNode
  error: string | null
  busy: boolean
  submitLabel: string
  busyLabel: string
  onSubmit: () => void
  children: ReactNode
  footer?: ReactNode
}) {
  function handle(e: FormEvent) {
    e.preventDefault()
    if (!busy) onSubmit()
  }
  return (
    <main className="auth-page">
      <div className="brand">
        <span className="brand-mark" aria-hidden="true" />
        AMS Customer Portal
      </div>
      <form className="card auth-card" onSubmit={handle} noValidate={false}>
        <h1>{title}</h1>
        {intro && <div className="intro">{intro}</div>}
        {children}
        {error && (
          <p className="error" role="alert">
            {error}
          </p>
        )}
        <button type="submit" className="primary" disabled={busy}>
          {busy ? busyLabel : submitLabel}
        </button>
        {footer && <div className="auth-footer">{footer}</div>}
      </form>
    </main>
  )
}
