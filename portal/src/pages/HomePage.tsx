import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'

import { getHome, getMe, signOut, type Home, type Me } from '../api'

export function HomePage() {
  const navigate = useNavigate()
  const [me, setMe] = useState<Me | null>(null)
  const [home, setHome] = useState<Home | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    Promise.all([getMe(), getHome()])
      .then(([m, h]) => {
        if (cancelled) return
        setMe(m)
        setHome(h)
      })
      .catch((e: unknown) => {
        if (!cancelled) setError(e instanceof Error ? e.message : 'Could not load the portal.')
      })
    return () => {
      cancelled = true
    }
  }, [])

  async function onSignOut() {
    await signOut()
    navigate('/login', { replace: true })
  }

  const org = home?.organization
  const totalServers = home?.environments.reduce((n, e) => n + e.server_count, 0) ?? 0

  return (
    <div className="shell">
      <header className="topbar">
        <div className="brand">
          <span className="brand-mark" aria-hidden="true" />
          AMS Customer Portal
        </div>
        <div className="who">
          {me && <span className="who-email">{me.email}</span>}
          <button type="button" className="quiet" onClick={onSignOut}>
            Sign out
          </button>
        </div>
      </header>

      <main className="page">
        {error && (
          <p className="error" role="alert">
            {error}
          </p>
        )}
        {!error && (!me || !home || !org) && <p className="muted">Loading…</p>}

        {me && home && org && (
          <>
            <p className="eyebrow">{org.name}</p>
            <h1>Welcome{me.display_name ? `, ${me.display_name.split(' ')[0]}` : ''}</h1>

            <div className="grid">
              <section className="card">
                <h2>Your service</h2>
                <dl>
                  <dt>Organization</dt>
                  <dd>{org.name}</dd>
                  <dt>AMS level</dt>
                  <dd>
                    {org.ams_level ? (
                      <span className={`level level-${org.ams_level.toLowerCase()}`}>
                        {org.ams_level}
                      </span>
                    ) : (
                      '—'
                    )}
                  </dd>
                  <dt>Help desk</dt>
                  <dd>
                    {org.help_desk_phone ? (
                      <a href={`tel:${org.help_desk_phone.replace(/[^+\d]/g, '')}`}>
                        {org.help_desk_phone}
                      </a>
                    ) : (
                      '—'
                    )}
                  </dd>
                </dl>
              </section>

              <section className="card">
                <h2>Managed environments</h2>
                {home.environments.length === 0 ? (
                  <p className="muted">No environments are recorded yet.</p>
                ) : (
                  <table>
                    <thead>
                      <tr>
                        <th>Environment</th>
                        <th className="num">Servers</th>
                      </tr>
                    </thead>
                    <tbody>
                      {home.environments.map((e) => (
                        <tr key={e.name}>
                          <td>{e.name}</td>
                          <td className="num">{e.server_count}</td>
                        </tr>
                      ))}
                    </tbody>
                    <tfoot>
                      <tr>
                        <td>Total</td>
                        <td className="num">{totalServers}</td>
                      </tr>
                    </tfoot>
                  </table>
                )}
              </section>
            </div>

            <p className="muted note">
              Signed in as {me.email}
              {me.role ? ` · ${me.role}` : ''}. Reports and support requests will appear here as
              they become available.
            </p>
          </>
        )}
      </main>
    </div>
  )
}
