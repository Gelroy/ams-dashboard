import { useCallback, useEffect, useRef, useState } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'

import { apiErrorDetail } from '../api'
import {
  deliverMetrics,
  generateAllReports,
  generateReport,
  getOverview,
  previousMonth,
  type Overview,
  type OverviewRow,
} from '../reportsApi'

/** Monthly reports: one row per contracted customer for the chosen month —
 *  whether monitoring data has arrived and where the report stands. */
export function ReportsPage() {
  const navigate = useNavigate()
  const [params, setParams] = useSearchParams()
  const period = params.get('period') || previousMonth()
  const [overview, setOverview] = useState<Overview | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [notice, setNotice] = useState<string | null>(null)
  const [busy, setBusy] = useState<string | null>(null)

  const load = useCallback(
    () =>
      getOverview(period)
        .then((o) => {
          setOverview(o)
          setError(null)
        })
        .catch((e: unknown) => setError(apiErrorDetail(e))),
    [period],
  )
  useEffect(() => {
    void load()
  }, [load])

  const run = async (key: string, work: () => Promise<string | void>) => {
    setBusy(key)
    setError(null)
    setNotice(null)
    try {
      const message = await work()
      if (message) setNotice(message)
      await load()
    } catch (e) {
      setError(apiErrorDetail(e))
    } finally {
      setBusy(null)
    }
  }

  const rows = overview?.period === period ? overview.rows : null
  const missing = rows?.filter((r) => !r.report).length ?? 0

  return (
    <div>
      <div className="panel-header-row">
        <span className="panel-title">Reports</span>
        <span className="panel-hint">
          Monthly customer reports. Drafts are only visible here; customers see a report in the
          portal once it is approved.
        </span>
      </div>

      <div className="filter-bar">
        <input
          className="input"
          type="month"
          aria-label="Report month"
          value={period}
          onChange={(e) => e.target.value && setParams({ period: e.target.value })}
        />
        <button
          className="btn"
          disabled={busy !== null || missing === 0}
          onClick={() =>
            run('all', async () => {
              const r = await generateAllReports(period)
              return `Created ${r.created} draft${r.created === 1 ? '' : 's'}.`
            })
          }
        >
          {busy === 'all' ? 'Generating…' : `Generate ${missing} missing draft${missing === 1 ? '' : 's'}`}
        </button>
        <Link className="btn-link" to="/report-templates" style={{ alignSelf: 'center' }}>
          Edit templates
        </Link>
      </div>

      {error && <div className="error-banner">{error}</div>}
      {notice && <div className="notice-banner">{notice}</div>}

      <div className="table-wrap">
        <table className="data-table">
          <thead>
            <tr>
              <th>Customer</th>
              <th style={{ width: 150 }}>Monitoring data</th>
              <th style={{ width: 120 }}>Tickets</th>
              <th style={{ width: 150 }}>Email recipients</th>
              <th style={{ width: 130 }}>Report</th>
              <th style={{ width: 150 }} />
            </tr>
          </thead>
          <tbody>
            {!rows && !error && (
              <tr>
                <td colSpan={6} className="state-cell">
                  Loading…
                </td>
              </tr>
            )}
            {rows?.length === 0 && (
              <tr>
                <td colSpan={6} className="state-cell">
                  No customers have an AMS level yet.
                </td>
              </tr>
            )}
            {rows?.map((row) => (
              <ReportRow
                key={row.organization}
                row={row}
                busy={busy}
                onGenerate={() =>
                  run(row.organization, async () => {
                    const report = await generateReport(row.organization, period)
                    navigate(`/reports/${report.id}`)
                  })
                }
                onMetrics={(payload) =>
                  run(row.organization, async () => {
                    await deliverMetrics(row.organization, period, payload)
                    return `Monitoring data saved for ${row.organization_name}.`
                  })
                }
                onBadFile={(message) => setError(message)}
              />
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}

function ReportRow({
  row,
  busy,
  onGenerate,
  onMetrics,
  onBadFile,
}: {
  row: OverviewRow
  busy: string | null
  onGenerate: () => void
  onMetrics: (payload: unknown) => void
  onBadFile: (message: string) => void
}) {
  const file = useRef<HTMLInputElement>(null)
  const working = busy === row.organization

  const onFile = async (f: File | undefined) => {
    if (!f) return
    try {
      onMetrics(JSON.parse(await f.text()))
    } catch {
      onBadFile(`${f.name} is not valid JSON.`)
    } finally {
      if (file.current) file.current.value = ''
    }
  }

  return (
    <tr>
      <td>
        <Link className="row-link" to={`/customers/${row.organization}`}>
          {row.organization_name}
        </Link>
        {row.ams_level && <span className="meta"> · {row.ams_level}</span>}
      </td>
      <td>
        <span className={row.metrics_received ? 'badge badge-portal-active' : 'badge'}>
          {row.metrics_received ? 'Received' : 'Not received'}
        </span>
        <button
          className="btn-link"
          disabled={busy !== null}
          title="Upload this month's monitoring metrics (JSON)"
          onClick={() => file.current?.click()}
        >
          {row.metrics_received ? 'Replace' : 'Upload'}
        </button>
        <input
          ref={file}
          type="file"
          accept="application/json,.json"
          hidden
          onChange={(e) => void onFile(e.target.files?.[0])}
        />
      </td>
      <td>
        {row.tickets_synced ? (
          <span className="badge badge-portal-active" title="Ticket activity for this month is in">
            {row.tickets_count} synced
          </span>
        ) : (
          <span className="badge" title="The report will show open ticket counts only">
            Not synced
          </span>
        )}
      </td>
      <td>
        {row.report_recipients > 0 ? (
          `${row.report_recipients} of ${row.portal_users} portal user${row.portal_users === 1 ? '' : 's'}`
        ) : (
          <span className="meta">
            {row.portal_users === 0 ? 'No portal users' : 'None flagged for the report'}
          </span>
        )}
      </td>
      <td>
        {row.report ? (
          <span className={`badge badge-report-${row.report.status}`}>
            {row.report.status === 'approved' ? 'Approved' : 'Draft'}
          </span>
        ) : (
          <span className="meta">Not started</span>
        )}
      </td>
      <td style={{ textAlign: 'right' }}>
        {row.report ? (
          <Link className="btn" to={`/reports/${row.report.id}`}>
            {row.report.status === 'approved' ? 'View' : 'Review draft'}
          </Link>
        ) : (
          <button className="btn" disabled={busy !== null} onClick={onGenerate}>
            {working ? 'Generating…' : 'Generate draft'}
          </button>
        )}
      </td>
    </tr>
  )
}
