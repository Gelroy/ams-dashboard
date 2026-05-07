import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'

import { listOrganizations } from '../api'
import type { AmsLevel, Organization } from '../types'

const AMS_LEVELS: AmsLevel[] = ['Essential', 'Enhanced', 'Expert']

export function CustomersPage() {
  const [items, setItems] = useState<Organization[]>([])
  const [count, setCount] = useState(0)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [q, setQ] = useState('')
  const [amsLevel, setAmsLevel] = useState<string>('')

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    setError(null)
    listOrganizations({ q: q || undefined, ams_level: amsLevel || undefined })
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
  }, [q, amsLevel])

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
        <select className="input" value={amsLevel} onChange={(e) => setAmsLevel(e.target.value)}>
          <option value="">All AMS Levels</option>
          {AMS_LEVELS.map((l) => (
            <option key={l} value={l}>
              {l}
            </option>
          ))}
        </select>
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
              <th>Last JIRA Sync</th>
            </tr>
          </thead>
          <tbody>
            {loading && (
              <tr>
                <td colSpan={6} className="state-cell">
                  Loading…
                </td>
              </tr>
            )}
            {!loading && items.length === 0 && (
              <tr>
                <td colSpan={6} className="state-cell">
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
                  <td className="meta">{formatDate(o.jira_synced_at)}</td>
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

function formatDate(iso: string | null): string {
  if (!iso) return '—'
  const d = new Date(iso)
  return d.toLocaleString()
}
