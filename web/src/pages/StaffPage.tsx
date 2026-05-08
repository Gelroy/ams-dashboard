import { useEffect, useState } from 'react'

import {
  createStaff,
  deleteStaff,
  listOrganizations,
  listStaff,
  setStaffSmeOrganizations,
  updateStaff,
} from '../api'
import type { Organization, Staff } from '../types'

export function StaffPage() {
  const [staff, setStaff] = useState<Staff[]>([])
  const [orgs, setOrgs] = useState<Organization[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const refresh = () => {
    setLoading(true)
    setError(null)
    Promise.all([listStaff(), listOrganizations({ limit: 200 })])
      .then(([s, o]) => {
        setStaff(s)
        setOrgs(o.results)
      })
      .catch((e: Error) => setError(e.message))
      .finally(() => setLoading(false))
  }
  useEffect(refresh, [])

  return (
    <div>
      <div className="panel-header-row">
        <span className="panel-title">Staff</span>
        <span className="panel-hint">{staff.length} on the team</span>
      </div>
      {error && <div className="error-banner">{error}</div>}
      {loading && <div className="state-cell">Loading…</div>}
      {!loading && staff.length === 0 && (
        <div className="state-cell">
          No staff yet. Add team members so Activities can be assigned.
        </div>
      )}
      {staff.map((s) => (
        <StaffRow key={s.id} staff={s} orgs={orgs} onChanged={refresh} />
      ))}
      <AddStaffForm onAdded={refresh} />
    </div>
  )
}

function StaffRow({
  staff,
  orgs,
  onChanged,
}: {
  staff: Staff
  orgs: Organization[]
  onChanged: () => void
}) {
  const [open, setOpen] = useState(false)
  const [name, setName] = useState(staff.name)
  const [email, setEmail] = useState(staff.email ?? '')
  const [phone, setPhone] = useState(staff.phone ?? '')
  const smeIds = new Set(staff.sme_organization_ids)

  const toggleSme = async (orgId: string) => {
    const next = new Set(smeIds)
    if (next.has(orgId)) next.delete(orgId)
    else next.add(orgId)
    await setStaffSmeOrganizations(staff.id, [...next])
    onChanged()
  }

  return (
    <div className="catalog-card">
      <div className="catalog-row">
        <button className="chevron-btn" onClick={() => setOpen(!open)}>
          {open ? '▼' : '▶'}
        </button>
        <input
          className="input"
          value={name}
          onChange={(e) => setName(e.target.value)}
          onBlur={() => {
            if (name !== staff.name) updateStaff(staff.id, { name }).then(onChanged)
          }}
        />
        <span className="meta">
          {staff.sme_organization_ids.length} customer
          {staff.sme_organization_ids.length === 1 ? '' : 's'}
        </span>
        <button
          className="btn-icon"
          onClick={() => {
            if (window.confirm(`Delete ${staff.name}?`)) deleteStaff(staff.id).then(onChanged)
          }}
        >
          ×
        </button>
      </div>
      {open && (
        <div className="catalog-children">
          <div className="form-grid" style={{ marginBottom: 12 }}>
            <div className="field">
              <div className="field-label">Email</div>
              <input
                className="input"
                value={email}
                placeholder="name@company.com"
                onChange={(e) => setEmail(e.target.value)}
                onBlur={() => {
                  if (email !== (staff.email ?? ''))
                    updateStaff(staff.id, { email: email || null }).then(onChanged)
                }}
              />
            </div>
            <div className="field">
              <div className="field-label">Phone</div>
              <input
                className="input"
                value={phone}
                placeholder="(555) 123-4567"
                onChange={(e) => setPhone(e.target.value)}
                onBlur={() => {
                  if (phone !== (staff.phone ?? ''))
                    updateStaff(staff.id, { phone: phone || null }).then(onChanged)
                }}
              />
            </div>
          </div>

          <div className="field-label" style={{ marginBottom: 4 }}>
            SME for customers
          </div>
          <div className="env-chips">
            {orgs.length === 0 && <span className="meta">No customers in the system yet.</span>}
            {orgs.map((o) => {
              const on = smeIds.has(o.id)
              return (
                <button
                  key={o.id}
                  className={on ? 'env-chip env-chip-on' : 'env-chip env-chip-off'}
                  onClick={() => toggleSme(o.id)}
                >
                  {on ? '✓ ' : ''}
                  {o.display_name}
                </button>
              )
            })}
          </div>
        </div>
      )}
    </div>
  )
}

function AddStaffForm({ onAdded }: { onAdded: () => void }) {
  const [name, setName] = useState('')
  const [email, setEmail] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const submit = async () => {
    if (!name.trim()) return
    setBusy(true)
    setError(null)
    try {
      await createStaff({ name: name.trim(), email: email.trim() || null })
      setName('')
      setEmail('')
      onAdded()
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="add-row">
      <input
        className="input compact"
        placeholder="Name"
        value={name}
        onChange={(e) => setName(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === 'Enter') submit()
        }}
      />
      <input
        className="input compact"
        placeholder="Email (optional)"
        value={email}
        onChange={(e) => setEmail(e.target.value)}
      />
      <button className="btn" disabled={busy || !name.trim()} onClick={submit}>
        + Add Staff
      </button>
      {error && <span className="error-text">{error}</span>}
    </div>
  )
}
