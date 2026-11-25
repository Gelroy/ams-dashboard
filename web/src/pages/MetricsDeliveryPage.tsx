import { useEffect, useState } from 'react'

import { apiErrorDetail, listOrganizations } from '../api'
import {
  createMetricsKey,
  listMetricsKeys,
  previousMonth,
  revokeMetricsKey,
  type MetricsKey,
} from '../reportsApi'
import type { Organization } from '../types'

const when = (iso: string | null) =>
  iso ? new Date(iso).toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' }) : '—'

/** Unattended delivery of monthly monitoring metrics: the keys the
 *  monitoring tool signs in with, and what it has to send. */
export function MetricsDeliveryPage() {
  const [keys, setKeys] = useState<MetricsKey[] | null>(null)
  const [orgs, setOrgs] = useState<Organization[]>([])
  const [name, setName] = useState('')
  const [fresh, setFresh] = useState<{ name: string; key: string } | null>(null)
  const [copied, setCopied] = useState(false)
  const [busy, setBusy] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    Promise.all([listMetricsKeys(), listOrganizations({ limit: 200, has_ams_level: true })])
      .then(([list, organizations]) => {
        if (cancelled) return
        setKeys(list)
        setOrgs(organizations.results)
      })
      .catch((e: unknown) => {
        if (!cancelled) setError(apiErrorDetail(e))
      })
    return () => {
      cancelled = true
    }
  }, [])

  const run = async (tag: string, work: () => Promise<void>) => {
    setBusy(tag)
    setError(null)
    try {
      await work()
      setKeys(await listMetricsKeys())
    } catch (e) {
      setError(apiErrorDetail(e))
    } finally {
      setBusy(null)
    }
  }

  const create = () =>
    run('create', async () => {
      const made = await createMetricsKey(name)
      setFresh({ name: made.name, key: made.key })
      setCopied(false)
      setName('')
    })

  const revoke = (k: MetricsKey) => {
    if (!window.confirm(`Revoke "${k.name}"? Anything still using this key stops working.`)) return
    void run(k.id, async () => {
      await revokeMetricsKey(k.id)
      if (fresh?.name === k.name) setFresh(null)
    })
  }

  const copy = async () => {
    if (!fresh) return
    try {
      await navigator.clipboard.writeText(fresh.key)
      setCopied(true)
    } catch {
      setCopied(false)
    }
  }

  const endpoint = `${window.location.origin}/api/report-metrics/ingest`
  const sampleCustomer = orgs[0]?.jira_org_id ?? '<customer id>'
  const example = [
    `curl --fail-with-body -X POST ${endpoint} \\`,
    `  -H "Authorization: Bearer $AMS_METRICS_KEY" \\`,
    `  -H "Content-Type: application/json" \\`,
    `  -d @metrics.json`,
  ].join('\n')
  const body = JSON.stringify(
    {
      period: previousMonth(),
      deliveries: [
        {
          customer: sampleCustomer,
          metrics: {
            availability: { percent: 99.97, downtimeMinutes: 12 },
            alerts: { total: 9, high: 1 },
            hosts: [{ name: 'prod-01', availabilityPercent: 99.99, cpuAvgPercent: 21.5 }],
          },
        },
      ],
    },
    null,
    2,
  )

  return (
    <div>
      <div className="panel-header-row">
        <span className="panel-title">Metrics Delivery</span>
        <span className="panel-hint">
          How the monitoring tool hands over each month's figures without anyone uploading a file.
        </span>
      </div>

      {error && <div className="error-banner">{error}</div>}

      {fresh && (
        <div className="notice-banner key-reveal">
          <div>
            <strong>Key for "{fresh.name}".</strong> Copy it now. It is not stored and cannot be
            shown again.
          </div>
          <code className="key-value">{fresh.key}</code>
          <div>
            <button className="btn" onClick={() => void copy()}>
              {copied ? 'Copied' : 'Copy key'}
            </button>
            <button className="btn-link" onClick={() => setFresh(null)}>
              Done
            </button>
          </div>
        </div>
      )}

      <div className="detail-section">
        <h3 className="section-title">Delivery keys</h3>
        <p className="meta" style={{ marginTop: 0 }}>
          A key lets a server deliver metrics and nothing else. It cannot read reports or customer
          data. Create one per server so each can be revoked on its own.
        </p>
        <div className="filter-bar">
          <input
            className="input"
            aria-label="Name for the new key"
            placeholder="Name, e.g. zabbix-prod"
            value={name}
            maxLength={80}
            onChange={(e) => setName(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && name.trim() && busy === null && void create()}
          />
          <button
            className="btn btn-primary"
            disabled={busy !== null || !name.trim()}
            onClick={() => void create()}
          >
            {busy === 'create' ? 'Creating…' : 'Create key'}
          </button>
        </div>
        <div className="table-wrap">
          <table className="data-table">
            <thead>
              <tr>
                <th>Name</th>
                <th>Key</th>
                <th>Created</th>
                <th>Last used</th>
                <th>Status</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {keys === null && (
                <tr>
                  <td className="state-cell" colSpan={6}>
                    Loading…
                  </td>
                </tr>
              )}
              {keys?.length === 0 && (
                <tr>
                  <td className="state-cell" colSpan={6}>
                    No keys yet. Until one exists, metrics are uploaded by hand on the Reports
                    screen.
                  </td>
                </tr>
              )}
              {keys?.map((k) => (
                <tr key={k.id}>
                  <td>{k.name}</td>
                  <td>
                    <code>{k.prefix}…</code>
                  </td>
                  <td>
                    {when(k.created_at)}
                    {k.created_by_email && <span className="meta"> · {k.created_by_email}</span>}
                  </td>
                  <td>{k.last_used_at ? when(k.last_used_at) : <span className="meta">Never</span>}</td>
                  <td>
                    {k.revoked_at ? (
                      <span className="badge" title={`Revoked ${when(k.revoked_at)}`}>
                        Revoked
                      </span>
                    ) : (
                      <span className="badge badge-portal-active">Active</span>
                    )}
                  </td>
                  <td>
                    {!k.revoked_at && (
                      <button
                        className="btn-link"
                        disabled={busy !== null}
                        onClick={() => revoke(k)}
                      >
                        {busy === k.id ? 'Revoking…' : 'Revoke'}
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      <div className="detail-section">
        <h3 className="section-title">What the monitoring tool sends</h3>
        <p className="meta" style={{ marginTop: 0 }}>
          One request a month, after the month has ended. Keep the key in an environment variable
          or a secrets store on that server, not in the script.
        </p>
        <pre className="code-sample">{example}</pre>
        <p className="meta">
          <code>metrics.json</code> lists one entry per customer. Everything inside{' '}
          <code>metrics</code> is yours to shape: report templates read it with tags such as{' '}
          <code>{'{metrics.availability.percent}'}</code>.
        </p>
        <pre className="code-sample">{body}</pre>
        <ul className="meta plain-list">
          <li>
            <code>customer</code> is the customer's JIRA organization id, listed below.
          </li>
          <li>Sending a month again replaces what was sent before, so a retry is always safe.</li>
          <li>
            The answer lists each customer as created, replaced or rejected. If any are rejected
            the request fails with status 422, and the others are still stored.
          </li>
          <li>Drafts already generated keep their old figures until someone regenerates them.</li>
        </ul>
      </div>

      <div className="detail-section">
        <h3 className="section-title">Customer ids</h3>
        <div className="table-wrap">
          <table className="data-table">
            <thead>
              <tr>
                <th>Customer</th>
                <th>
                  <code>customer</code> value
                </th>
              </tr>
            </thead>
            <tbody>
              {orgs.map((o) => (
                <tr key={o.id}>
                  <td>{o.display_name}</td>
                  <td>
                    <code>{o.jira_org_id}</code>
                  </td>
                </tr>
              ))}
              {orgs.length === 0 && (
                <tr>
                  <td className="state-cell" colSpan={2}>
                    No contracted customers.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  )
}
