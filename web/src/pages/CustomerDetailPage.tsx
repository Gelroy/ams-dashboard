import { useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'

import { getOrganization, listOrgUsers, updateOrganization, updateOrgUser } from '../api'
import type { AmsLevel, EditableOrgFields, Organization, OrgUser, ZabbixStatus } from '../types'

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

      <DetailsSection org={org} onUpdated={setOrg} />
      <UsersSection orgId={id} users={users} onUsersChanged={setUsers} />
    </div>
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
    connection_guide_url: org.connection_guide_url,
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
    <section className="detail-section">
      <h3 className="section-title">Details</h3>
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
        <Field label="Connection Guide URL" wide>
          <input
            className="input"
            type="url"
            value={draft.connection_guide_url ?? ''}
            placeholder="https://…"
            onChange={(e) => set('connection_guide_url', e.target.value || null)}
          />
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
    </section>
  )
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
    <section className="detail-section">
      <h3 className="section-title">Users</h3>
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
    </section>
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
