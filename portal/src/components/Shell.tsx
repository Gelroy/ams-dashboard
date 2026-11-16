import type { ReactNode } from 'react'
import { NavLink, useNavigate } from 'react-router-dom'

import { signOut } from '../api'

/** Frame shared by every signed-in page: brand, navigation, sign out. */
export function Shell({ email, children }: { email: string | null; children: ReactNode }) {
  const navigate = useNavigate()

  async function onSignOut() {
    await signOut()
    navigate('/login', { replace: true })
  }

  return (
    <div className="shell">
      <header className="topbar">
        <div className="brand">
          <span className="brand-mark" aria-hidden="true" />
          AMS Customer Portal
        </div>
        <nav className="topnav" aria-label="Main">
          <NavLink to="/" end>
            Home
          </NavLink>
          <NavLink to="/documents">Documents</NavLink>
        </nav>
        <div className="who">
          {email && <span className="who-email">{email}</span>}
          <button type="button" className="quiet" onClick={onSignOut}>
            Sign out
          </button>
        </div>
      </header>
      <main className="page">{children}</main>
    </div>
  )
}
