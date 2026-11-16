import { useEffect, useState } from 'react'

import { apiErrorDetail, listOrganizations } from '../api'
import {
  createTemplate,
  deleteTemplate,
  getTagReference,
  listTemplates,
  openPdfWhenReady,
  previewTemplate,
  previousMonth,
  updateTemplate,
  type ReportSection,
  type ReportTemplate,
  type ReportTemplateDraft,
  type TagReference,
} from '../reportsApi'
import type { Organization } from '../types'

const BLANK: ReportTemplateDraft = {
  name: '',
  description: '',
  report_title: 'AMS Monthly Report',
  is_default: false,
  sections: [
    {
      title: 'Overview',
      body: 'This report was generated for {customerName} on {dateTime}.',
    },
  ],
}

const toDraft = (t: ReportTemplate): ReportTemplateDraft => ({
  name: t.name,
  description: t.description,
  report_title: t.report_title,
  is_default: t.is_default,
  sections: t.sections,
})

/** Report templates: section text that mixes fixed wording with {tags}
 *  filled in for each customer when a draft is generated. */
export function ReportTemplatesPage() {
  const [templates, setTemplates] = useState<ReportTemplate[] | null>(null)
  const [selected, setSelected] = useState<string | 'new' | null>(null)
  const [draft, setDraft] = useState<ReportTemplateDraft>(BLANK)
  const [dirty, setDirty] = useState(false)
  const [reference, setReference] = useState<TagReference | null>(null)
  const [orgs, setOrgs] = useState<Organization[]>([])
  const [previewOrg, setPreviewOrg] = useState('')
  const [previewPeriod, setPreviewPeriod] = useState(previousMonth())
  const [busy, setBusy] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [notice, setNotice] = useState<string | null>(null)

  const open = (t: ReportTemplate) => {
    setSelected(t.id)
    setDraft(toDraft(t))
    setDirty(false)
  }

  useEffect(() => {
    let cancelled = false
    Promise.all([
      listTemplates(),
      getTagReference(),
      listOrganizations({ limit: 200, has_ams_level: true }),
    ])
      .then(([list, tags, organizations]) => {
        if (cancelled) return
        setTemplates(list)
        setReference(tags)
        setOrgs(organizations.results)
        setPreviewOrg(organizations.results[0]?.id ?? '')
        const first = list.find((t) => t.is_default) ?? list[0]
        if (first) open(first)
      })
      .catch((e: unknown) => {
        if (!cancelled) setError(apiErrorDetail(e))
      })
    return () => {
      cancelled = true
    }
  }, [])

  const change = (patch: Partial<ReportTemplateDraft>) => {
    setDraft((d) => ({ ...d, ...patch }))
    setDirty(true)
  }
  const changeSection = (index: number, patch: Partial<ReportSection>) =>
    change({ sections: draft.sections.map((s, i) => (i === index ? { ...s, ...patch } : s)) })
  const moveSection = (index: number, by: number) => {
    const next = [...draft.sections]
    const [item] = next.splice(index, 1)
    next.splice(index + by, 0, item)
    change({ sections: next })
  }

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

  const leave = () => !dirty || window.confirm('Discard your unsaved changes to this template?')

  const save = () =>
    run('save', async () => {
      const saved =
        selected === 'new' || selected === null
          ? await createTemplate(draft)
          : await updateTemplate(selected, draft)
      setTemplates(await listTemplates())
      open(saved)
      return 'Template saved. It applies to drafts generated from now on.'
    })

  const remove = () => {
    const current = templates?.find((t) => t.id === selected)
    if (!current || !window.confirm(`Delete the template “${current.name}”?`)) return
    void run('delete', async () => {
      await deleteTemplate(current.id)
      const list = await listTemplates()
      setTemplates(list)
      const next = list.find((t) => t.is_default) ?? list[0]
      if (next) open(next)
      else {
        setSelected('new')
        setDraft(BLANK)
      }
    })
  }

  const preview = () =>
    run('preview', () =>
      openPdfWhenReady(
        previewTemplate({
          organization: previewOrg,
          period: previewPeriod,
          report_title: draft.report_title,
          sections: draft.sections,
        }),
      ),
    )

  return (
    <div>
      <div className="panel-header-row">
        <span className="panel-title">Report Templates</span>
        <span className="panel-hint">
          Fixed wording plus tags such as {'{customerName}'} that are filled in for each customer.
        </span>
      </div>

      {error && <div className="error-banner">{error}</div>}
      {notice && <div className="notice-banner">{notice}</div>}
      {!templates && !error && <div className="state-cell">Loading…</div>}

      {templates && (
        <>
          <div className="tabs">
            {templates.map((t) => (
              <button
                key={t.id}
                className={t.id === selected ? 'tab tab-active' : 'tab'}
                onClick={() => leave() && open(t)}
              >
                {t.name}
                {t.is_default ? ' (default)' : ''}
              </button>
            ))}
            <button
              className={selected === 'new' ? 'tab tab-active' : 'tab'}
              onClick={() => {
                if (!leave()) return
                setSelected('new')
                setDraft(BLANK)
                setDirty(false)
              }}
            >
              + New template
            </button>
          </div>

          <div className="template-layout">
            <div>
              <div className="detail-section">
                <div className="form-grid">
                  <div className="field">
                    <div className="field-label">Template name</div>
                    <input
                      className="input"
                      value={draft.name}
                      onChange={(e) => change({ name: e.target.value })}
                    />
                  </div>
                  <div className="field">
                    <div className="field-label">Title printed on the report</div>
                    <input
                      className="input"
                      value={draft.report_title}
                      onChange={(e) => change({ report_title: e.target.value })}
                    />
                  </div>
                  <div className="field field-wide">
                    <div className="field-label">Notes for the team</div>
                    <input
                      className="input"
                      value={draft.description}
                      onChange={(e) => change({ description: e.target.value })}
                    />
                  </div>
                  <label className="filter-checkbox field-wide">
                    <input
                      type="checkbox"
                      checked={draft.is_default}
                      onChange={(e) => change({ is_default: e.target.checked })}
                    />
                    Use this template when drafts are generated
                  </label>
                </div>
              </div>

              {draft.sections.map((s, i) => (
                <div className="detail-section" key={i}>
                  <div className="template-section-head">
                    <div className="field" style={{ flex: 1 }}>
                      <div className="field-label">Section {i + 1} heading</div>
                      <input
                        className="input"
                        value={s.title}
                        onChange={(e) => changeSection(i, { title: e.target.value })}
                      />
                    </div>
                    <button
                      className="btn-link"
                      disabled={i === 0}
                      title="Move up"
                      onClick={() => moveSection(i, -1)}
                    >
                      ↑
                    </button>
                    <button
                      className="btn-link"
                      disabled={i === draft.sections.length - 1}
                      title="Move down"
                      onClick={() => moveSection(i, 1)}
                    >
                      ↓
                    </button>
                    <button
                      className="btn-link"
                      disabled={draft.sections.length === 1}
                      onClick={() =>
                        window.confirm(`Remove the section “${s.title || 'untitled'}”?`) &&
                        change({ sections: draft.sections.filter((_, n) => n !== i) })
                      }
                    >
                      Remove
                    </button>
                  </div>
                  <textarea
                    className="input textarea report-body"
                    value={s.body}
                    spellCheck
                    rows={Math.min(30, Math.max(6, s.body.split('\n').length + 1))}
                    onChange={(e) => changeSection(i, { body: e.target.value })}
                  />
                </div>
              ))}

              <div className="add-row" style={{ marginBottom: '1.25rem' }}>
                <button
                  className="btn"
                  onClick={() => change({ sections: [...draft.sections, { title: '', body: '' }] })}
                >
                  + Add section
                </button>
              </div>

              <div className="detail-section">
                <div className="form-actions" style={{ marginTop: 0, flexWrap: 'wrap' }}>
                  <button
                    className="btn btn-primary"
                    disabled={busy !== null || !dirty}
                    onClick={save}
                  >
                    {busy === 'save' ? 'Saving…' : 'Save template'}
                  </button>
                  <span className="meta">Preview with</span>
                  <select
                    className="input"
                    aria-label="Customer to preview with"
                    value={previewOrg}
                    onChange={(e) => setPreviewOrg(e.target.value)}
                  >
                    {orgs.map((o) => (
                      <option key={o.id} value={o.id}>
                        {o.display_name}
                      </option>
                    ))}
                  </select>
                  <input
                    className="input"
                    type="month"
                    aria-label="Month to preview"
                    value={previewPeriod}
                    onChange={(e) => e.target.value && setPreviewPeriod(e.target.value)}
                  />
                  <button className="btn" disabled={busy !== null || !previewOrg} onClick={preview}>
                    {busy === 'preview' ? 'Rendering…' : 'Preview PDF'}
                  </button>
                  {selected !== 'new' && selected !== null && (
                    <button className="btn-link" disabled={busy !== null} onClick={remove}>
                      Delete template
                    </button>
                  )}
                </div>
                <p className="meta" style={{ marginTop: 10 }}>
                  The preview uses your unsaved text and the chosen customer's real data. Saving
                  does not change drafts or reports that already exist.
                </p>
              </div>
            </div>

            <aside className="detail-section tag-reference">
              <h3 className="section-title">Tags</h3>
              <dl>
                {reference?.tags.map((t) => (
                  <div key={t.tag}>
                    <dt>
                      <code>{`{${t.tag}}`}</code>
                    </dt>
                    <dd>{t.description}</dd>
                  </div>
                ))}
              </dl>
              {reference && reference.metrics_paths.length > 0 && (
                <>
                  <h3 className="section-title">
                    Monitoring values delivered ({reference.metrics_sample_period})
                  </h3>
                  <ul className="tag-paths">
                    {reference.metrics_paths.map((p) => (
                      <li key={p}>
                        <code>{p}</code>
                      </li>
                    ))}
                  </ul>
                </>
              )}
              <h3 className="section-title">Syntax</h3>
              <ul className="tag-paths">
                <li>
                  <code>{'{value|round:2}'}</code> <code>{'{day|date}'}</code>{' '}
                  <code>{'{value|default:n/a}'}</code>
                </li>
                <li>
                  <code>{'{#each list}'}</code> … <code>{'{#else}'}</code> … <code>{'{/each}'}</code>{' '}
                  repeats lines for every item
                </li>
                <li>
                  <code>{'{#if value}'}</code> … <code>{'{/if}'}</code> shows text only when the value
                  exists
                </li>
                <li>
                  <code>## Heading</code>, <code>- bullet</code>, <code>**bold**</code>,{' '}
                  <code>| cell | cell |</code> table rows
                </li>
                <li>
                  <code>[[note]]</code> marks something staff must write before approval
                </li>
              </ul>
            </aside>
          </div>
        </>
      )}
    </div>
  )
}
