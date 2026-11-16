import { useEffect, useState } from 'react'

import { getDocumentPdf, getDocuments, getMe, type Me, type PortalDocument } from '../api'
import { Shell } from '../components/Shell'

const published = (iso: string) =>
  new Date(iso).toLocaleDateString(undefined, { day: 'numeric', month: 'short', year: 'numeric' })

const size = (bytes: number | null) =>
  bytes == null ? '' : bytes < 1_048_576 ? `${Math.ceil(bytes / 1024)} KB` : `${(bytes / 1_048_576).toFixed(1)} MB`

/** The customer's published documents — today, the monthly AMS reports. */
export function DocumentsPage() {
  const [me, setMe] = useState<Me | null>(null)
  const [documents, setDocuments] = useState<PortalDocument[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [opening, setOpening] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    Promise.all([getMe(), getDocuments()])
      .then(([m, d]) => {
        if (cancelled) return
        setMe(m)
        setDocuments(d)
      })
      .catch((e: unknown) => {
        if (!cancelled) setError(e instanceof Error ? e.message : 'Could not load your documents.')
      })
    return () => {
      cancelled = true
    }
  }, [])

  /** Fetch the PDF with the session token, then either show it in a new
   *  tab or save it. The tab is opened before the fetch so the browser
   *  treats it as a response to the click. */
  async function open(doc: PortalDocument, mode: 'view' | 'save') {
    const tab = mode === 'view' ? window.open('', '_blank') : null
    setOpening(doc.id)
    setError(null)
    try {
      const url = URL.createObjectURL(await getDocumentPdf(doc.id))
      if (tab) {
        tab.location.href = url
      } else {
        const link = document.createElement('a')
        link.href = url
        link.download = doc.filename
        link.click()
      }
      window.setTimeout(() => URL.revokeObjectURL(url), 60_000)
    } catch (e) {
      tab?.close()
      setError(e instanceof Error ? e.message : 'The document could not be opened.')
    } finally {
      setOpening(null)
    }
  }

  return (
    <Shell email={me?.email ?? null}>
      {me && <p className="eyebrow">{me.organization.name}</p>}
      <h1>Documents</h1>
      <p className="muted">Reports published for your organization by the AMS team.</p>

      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}
      {!documents && !error && <p className="muted">Loading…</p>}

      {documents && documents.length === 0 && (
        <section className="card empty">
          <p>No documents have been published yet.</p>
          <p className="muted">
            Your monthly AMS report will appear here, and you will get an email when it does.
          </p>
        </section>
      )}

      {documents && documents.length > 0 && (
        <section className="card documents">
          <table>
            <thead>
              <tr>
                <th>Report</th>
                <th>Published</th>
                <th className="num">Size</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {documents.map((doc) => (
                <tr key={doc.id}>
                  <td>
                    <strong>{doc.period_label}</strong>
                    <div className="muted small">{doc.title}</div>
                  </td>
                  <td>{published(doc.published_at)}</td>
                  <td className="num">{size(doc.size)}</td>
                  <td className="doc-actions">
                    <button
                      type="button"
                      className="primary compact"
                      disabled={opening !== null}
                      onClick={() => void open(doc, 'view')}
                    >
                      {opening === doc.id ? 'Opening…' : 'View'}
                    </button>
                    <button
                      type="button"
                      className="quiet"
                      disabled={opening !== null}
                      onClick={() => void open(doc, 'save')}
                    >
                      Download
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      )}
    </Shell>
  )
}
