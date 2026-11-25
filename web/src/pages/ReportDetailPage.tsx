import { useEffect, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'

import { apiErrorDetail } from '../api'
import {
  approveReport,
  deleteReport,
  getReport,
  getReportPdf,
  notifyReport,
  openPdfWhenReady,
  regenerateReport,
  writeAiSummary,
  saveReport,
  type Report,
  type ReportSection,
} from '../reportsApi'

const when = (iso: string | null) =>
  iso ? new Date(iso).toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' }) : '—'

/** Review one report. A draft is editable section by section and can be
 *  previewed as a PDF; approving it freezes the content, stores the PDF and
 *  tells the customer. */
export function ReportDetailPage() {
  const { id = '' } = useParams()
  const navigate = useNavigate()
  const [report, setReport] = useState<Report | null>(null)
  const [title, setTitle] = useState('')
  const [sections, setSections] = useState<ReportSection[]>([])
  const [dirty, setDirty] = useState(false)
  const [busy, setBusy] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [notice, setNotice] = useState<string | null>(null)

  const adopt = (r: Report) => {
    setReport(r)
    setTitle(r.title)
    setSections(r.sections)
    setDirty(false)
  }

  useEffect(() => {
    let cancelled = false
    getReport(id)
      .then((r) => {
        if (!cancelled) adopt(r)
      })
      .catch((e: unknown) => {
        if (!cancelled) setError(apiErrorDetail(e))
      })
    return () => {
      cancelled = true
    }
  }, [id])

  const run = async (key: string, work: () => Promise<string | void>) => {
    setBusy(key)
    setError(null)
    setNotice(null)
    try {
      const message = await work()
      if (message) setNotice(message)
    } catch (e) {
      setError(apiErrorDetail(e))
    } finally {
      setBusy(null)
    }
  }

  if (!report) {
    return error ? <div className="error-banner">{error}</div> : <div className="state-cell">Loading…</div>
  }

  const isDraft = report.status === 'draft'
  const blockers = report.issues.filter((i) => i.level === 'blocker')
  const warnings = report.issues.filter((i) => i.level === 'warning')
  const backTo = `/reports?period=${report.period}`

  const edit = (index: number, patch: Partial<ReportSection>) => {
    setSections((all) => all.map((s, i) => (i === index ? { ...s, ...patch } : s)))
    setDirty(true)
  }

  const save = () =>
    run('save', async () => {
      adopt(await saveReport(report.id, { title, sections }))
      return 'Draft saved.'
    })

  const approve = () => {
    const who =
      report.recipients.length > 0
        ? `These portal users will be emailed:\n\n${report.recipients.join('\n')}`
        : 'Nobody will be emailed: this customer has no active portal user flagged for the AMS report.'
    if (
      !window.confirm(
        `Approve the ${report.period_label} report for ${report.organization_name}?\n\n` +
          `It becomes visible in the customer portal and can no longer be edited.\n\n${who}`,
      )
    )
      return
    void run('approve', async () => {
      adopt(await approveReport(report.id))
      return 'Report approved and published to the portal.'
    })
  }

  return (
    <div>
      <div className="breadcrumbs">
        <Link to={backTo}>Reports</Link> / {report.period_label} / {report.organization_name}
      </div>

      <div className="panel-header-row">
        <span className="panel-title">{report.organization_name}</span>
        <span className={`badge badge-report-${report.status}`}>
          {isDraft ? 'Draft' : 'Approved'}
        </span>
        <span className="panel-hint">
          {report.period_label} · template “{report.template_name}” · generated{' '}
          {when(report.generated_at)}
          {report.created_by_email ? ` by ${report.created_by_email}` : ''}
          {report.ai_summary ? ` · ticket summary drafted by AI (${report.ai_summary.model})` : ''}
          {!isDraft && ` · approved ${when(report.approved_at)} by ${report.approved_by_email || 'unknown'}`}
        </span>
      </div>

      {error && <div className="error-banner">{error}</div>}
      {notice && <div className="notice-banner">{notice}</div>}

      {isDraft && blockers.length > 0 && (
        <div className="issue-box issue-blocker">
          <strong>Resolve before approving</strong>
          <ul>
            {blockers.map((i, n) => (
              <li key={n}>
                {i.section && <span className="meta">{i.section}: </span>}
                {i.message}
              </li>
            ))}
          </ul>
        </div>
      )}
      {warnings.length > 0 && (
        <div className="issue-box issue-warning">
          <ul>
            {warnings.map((i, n) => (
              <li key={n}>{i.message}</li>
            ))}
          </ul>
        </div>
      )}

      <div className="form-actions" style={{ marginTop: 0, marginBottom: '1.25rem', flexWrap: 'wrap' }}>
        {isDraft && (
          <button className="btn btn-primary" disabled={!dirty || busy !== null} onClick={save}>
            {busy === 'save' ? 'Saving…' : 'Save draft'}
          </button>
        )}
        <button
          className="btn"
          disabled={busy !== null || dirty}
          title={dirty ? 'Save your changes first' : undefined}
          onClick={() => void run('pdf', () => openPdfWhenReady(getReportPdf(report.id)))}
        >
          {isDraft ? 'Preview PDF' : 'Open PDF'}
        </button>
        {isDraft && (
          <>
            <button
              className="btn"
              disabled={busy !== null || dirty || blockers.length > 0}
              title={
                dirty
                  ? 'Save your changes first'
                  : blockers.length > 0
                    ? 'Resolve the items above first'
                    : undefined
              }
              onClick={approve}
            >
              {busy === 'approve' ? 'Approving…' : 'Approve and publish'}
            </button>
            {report.can_write_ai_summary && (
              <button
                className="btn"
                disabled={busy !== null || dirty}
                title={
                  dirty
                    ? 'Save your changes first'
                    : "Sends this month's ticket figures and titles for this customer to the AI service and puts its summary in the draft"
                }
                onClick={() =>
                  void run('ai', async () => {
                    adopt(await writeAiSummary(report.id))
                    return 'Ticket summary drafted by AI. Read it against the ticket lists before approving.'
                  })
                }
              >
                {busy === 'ai' ? 'Writing summary…' : 'Write ticket summary with AI'}
              </button>
            )}
            <button
              className="btn-link"
              disabled={busy !== null}
              onClick={() => {
                if (
                  window.confirm(
                    'Rebuild this draft from the template and current data? Your edits to it will be lost.',
                  )
                )
                  void run('regenerate', async () => {
                    adopt(await regenerateReport(report.id))
                    return 'Draft rebuilt from current data.'
                  })
              }}
            >
              Regenerate
            </button>
          </>
        )}
        {!isDraft && (
          <button
            className="btn-link"
            disabled={busy !== null || report.recipients.length === 0}
            onClick={() => {
              if (window.confirm(`Email ${report.recipients.join(', ')} again about this report?`))
                void run('notify', async () => {
                  adopt(await notifyReport(report.id))
                  return 'Notification recorded.'
                })
            }}
          >
            Email customer again
          </button>
        )}
        <button
          className="btn-link"
          disabled={busy !== null}
          onClick={() => {
            const warning = isDraft
              ? 'Delete this draft?'
              : 'Delete this approved report? It disappears from the customer portal immediately.'
            if (window.confirm(warning))
              void run('delete', async () => {
                await deleteReport(report.id)
                navigate(backTo)
              })
          }}
        >
          Delete
        </button>
        {dirty && <span className="meta">Unsaved changes</span>}
      </div>

      <div className="detail-section">
        <div className="field">
          <div className="field-label">Report title</div>
          <input
            className="input"
            value={title}
            disabled={!isDraft}
            onChange={(e) => {
              setTitle(e.target.value)
              setDirty(true)
            }}
          />
        </div>
      </div>

      {sections.map((s, i) => (
        <div className="detail-section" key={s.key ?? i}>
          <div className="field" style={{ marginBottom: 10 }}>
            <div className="field-label">Section {i + 1}</div>
            <input
              className="input"
              value={s.title}
              disabled={!isDraft}
              onChange={(e) => edit(i, { title: e.target.value })}
            />
          </div>
          <textarea
            className="input textarea report-body"
            value={s.body}
            readOnly={!isDraft}
            spellCheck
            rows={Math.min(28, Math.max(5, s.body.split('\n').length + 1))}
            onChange={(e) => edit(i, { body: e.target.value })}
          />
        </div>
      ))}

      {isDraft && (
        <p className="meta" style={{ marginBottom: '1.25rem' }}>
          Formatting: <code>## Heading</code>, <code>- bullet</code>, <code>**bold**</code>, and
          table rows written as <code>| cell | cell |</code> (first row is the header). Text in{' '}
          <code>[[double brackets]]</code> marks something still to do and blocks approval.
        </p>
      )}

      {!isDraft && (
        <div className="detail-section">
          <h3 className="section-title">Customer notifications</h3>
          {report.notifications.length === 0 ? (
            <p className="meta">
              Nobody was emailed: the customer had no active portal user flagged for the AMS report.
            </p>
          ) : (
            <table className="data-table">
              <thead>
                <tr>
                  <th>Recipient</th>
                  <th style={{ width: 120 }}>Result</th>
                  <th style={{ width: 180 }}>When</th>
                  <th>Detail</th>
                </tr>
              </thead>
              <tbody>
                {report.notifications.map((n) => (
                  <tr key={n.id}>
                    <td>{n.email}</td>
                    <td>
                      <span className={`badge badge-notify-${n.status}`}>
                        {n.status === 'sent' ? 'Sent' : n.status === 'failed' ? 'Failed' : 'Not sent'}
                      </span>
                    </td>
                    <td>{when(n.created_at)}</td>
                    <td className="meta">{n.detail}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      )}
    </div>
  )
}
