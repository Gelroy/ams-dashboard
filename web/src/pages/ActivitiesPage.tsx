import { useEffect, useState } from 'react'

import {
  completeActivity,
  createActivity,
  deleteActivity,
  listActivities,
  listOrganizations,
  listStaff,
  updateActivity,
} from '../api'
import type {
  Activity,
  ActivityPriority,
  ActivityStatus,
  ActivityType,
  Organization,
  Staff,
} from '../types'

const TYPES: ActivityType[] = ['Meeting', 'Patch', 'Cert', 'Review', 'Other']
const PRIORITIES: ActivityPriority[] = ['High', 'Medium', 'Low']

export function ActivitiesPage() {
  const [items, setItems] = useState<Activity[]>([])
  const [orgs, setOrgs] = useState<Organization[]>([])
  const [staff, setStaff] = useState<Staff[]>([])
  const [filter, setFilter] = useState<ActivityStatus | 'all'>('scheduled')
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [showAdd, setShowAdd] = useState(false)

  const refresh = () => {
    setLoading(true)
    setError(null)
    Promise.all([listActivities(filter), listOrganizations({ limit: 200 }), listStaff()])
      .then(([a, o, s]) => {
        setItems(a)
        setOrgs(o.results)
        setStaff(s)
      })
      .catch((e: Error) => setError(e.message))
      .finally(() => setLoading(false))
  }
  useEffect(refresh, [filter])

  return (
    <div>
      <div className="panel-header-row">
        <span className="panel-title">Activities</span>
        <span className="panel-hint">{items.length} shown</span>
      </div>

      <div className="filter-bar">
        <select
          className="input"
          value={filter}
          onChange={(e) => setFilter(e.target.value as ActivityStatus | 'all')}
        >
          <option value="scheduled">Open</option>
          <option value="completed">Completed</option>
          <option value="all">All</option>
        </select>
        <button className="btn" onClick={() => setShowAdd(!showAdd)}>
          {showAdd ? 'Cancel' : '+ Add Activity'}
        </button>
      </div>

      {showAdd && (
        <AddActivityForm
          orgs={orgs}
          staff={staff}
          onAdded={() => {
            setShowAdd(false)
            refresh()
          }}
        />
      )}

      {error && <div className="error-banner">{error}</div>}
      {loading && <div className="state-cell">Loading…</div>}
      {!loading && items.length === 0 && (
        <div className="state-cell">No activities for this filter.</div>
      )}

      {items.map((a) => (
        <ActivityCard key={a.id} activity={a} orgs={orgs} staff={staff} onChanged={refresh} />
      ))}
    </div>
  )
}

function ActivityCard({
  activity,
  orgs,
  staff,
  onChanged,
}: {
  activity: Activity
  orgs: Organization[]
  staff: Staff[]
  onChanged: () => void
}) {
  const [open, setOpen] = useState(false)
  const isCompleted = activity.status === 'completed'

  return (
    <div className="catalog-card" style={{ opacity: isCompleted ? 0.6 : 1 }}>
      <div className="catalog-row">
        <button className="chevron-btn" onClick={() => setOpen(!open)}>
          {open ? '▼' : '▶'}
        </button>
        <strong>{activity.name}</strong>
        <span className="meta">{new Date(activity.scheduled_at).toLocaleString()}</span>
        <span className="badge">{activity.type}</span>
        <span className="badge">{activity.priority}</span>
        {activity.organization_name && (
          <span className="meta">{activity.organization_name}</span>
        )}
        {!isCompleted && (
          <button
            className="btn"
            style={{ padding: '2px 10px', fontSize: 11 }}
            onClick={() => completeActivity(activity.id).then(onChanged)}
          >
            Complete
          </button>
        )}
        <button
          className="btn-icon"
          onClick={() => {
            if (window.confirm(`Delete ${activity.name}?`))
              deleteActivity(activity.id).then(onChanged)
          }}
        >
          ×
        </button>
      </div>
      {open && (
        <div className="catalog-children">
          <ActivityForm
            activity={activity}
            orgs={orgs}
            staff={staff}
            onSaved={onChanged}
          />
        </div>
      )}
    </div>
  )
}

function ActivityForm({
  activity,
  orgs,
  staff,
  onSaved,
}: {
  activity: Activity
  orgs: Organization[]
  staff: Staff[]
  onSaved: () => void
}) {
  const dt = new Date(activity.scheduled_at)
  const [date, setDate] = useState(dt.toISOString().slice(0, 10))
  const [time, setTime] = useState(dt.toTimeString().slice(0, 5))
  const [type, setType] = useState(activity.type)
  const [priority, setPriority] = useState(activity.priority)
  const [orgId, setOrgId] = useState(activity.organization ?? '')
  const [staffId, setStaffId] = useState(activity.assigned_staff ?? '')
  const [duration, setDuration] = useState(activity.duration ?? '')
  const [notes, setNotes] = useState(activity.notes ?? '')

  const save = async () => {
    const scheduled_at = new Date(`${date}T${time || '00:00'}:00`).toISOString()
    await updateActivity(activity.id, {
      scheduled_at,
      type,
      priority,
      organization: orgId || null,
      assigned_staff: staffId || null,
      duration: duration || null,
      notes: notes || null,
    })
    onSaved()
  }

  return (
    <div className="form-grid">
      <div className="field">
        <div className="field-label">Date</div>
        <input
          type="date"
          className="input"
          value={date}
          onChange={(e) => setDate(e.target.value)}
        />
      </div>
      <div className="field">
        <div className="field-label">Time</div>
        <input
          type="time"
          className="input"
          value={time}
          onChange={(e) => setTime(e.target.value)}
        />
      </div>
      <div className="field">
        <div className="field-label">Type</div>
        <select className="input" value={type} onChange={(e) => setType(e.target.value as ActivityType)}>
          {TYPES.map((t) => (
            <option key={t} value={t}>
              {t}
            </option>
          ))}
        </select>
      </div>
      <div className="field">
        <div className="field-label">Priority</div>
        <select
          className="input"
          value={priority}
          onChange={(e) => setPriority(e.target.value as ActivityPriority)}
        >
          {PRIORITIES.map((p) => (
            <option key={p} value={p}>
              {p}
            </option>
          ))}
        </select>
      </div>
      <div className="field">
        <div className="field-label">Customer</div>
        <select className="input" value={orgId} onChange={(e) => setOrgId(e.target.value)}>
          <option value="">— None —</option>
          {orgs.map((o) => (
            <option key={o.id} value={o.id}>
              {o.display_name}
            </option>
          ))}
        </select>
      </div>
      <div className="field">
        <div className="field-label">Assigned to</div>
        <select className="input" value={staffId} onChange={(e) => setStaffId(e.target.value)}>
          <option value="">— None —</option>
          {staff.map((s) => (
            <option key={s.id} value={s.id}>
              {s.name}
            </option>
          ))}
        </select>
      </div>
      <div className="field">
        <div className="field-label">Duration</div>
        <input
          className="input"
          value={duration}
          placeholder="e.g. 2 hrs"
          onChange={(e) => setDuration(e.target.value)}
        />
      </div>
      <div className="field"></div>
      <div className="field field-wide">
        <div className="field-label">Notes</div>
        <textarea
          className="input textarea"
          rows={3}
          value={notes}
          onChange={(e) => setNotes(e.target.value)}
        />
      </div>
      <div className="form-actions field-wide">
        <button className="btn btn-primary" onClick={save}>
          Save Changes
        </button>
      </div>
    </div>
  )
}

function AddActivityForm({
  orgs,
  staff,
  onAdded,
}: {
  orgs: Organization[]
  staff: Staff[]
  onAdded: () => void
}) {
  const [name, setName] = useState('')
  const [date, setDate] = useState(new Date().toISOString().slice(0, 10))
  const [time, setTime] = useState('09:00')
  const [type, setType] = useState<ActivityType>('Meeting')
  const [priority, setPriority] = useState<ActivityPriority>('Medium')
  const [orgId, setOrgId] = useState('')
  const [staffId, setStaffId] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const submit = async () => {
    if (!name.trim()) return
    setBusy(true)
    setError(null)
    try {
      const scheduled_at = new Date(`${date}T${time}:00`).toISOString()
      await createActivity({
        name: name.trim(),
        scheduled_at,
        type,
        priority,
        organization: orgId || null,
        assigned_staff: staffId || null,
      })
      setName('')
      onAdded()
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="catalog-card" style={{ padding: 12, marginBottom: 12 }}>
      <div className="add-row">
        <input
          className="input compact"
          style={{ flex: 1 }}
          placeholder="Activity name"
          value={name}
          onChange={(e) => setName(e.target.value)}
        />
        <input type="date" className="input compact" value={date} onChange={(e) => setDate(e.target.value)} />
        <input type="time" className="input compact" value={time} onChange={(e) => setTime(e.target.value)} />
      </div>
      <div className="add-row">
        <select className="input compact" value={type} onChange={(e) => setType(e.target.value as ActivityType)}>
          {TYPES.map((t) => (
            <option key={t} value={t}>
              {t}
            </option>
          ))}
        </select>
        <select
          className="input compact"
          value={priority}
          onChange={(e) => setPriority(e.target.value as ActivityPriority)}
        >
          {PRIORITIES.map((p) => (
            <option key={p} value={p}>
              {p}
            </option>
          ))}
        </select>
        <select className="input compact" value={orgId} onChange={(e) => setOrgId(e.target.value)}>
          <option value="">— Customer —</option>
          {orgs.map((o) => (
            <option key={o.id} value={o.id}>
              {o.display_name}
            </option>
          ))}
        </select>
        <select className="input compact" value={staffId} onChange={(e) => setStaffId(e.target.value)}>
          <option value="">— Assigned —</option>
          {staff.map((s) => (
            <option key={s.id} value={s.id}>
              {s.name}
            </option>
          ))}
        </select>
        <button className="btn btn-primary" disabled={busy || !name.trim()} onClick={submit}>
          Create
        </button>
        {error && <span className="error-text">{error}</span>}
      </div>
    </div>
  )
}
