import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'

import { listOrganizations } from '../api'
import type { Organization } from '../types'

export function CustomersPage() {
  const [items, setItems] = useState<Organization[]>([])
  const [count, setCount] = useState(0)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [q, setQ] = useState('')
  // Default behavior: hide customers without an AMS level, since the AMS
  // team only deals with contracted customers. Uncheck to see everyone
  // (e.g. when triaging a newly-synced org that needs a level assigned).
  const [hideUnassigned, setHideUnassigned] = useState(true)

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    setError(null)
    listOrganizations({
      q: q || undefined,
      has_ams_level: hideUnassigned ? true : undefined,
    })
      .then((data) => {
        if (cancelled) return
        setItems(data.results)
        setCount(data.count)
      })
      .catch((e: Error) => {
        if (cancelled) return
        setError(e.message)
      })
      .finally(() => {
        if (cancelled) return
        setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [q, hideUnassigned])

  return (
    <div>
      <div className="panel-header-row">
        <span className="panel-title">Customers</span>
        <span className="panel-hint">{count} total</span>
      </div>

      <div className="filter-bar">
        <input
          className="input"
          placeholder="Search by name…"
          value={q}
          onChange={(e) => setQ(e.target.value)}
        />
        <label className="filter-checkbox">
          <input
            type="checkbox"
            checked={hideUnassigned}
            onChange={(e) => setHideUnassigned(e.target.checked)}
          />
          Hide customers without AMS level
        </label>
      </div>

      {error && <div className="error-banner">Error: {error}</div>}

      <div className="table-wrap">
        <table className="data-table">
          <thead>
            <tr>
              <th>Name</th>
              <th>AMS Level</th>
              <th>Zabbix</th>
              <th>Open Tickets</th>
              <th>Patching</th>
              <th>Cert</th>
              <th>Country</th>
            </tr>
          </thead>
          <tbody>
            {loading && (
              <tr>
                <td colSpan={7} className="state-cell">
                  Loading…
                </td>
              </tr>
            )}
            {!loading && items.length === 0 && (
              <tr>
                <td colSpan={7} className="state-cell">
                  No customers found.
                </td>
              </tr>
            )}
            {!loading &&
              items.map((o) => (
                <tr key={o.id}>
                  <td>
                    <Link to={`/customers/${o.id}`} className="row-link">
                      <strong>{o.display_name}</strong>
                    </Link>
                    {o.local_name && o.local_name !== o.jira_name && (
                      <span className="meta"> (JIRA: {o.jira_name})</span>
                    )}
                  </td>
                  <td>{o.ams_level ? <Badge value={o.ams_level} /> : <span className="meta">—</span>}</td>
                  <td>
                    {o.zabbix_status ? <Badge value={o.zabbix_status} /> : <span className="meta">—</span>}
                  </td>
                  <td>{o.open_ticket_count ?? <span className="meta">—</span>}</td>
                  <td><PatchingBadge status={o.needs_patching} /></td>
                  <td><CertDot status={o.cert_status} /></td>
                  <td>{o.country ?? <span className="meta">—</span>}</td>
                </tr>
              ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}

function Badge({ value }: { value: string }) {
  return <span className={`badge badge-${value.toLowerCase()}`}>{value}</span>
}

function PatchingBadge({ status }: { status: 'yes' | 'no' | 'unknown' }) {
  if (status === 'yes') return <span className="badge patch-yes">Needs Patching</span>
  if (status === 'no') return <span className="badge patch-no">Up to Date</span>
  return <span className="meta">—</span>
}

function CertDot({ status }: { status: 'green' | 'yellow' | 'red' | 'unknown' }) {
  if (status === 'unknown') return <span className="meta">—</span>
  const title =
    status === 'red'
      ? 'One or more server certs are expired'
      : status === 'yellow'
        ? 'A server cert expires within 30 days'
        : 'All server certs are at least 30 days out'
  return <span className={`cert-dot cert-${status}`} title={title} aria-label={title}>●</span>
}
