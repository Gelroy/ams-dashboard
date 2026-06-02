import { useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'

import {
  createOrgDocument,
  deleteOrgDocument,
  getOrganization,
  listOrgUsers,
  listPatchHistory,
  updateOrganization,
  updateOrgDocument,
  updateOrgUser,
} from '../api'
import { CustomerAnalyticsSection } from '../components/CustomerAnalyticsSection'
import { CustomerSystemsSection } from '../components/CustomerSystemsSection'
import type {
  AmsLevel,
  Country,
  EditableOrgFields,
  Organization,
  OrgUser,
  PatchHistoryEntry,
  ZabbixStatus,
} from '../types'

const AMS_LEVELS: AmsLevel[] = ['Essential', 'Enhanced', 'Expert']
const ZABBIX_STATUSES: ZabbixStatus[] = ['Good', 'Issue']
const COUNTRIES: Country[] = ['US', 'CA']

export function CustomerDetailPage() {
  const { id = '' } = useParams<{ id: string }>()
  const [org, setOrg] = useState<Organization | null>(null)
  const [users, setUsers] = useState<OrgUser[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    setError(null)
    Promise.all([getOrganization(id), listOrgUsers(id)])
      .then(([orgData, usersData]) => {
        if (cancelled) return
        setOrg(orgData)
        setUsers(usersData.results)
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
  }, [id])

  if (loading) return <div className="state-cell">Loading…</div>
  if (error) return <div className="error-banner">Error: {error}</div>
  if (!org) return <div className="state-cell">Customer not found.</div>

  return (
    <div>
      <div className="breadcrumbs">
        <Link to="/customers">← Customers</Link>
      </div>
      <div className="panel-header-row">
        <span className="panel-title">{org.display_name}</span>
        <span className="panel-hint">
          JIRA: {org.jira_name} · ID: {org.jira_org_id}
        </span>
      </div>

      <CollapsibleSection title="Details">
        <DetailsSection org={org} onUpdated={setOrg} />
      </CollapsibleSection>
      <CollapsibleSection title="Customer Systems">
        <CustomerSystemsSection orgId={id} />
      </CollapsibleSection>
      <CollapsibleSection title="Users">
        <UsersSection orgId={id} users={users} onUsersChanged={setUsers} />
      </CollapsibleSection>
      <CollapsibleSection title="Analytics">
        <CustomerAnalyticsSection orgId={id} />
      </CollapsibleSection>
      <CollapsibleSection title="Patch History">
        <PatchHistorySection orgId={id} />
      </CollapsibleSection>
    </div>
  )
}

function CollapsibleSection({
  title,
  defaultOpen = true,
  children,
}: {
  title: string
  defaultOpen?: boolean
  children: React.ReactNode
}) {
  const [open, setOpen] = useState(defaultOpen)
  return (
    <section className="detail-section collapsible">
      <div
        className="section-header"
        role="button"
        tabIndex={0}
        aria-expanded={open}
        onClick={() => setOpen(!open)}
        onKeyDown={(e) => {
          if (e.key === 'Enter' || e.key === ' ') {
            e.preventDefault()
            setOpen(!open)
          }
        }}
      >
        <span className={open ? 'chevron-btn open' : 'chevron-btn'}>
          {open ? '▼' : '▶'}
        </span>
        <h3 className="section-title">{title}</h3>
      </div>
      <div className="section-body" style={{ display: open ? 'block' : 'none' }}>
        {children}
      </div>
    </section>
  )
}

function DetailsSection({
  org,
  onUpdated,
}: {
  org: Organization
  onUpdated: (o: Organization) => void
}) {
  const [draft, setDraft] = useState<EditableOrgFields>({
    local_name: org.local_name,
    ams_level: org.ams_level,
    zabbix_status: org.zabbix_status,
    country: org.country,
    help_desk_phone: org.help_desk_phone,
    roadmap: org.roadmap,
    notes: org.notes,
  })
  const [saving, setSaving] = useState(false)
  const [saveError, setSaveError] = useState<string | null>(null)
  const [savedAt, setSavedAt] = useState<number | null>(null)

  const set = <K extends keyof EditableOrgFields>(key: K, value: EditableOrgFields[K]) =>
    setDraft((d) => ({ ...d, [key]: value }))

  const save = () => {
    setSaving(true)
    setSaveError(null)
    updateOrganization(org.id, draft)
      .then((updated) => {
        onUpdated(updated)
        setSavedAt(Date.now())
      })
      .catch((e: Error) => setSaveError(e.message))
      .finally(() => setSaving(false))
  }

  return (
    <>
      <div className="form-grid">
        <Field label="Company Name (override)">
          <input
            className="input"
            value={draft.local_name ?? ''}
            placeholder={org.jira_name}
            onChange={(e) => set('local_name', e.target.value || null)}
          />
        </Field>
        <Field label="AMS Level">
          <select
            className="input"
            value={draft.ams_level ?? ''}
            onChange={(e) => set('ams_level', (e.target.value as AmsLevel) || null)}
          >
            <option value="">— Not set —</option>
            {AMS_LEVELS.map((l) => (
              <option key={l} value={l}>
                {l}
              </option>
            ))}
          </select>
        </Field>
        <Field label="Zabbix Status">
          <select
            className="input"
            value={draft.zabbix_status ?? ''}
            onChange={(e) => set('zabbix_status', (e.target.value as ZabbixStatus) || null)}
          >
            <option value="">— Not set —</option>
            {ZABBIX_STATUSES.map((s) => (
              <option key={s} value={s}>
                {s}
              </option>
            ))}
          </select>
        </Field>
        <Field label="Country">
          <select
            className="input"
            value={draft.country ?? ''}
            onChange={(e) => set('country', (e.target.value as Country) || null)}
          >
            <option value="">— Not set —</option>
            {COUNTRIES.map((c) => (
              <option key={c} value={c}>
                {c}
              </option>
            ))}
          </select>
        </Field>
        <Field label="Help Desk #">
          <input
            className="input"
            value={draft.help_desk_phone ?? ''}
            placeholder="5551234567"
            onChange={(e) => set('help_desk_phone', e.target.value || null)}
          />
        </Field>
        <Field label="Documents" wide>
          <DocumentsField org={org} onChanged={onUpdated} />
        </Field>
        <Field label={`SMEs${org.sme_staff.length ? ` (${org.sme_staff.length})` : ''}`} wide>
          {org.sme_staff.length === 0 ? (
            <span className="meta">
              None assigned. Set in the Staff panel.
            </span>
          ) : (
            <div className="sme-inline">
              {org.sme_staff.map((s) => (
                <span key={s.id} className="sme-chip">
                  {s.email ? (
                    <a href={`mailto:${s.email}`}>{s.name}</a>
                  ) : (
                    <strong>{s.name}</strong>
                  )}
                  {s.phone && (
                    <a className="meta" href={`tel:${s.phone}`}>
                      {formatPhone(s.phone)}
                    </a>
                  )}
                </span>
              ))}
            </div>
          )}
        </Field>
        <ExpandableField
          label="Roadmap"
          value={draft.roadmap ?? null}
          onChange={(v) => set('roadmap', v)}
        />
        <ExpandableField
          label="Notes"
          value={draft.notes ?? null}
          onChange={(v) => set('notes', v)}
        />
        <Field label="Open Tickets">
          <span className="meta">
            {org.open_ticket_count ?? '—'}
            {org.ticket_count_synced_at && (
              <> · synced {new Date(org.ticket_count_synced_at).toLocaleString()}</>
            )}
          </span>
        </Field>
        <Field label="Last JIRA Sync">
          <span className="meta">
            {org.jira_synced_at ? new Date(org.jira_synced_at).toLocaleString() : '—'}
          </span>
        </Field>
      </div>
      <div className="form-actions">
        <button className="btn btn-primary" onClick={save} disabled={saving}>
          {saving ? 'Saving…' : 'Save Changes'}
        </button>
        {savedAt && !saving && <span className="saved-indicator">Saved</span>}
        {saveError && <span className="error-text">{saveError}</span>}
      </div>
    </>
  )
}

type DocsMode = 'view' | 'edit' | 'add'

function DocumentsField({
  org,
  onChanged,
}: {
  org: Organization
  onChanged: (o: Organization) => void
}) {
  const docs = org.documents
  const [selectedId, setSelectedId] = useState<string>(docs[0]?.id ?? '')
  const [mode, setMode] = useState<DocsMode>('view')
  const [formDescription, setFormDescription] = useState('')
  const [formUrl, setFormUrl] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const selected = docs.find((d) => d.id === selectedId) ?? docs[0]

  const refresh = async () => {
    const fresh = await getOrganization(org.id)
    onChanged(fresh)
  }

  const open = () => {
    if (!selected) return
    window.open(selected.url, '_blank', 'noopener,noreferrer')
  }

  const startEdit = () => {
    if (!selected) return
    setFormDescription(selected.description)
    setFormUrl(selected.url)
    setError(null)
    setMode('edit')
  }

  const startAdd = () => {
    setFormDescription('')
    setFormUrl('')
    setError(null)
    setMode('add')
  }

  const closeForm = () => {
    setMode('view')
    setError(null)
  }

  const submitDone = async () => {
    const description = formDescription.trim()
    const url = formUrl.trim()
    if (!description || !url) return
    setBusy(true)
    setError(null)
    try {
      if (mode === 'edit' && selected) {
        await updateOrgDocument(org.id, selected.id, { description, url })
      } else if (mode === 'add') {
        const created = await createOrgDocument(org.id, {
          description,
          url,
          position: docs.length,
        })
        setSelectedId(created.id)
      }
      await refresh()
      closeForm()
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setBusy(false)
    }
  }

  const submitDelete = async () => {
    if (mode === 'add') {
      // Nothing persisted yet — just discard the form.
      closeForm()
      return
    }
    if (!selected) return
    if (!window.confirm(`Delete "${selected.description}"?`)) return
    setBusy(true)
    setError(null)
    try {
      await deleteOrgDocument(org.id, selected.id)
      await refresh()
      // Select the next remaining doc, if any.
      const remaining = docs.filter((d) => d.id !== selected.id)
      setSelectedId(remaining[0]?.id ?? '')
      closeForm()
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="documents-field">
      <div className="documents-row">
        {docs.length > 0 && (
          <>
            <select
              className="input"
              style={{ minWidth: 240 }}
              value={selected?.id ?? ''}
              onChange={(e) => {
                setSelectedId(e.target.value)
                if (mode !== 'view') closeForm()
              }}
              disabled={mode !== 'view'}
            >
              {docs.map((d) => (
                <option key={d.id} value={d.id}>
                  {d.description}
                </option>
              ))}
            </select>
            <button className="btn" onClick={open} disabled={!selected || mode !== 'view'}>
              Open
            </button>
            <button
              className={mode === 'edit' ? 'btn btn-primary' : 'btn'}
              onClick={mode === 'edit' ? closeForm : startEdit}
              disabled={!selected || mode === 'add'}
            >
              Edit
            </button>
          </>
        )}
        {docs.length === 0 && <span className="meta">No documents yet.</span>}
        <button
          className={mode === 'add' ? 'btn btn-primary' : 'btn'}
          onClick={mode === 'add' ? closeForm : startAdd}
          disabled={mode === 'edit'}
        >
          Add
        </button>
      </div>

      {mode !== 'view' && (
        <div className="documents-form">
          <div className="field">
            <div className="field-label">Description</div>
            <input
              className="input"
              value={formDescription}
              autoFocus
              onChange={(e) => setFormDescription(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter') submitDone()
              }}
            />
          </div>
          <div className="field">
            <div className="field-label">URL</div>
            <input
              className="input"
              type="url"
              placeholder="https://…"
              value={formUrl}
              onChange={(e) => setFormUrl(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter') submitDone()
              }}
            />
          </div>
          <div className="form-actions">
            <button
              className="btn btn-primary"
              disabled={busy || !formDescription.trim() || !formUrl.trim()}
              onClick={submitDone}
            >
              Done
            </button>
            <button className="btn" disabled={busy} onClick={submitDelete}>
              Delete
            </button>
            {error && <span className="error-text">{error}</span>}
          </div>
        </div>
      )}
    </div>
  )
}

function formatPhone(raw: string): string {
  const d = raw.replace(/\D/g, '')
  if (d.length === 10) return `(${d.slice(0, 3)}) ${d.slice(3, 6)}-${d.slice(6)}`
  return raw
}

/** Copy `text` to the system clipboard. Prefers the async Clipboard API
 *  (only available in secure contexts — i.e., HTTPS or localhost), and
 *  falls back to the older execCommand path with a hidden textarea so the
 *  header-click email copy works during the HTTP-only window before our
 *  cert lands. Returns true if the copy succeeded. */
async function copyToClipboard(text: string): Promise<boolean> {
  // Prefer the async API when allowed.
  if (typeof navigator !== 'undefined' && navigator.clipboard && window.isSecureContext) {
    try {
      await navigator.clipboard.writeText(text)
      return true
    } catch {
      // fall through to legacy path
    }
  }
  // Legacy fallback — works on http:// pages where the async API is gated.
  try {
    const ta = document.createElement('textarea')
    ta.value = text
    ta.style.position = 'fixed'
    ta.style.top = '-1000px'
    ta.style.opacity = '0'
    ta.setAttribute('readonly', '')
    document.body.appendChild(ta)
    ta.select()
    ta.setSelectionRange(0, text.length)
    const ok = document.execCommand('copy')
    document.body.removeChild(ta)
    return ok
  } catch {
    return false
  }
}

function UsersSection({
  orgId,
  users,
  onUsersChanged,
}: {
  orgId: string
  users: OrgUser[]
  onUsersChanged: (u: OrgUser[]) => void
}) {
  const [savingId, setSavingId] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  // JIRA syncs every user assigned to an org, but the AMS team only deals
  // with a subset. Hidden rows stay in the DB (so sync keeps them current
  // in case they become relevant again) but disappear from the table until
  // this is toggled on.
  const [showHidden, setShowHidden] = useState(false)
  // Transient feedback after a header-click copy. Cleared by a timer.
  const [copyMsg, setCopyMsg] = useState<string | null>(null)

  const visibleUsers = showHidden ? users : users.filter((u) => !u.is_hidden)
  const hiddenCount = users.filter((u) => u.is_hidden).length

  const patchUser = (userId: string, patch: Partial<OrgUser>) => {
    // Optimistic update
    onUsersChanged(users.map((u) => (u.id === userId ? { ...u, ...patch } : u)))
    setSavingId(userId)
    setError(null)
    updateOrgUser(orgId, userId, patch)
      .then((updated) => {
        onUsersChanged(users.map((u) => (u.id === userId ? updated : u)))
      })
      .catch((e: Error) => setError(e.message))
      .finally(() => setSavingId(null))
  }

  const copyEmailsForFlag = (
    flag: 'alerts_enabled' | 'is_primary' | 'ams_report',
    label: string,
  ) => {
    const emails = users
      .filter((u) => u[flag] && u.email)
      .map((u) => (u.email as string).trim())
      .filter(Boolean)
    if (emails.length === 0) {
      flashCopyMsg(`No users have ${label} checked.`)
      return
    }
    const text = emails.join('; ')
    copyToClipboard(text)
      .then((ok) => {
        flashCopyMsg(
          ok
            ? `Copied ${emails.length} ${label} email${emails.length === 1 ? '' : 's'}`
            : 'Copy failed — your browser blocked clipboard access.',
        )
      })
      .catch(() => flashCopyMsg('Copy failed — your browser blocked clipboard access.'))
  }

  const flashCopyMsg = (msg: string) => {
    setCopyMsg(msg)
    window.setTimeout(() => setCopyMsg(null), 2500)
  }

  return (
    <>
      {error && <div className="error-banner">{error}</div>}

      <div className="filter-bar">
        <label className="filter-checkbox">
          <input
            type="checkbox"
            checked={showHidden}
            onChange={(e) => setShowHidden(e.target.checked)}
          />
          Show hidden users
          {hiddenCount > 0 && (
            <span className="meta"> ({hiddenCount} hidden)</span>
          )}
        </label>
        {copyMsg && <span className="meta">· {copyMsg}</span>}
      </div>

      {users.length === 0 ? (
        <div className="state-cell">
          No users synced yet. Run <code>python manage.py sync_jira_users</code>.
        </div>
      ) : visibleUsers.length === 0 ? (
        <div className="state-cell">
          All {users.length} users are hidden. Toggle &ldquo;Show hidden users&rdquo; above
          to bring them back.
        </div>
      ) : (
        <div className="table-wrap">
          <table className="data-table">
            <thead>
              <tr>
                <th>Name</th>
                <th>Email</th>
                <th style={{ width: 120 }}>Role</th>
                <th
                  style={{ width: 80, cursor: 'pointer' }}
                  onClick={() => copyEmailsForFlag('alerts_enabled', 'Alerts')}
                  title="Click to copy emails of users with Alerts checked"
                >
                  Alerts <span className="meta">⧉</span>
                </th>
                <th
                  style={{ width: 80, cursor: 'pointer' }}
                  onClick={() => copyEmailsForFlag('is_primary', 'Primary')}
                  title="Click to copy emails of users with Primary checked"
                >
                  Primary <span className="meta">⧉</span>
                </th>
                <th
                  style={{ width: 100, cursor: 'pointer' }}
                  onClick={() => copyEmailsForFlag('ams_report', 'AMS Report')}
                  title="Click to copy emails of users with AMS Report checked"
                >
                  AMS Report <span className="meta">⧉</span>
                </th>
                <th style={{ width: 60 }}>Hide</th>
              </tr>
            </thead>
            <tbody>
              {visibleUsers.map((u) => (
                <tr key={u.id} style={u.is_hidden ? { opacity: 0.5 } : undefined}>
                  <td>
                    <strong>{u.display_name || '—'}</strong>
                    {savingId === u.id && <span className="meta"> · saving…</span>}
                  </td>
                  <td className="meta">{u.email || '—'}</td>
                  <td>
                    <input
                      className="input compact"
                      style={{ width: 100 }}
                      value={u.role ?? ''}
                      placeholder="—"
                      onChange={(e) =>
                        onUsersChanged(
                          users.map((x) => (x.id === u.id ? { ...x, role: e.target.value } : x)),
                        )
                      }
                      onBlur={(e) => patchUser(u.id, { role: e.target.value || null })}
                    />
                  </td>
                  <td style={{ textAlign: 'center' }}>
                    <input
                      type="checkbox"
                      checked={u.alerts_enabled}
                      onChange={(e) => patchUser(u.id, { alerts_enabled: e.target.checked })}
                    />
                  </td>
                  <td style={{ textAlign: 'center' }}>
                    <input
                      type="checkbox"
                      checked={u.is_primary}
                      onChange={(e) => patchUser(u.id, { is_primary: e.target.checked })}
                    />
                  </td>
                  <td style={{ textAlign: 'center' }}>
                    <input
                      type="checkbox"
                      checked={u.ams_report}
                      onChange={(e) => patchUser(u.id, { ams_report: e.target.checked })}
                    />
                  </td>
                  <td style={{ textAlign: 'center' }}>
                    <input
                      type="checkbox"
                      checked={u.is_hidden}
                      onChange={(e) => patchUser(u.id, { is_hidden: e.target.checked })}
                      title={u.is_hidden ? 'Currently hidden — uncheck to restore' : 'Hide this user from the default view'}
                    />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </>
  )
}

function PatchHistorySection({ orgId }: { orgId: string }) {
  const [entries, setEntries] = useState<PatchHistoryEntry[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [envFilter, setEnvFilter] = useState('')

  useEffect(() => {
    setLoading(true)
    setError(null)
    listPatchHistory({ organization: orgId })
      .then(setEntries)
      .catch((e: Error) => setError(e.message))
      .finally(() => setLoading(false))
  }, [orgId])

  if (loading) return <div className="state-cell">Loading…</div>
  if (error) return <div className="error-banner">{error}</div>
  if (entries.length === 0) {
    return (
      <div className="state-cell">
        No patches recorded yet for this customer. Rows appear here when a
        Patch Execution is finalized (one row per software release applied).
      </div>
    )
  }

  // Distinct envs for the filter dropdown.
  const envNames = Array.from(new Set(entries.map((e) => e.environment_name))).sort()

  // Apply env filter.
  const visible = envFilter
    ? entries.filter((e) => e.environment_name === envFilter)
    : entries

  // Group by software_name. Within each, sort ascending by patched_on so
  // the row order *is* the evolution story (oldest → newest, .10 → .11 → .12).
  const bySoftware = new Map<string, PatchHistoryEntry[]>()
  for (const e of visible) {
    const arr = bySoftware.get(e.software_name) ?? []
    arr.push(e)
    bySoftware.set(e.software_name, arr)
  }
  for (const arr of bySoftware.values()) {
    arr.sort((a, b) => a.patched_on.localeCompare(b.patched_on))
  }
  const softwareNames = Array.from(bySoftware.keys()).sort()

  return (
    <>
      <div className="filter-bar">
        <label className="filter-checkbox">
          Environment:
          <select
            className="input compact"
            value={envFilter}
            onChange={(e) => setEnvFilter(e.target.value)}
            style={{ marginLeft: '0.5rem' }}
          >
            <option value="">All</option>
            {envNames.map((n) => (
              <option key={n} value={n}>
                {n}
              </option>
            ))}
          </select>
        </label>
        <span className="meta">
          {visible.length} patch{visible.length === 1 ? '' : 'es'} across{' '}
          {softwareNames.length} software item{softwareNames.length === 1 ? '' : 's'}
        </span>
      </div>

      {softwareNames.map((name) => {
        const rows = bySoftware.get(name)!
        return (
          <div key={name} className="patch-history-software">
            <h4 className="patch-history-heading">{name}</h4>
            <div className="table-wrap">
              <table className="data-table">
                <thead>
                  <tr>
                    <th style={{ width: 130 }}>Date</th>
                    <th style={{ width: 110 }}>Environment</th>
                    <th>Release</th>
                  </tr>
                </thead>
                <tbody>
                  {rows.map((e) => (
                    <tr key={e.id}>
                      <td>{formatPatchDate(e.patched_on)}</td>
                      <td>{e.environment_name}</td>
                      <td>
                        {e.from_release ? (
                          <>
                            <span className="meta">{e.from_release}</span>
                            {' → '}
                            <strong>{e.to_release}</strong>
                          </>
                        ) : (
                          <>
                            <span className="meta">initial</span>
                            {' → '}
                            <strong>{e.to_release}</strong>
                          </>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )
      })}
    </>
  )
}

function formatPatchDate(iso: string): string {
  // PatchHistory.patched_on is a date-only string (YYYY-MM-DD). Anchor to
  // local midnight so Date() doesn't apply a TZ shift.
  const d = new Date(iso + 'T00:00:00')
  return d.toLocaleDateString(undefined, {
    year: 'numeric',
    month: 'short',
    day: 'numeric',
  })
}

function Field({
  label,
  wide,
  children,
}: {
  label: string
  wide?: boolean
  children: React.ReactNode
}) {
  return (
    <div className={wide ? 'field field-wide' : 'field'}>
      <div className="field-label">{label}</div>
      <div className="field-control">{children}</div>
    </div>
  )
}

/** Collapsible long-form text field. Wide by default (spans the form grid),
 *  collapsed when first rendered. Summary shows the label + a short status
 *  hint so users can tell at a glance whether content exists. */
function ExpandableField({
  label,
  value,
  onChange,
  rows = 6,
}: {
  label: string
  value: string | null
  onChange: (next: string | null) => void
  rows?: number
}) {
  const trimmed = (value ?? '').trim()
  const hint = trimmed ? `${trimmed.length} chars` : 'empty'
  return (
    <details className="field field-wide expandable-field">
      <summary className="field-label expandable-summary">
        {label}
        <span className="meta" style={{ marginLeft: 8 }}>· {hint}</span>
      </summary>
      <textarea
        className="input textarea"
        rows={rows}
        value={value ?? ''}
        onChange={(e) => onChange(e.target.value || null)}
        style={{ marginTop: 6, width: '100%' }}
      />
    </details>
  )
}
