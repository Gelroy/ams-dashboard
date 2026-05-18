import { useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'

import {
  createOrgDocument,
  deleteOrgDocument,
  getOrganization,
  listOrgUsers,
  updateOrganization,
  updateOrgDocument,
  updateOrgUser,
} from '../api'
import { CustomerAnalyticsSection } from '../components/CustomerAnalyticsSection'
import { CustomerSystemsSection } from '../components/CustomerSystemsSection'
import type {
  AmsLevel,
  EditableOrgFields,
  Organization,
  OrgUser,
  ZabbixStatus,
} from '../types'

const AMS_LEVELS: AmsLevel[] = ['Essential', 'Enhanced', 'Expert']
const ZABBIX_STATUSES: ZabbixStatus[] = ['Good', 'Issue']

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
    help_desk_phone: org.help_desk_phone,
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
        <Field label="Notes" wide>
          <textarea
            className="input textarea"
            rows={3}
            value={draft.notes ?? ''}
            onChange={(e) => set('notes', e.target.value || null)}
          />
        </Field>
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

  return (
    <>
      {error && <div className="error-banner">{error}</div>}
      {users.length === 0 ? (
        <div className="state-cell">
          No users synced yet. Run <code>python manage.py sync_jira_users</code>.
        </div>
      ) : (
        <div className="table-wrap">
          <table className="data-table">
            <thead>
              <tr>
                <th>Name</th>
                <th>Email</th>
                <th>Role</th>
                <th style={{ width: 80 }}>Alerts</th>
                <th style={{ width: 80 }}>Primary</th>
              </tr>
            </thead>
            <tbody>
              {users.map((u) => (
                <tr key={u.id}>
                  <td>
                    <strong>{u.display_name || '—'}</strong>
                    {savingId === u.id && <span className="meta"> · saving…</span>}
                  </td>
                  <td className="meta">{u.email || '—'}</td>
                  <td>
                    <input
                      className="input compact"
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
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </>
  )
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
