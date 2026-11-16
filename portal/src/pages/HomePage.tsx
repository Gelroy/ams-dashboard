import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'

import { getDocuments, getHome, getMe, type Home, type Me, type PortalDocument } from '../api'
import { Shell } from '../components/Shell'

export function HomePage() {
  const [me, setMe] = useState<Me | null>(null)
  const [home, setHome] = useState<Home | null>(null)
  const [documents, setDocuments] = useState<PortalDocument[]>([])
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    Promise.all([getMe(), getHome(), getDocuments()])
      .then(([m, h, d]) => {
        if (cancelled) return
        setMe(m)
        setHome(h)
        setDocuments(d)
      })
      .catch((e: unknown) => {
        if (!cancelled) setError(e instanceof Error ? e.message : 'Could not load the portal.')
      })
    return () => {
      cancelled = true
    }
  }, [])

  const org = home?.organization
  const totalServers = home?.environments.reduce((n, e) => n + e.server_count, 0) ?? 0

  return (
    <Shell email={me?.email ?? null}>
      <>
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

            <section className="card latest">
              <h2>Latest report</h2>
              {documents.length === 0 ? (
                <p className="muted">
                  Your monthly AMS reports will appear here once they are published.
                </p>
              ) : (
                <p>
                  <strong>{documents[0].period_label}</strong> · {documents[0].title}.{' '}
                  <Link to="/documents">
                    {documents.length === 1 ? 'Open it in Documents' : `See all ${documents.length} reports`}
                  </Link>
                </p>
              )}
            </section>

            <p className="muted note">
              Signed in as {me.email}
              {me.role ? ` · ${me.role}` : ''}.
            </p>
          </>
        )}
      </>
    </Shell>
  )
}
