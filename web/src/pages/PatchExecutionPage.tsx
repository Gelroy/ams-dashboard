import { useEffect, useState } from 'react'

import {
  addPatchPlanGroup,
  createPatchGroup,
  createPatchGroupStep,
  createPatchPlan,
  deletePatchGroup,
  deletePatchGroupStep,
  deletePatchPlan,
  listBaskets,
  listPatchGroups,
  listPatchPlans,
  removePatchPlanGroup,
  updatePatchGroup,
  updatePatchGroupStep,
  updatePatchPlan,
} from '../api'
import type { Basket, PatchGroup, PatchGroupStep, PatchPlan } from '../types'

type Tab = 'groups' | 'plans' | 'executions'

export function PatchExecutionPage() {
  const [tab, setTab] = useState<Tab>('groups')

  return (
    <div>
      <div className="panel-header-row">
        <span className="panel-title">Patch Execution</span>
      </div>
      <div className="tabs">
        <TabBtn active={tab === 'groups'} onClick={() => setTab('groups')}>Groups</TabBtn>
        <TabBtn active={tab === 'plans'} onClick={() => setTab('plans')}>Plans</TabBtn>
        <TabBtn active={tab === 'executions'} onClick={() => setTab('executions')}>Executions</TabBtn>
      </div>

      {tab === 'groups' && <GroupsTab />}
      {tab === 'plans' && <PlansTab />}
      {tab === 'executions' && (
        <div className="state-cell">
          Executions UI lands in the next slice — Plans + Groups defined here are
          the inputs.
        </div>
      )}
    </div>
  )
}

function TabBtn({
  active,
  onClick,
  children,
}: {
  active: boolean
  onClick: () => void
  children: React.ReactNode
}) {
  return (
    <button className={active ? 'tab tab-active' : 'tab'} onClick={onClick}>
      {children}
    </button>
  )
}

/* ════════════════════════════════════════════════════════════════════════════
   Groups
   ════════════════════════════════════════════════════════════════════════════ */

function GroupsTab() {
  const [groups, setGroups] = useState<PatchGroup[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const refresh = () => {
    setLoading(true)
    setError(null)
    listPatchGroups()
      .then(setGroups)
      .catch((e: Error) => setError(e.message))
      .finally(() => setLoading(false))
  }
  useEffect(refresh, [])

  return (
    <div>
      {error && <div className="error-banner">{error}</div>}
      {loading && <div className="state-cell">Loading…</div>}
      {!loading && groups.length === 0 && (
        <div className="state-cell">
          No patch groups yet. Groups are reusable runbook fragments that Plans
          assemble in order.
        </div>
      )}
      {groups.map((g) => (
        <PatchGroupCard key={g.id} group={g} onChanged={refresh} />
      ))}
      <AddPatchGroupForm onAdded={refresh} />
    </div>
  )
}

function PatchGroupCard({ group, onChanged }: { group: PatchGroup; onChanged: () => void }) {
  const [open, setOpen] = useState(false)
  const [name, setName] = useState(group.name)

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
            if (name !== group.name) updatePatchGroup(group.id, { name }).then(onChanged)
          }}
        />
        <span className="meta">
          {group.steps.length} step{group.steps.length === 1 ? '' : 's'}
        </span>
        <button
          className="btn-icon"
          onClick={() => {
            if (window.confirm(`Delete group ${group.name}?`))
              deletePatchGroup(group.id).then(onChanged)
          }}
        >
          ×
        </button>
      </div>

      {open && (
        <div className="catalog-children">
          <table className="data-table" style={{ marginBottom: 8 }}>
            <thead>
              <tr>
                <th style={{ width: 36 }}>#</th>
                <th>Description</th>
                <th style={{ width: 80 }}>Est.</th>
                <th style={{ width: 80, textAlign: 'center' }}>Per Server</th>
                <th style={{ width: 36 }}></th>
              </tr>
            </thead>
            <tbody>
              {group.steps.map((s) => (
                <PatchGroupStepRow
                  key={s.id}
                  groupId={group.id}
                  step={s}
                  onChanged={onChanged}
                />
              ))}
            </tbody>
          </table>
          <AddPatchGroupStepForm
            groupId={group.id}
            nextStepNum={group.steps.length + 1}
            onAdded={onChanged}
          />
        </div>
      )}
    </div>
  )
}

function PatchGroupStepRow({
  groupId,
  step,
  onChanged,
}: {
  groupId: string
  step: PatchGroupStep
  onChanged: () => void
}) {
  const [desc, setDesc] = useState(step.description)
  const [est, setEst] = useState(step.est_time ?? '')

  return (
    <tr>
      <td>{step.step_num}</td>
      <td>
        <input
          className="input compact"
          style={{ width: '100%' }}
          value={desc}
          onChange={(e) => setDesc(e.target.value)}
          onBlur={() => {
            if (desc !== step.description)
              updatePatchGroupStep(groupId, step.id, { description: desc }).then(onChanged)
          }}
        />
      </td>
      <td>
        <input
          className="input compact"
          style={{ width: 70 }}
          placeholder="15m"
          value={est}
          onChange={(e) => setEst(e.target.value)}
          onBlur={() => {
            if (est !== (step.est_time ?? ''))
              updatePatchGroupStep(groupId, step.id, { est_time: est || null }).then(onChanged)
          }}
        />
      </td>
      <td style={{ textAlign: 'center' }}>
        <input
          type="checkbox"
          checked={step.per_server}
          onChange={(e) =>
            updatePatchGroupStep(groupId, step.id, { per_server: e.target.checked }).then(
              onChanged,
            )
          }
        />
      </td>
      <td>
        <button
          className="btn-icon"
          onClick={() => {
            if (window.confirm('Delete this step?'))
              deletePatchGroupStep(groupId, step.id).then(onChanged)
          }}
        >
          ×
        </button>
      </td>
    </tr>
  )
}

function AddPatchGroupForm({ onAdded }: { onAdded: () => void }) {
  const [name, setName] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const submit = async () => {
    if (!name.trim()) return
    setBusy(true)
    setError(null)
    try {
      await createPatchGroup(name.trim())
      setName('')
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
        placeholder="New group name"
        value={name}
        onChange={(e) => setName(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === 'Enter') submit()
        }}
      />
      <button className="btn" disabled={busy || !name.trim()} onClick={submit}>
        + Add Group
      </button>
      {error && <span className="error-text">{error}</span>}
    </div>
  )
}

function AddPatchGroupStepForm({
  groupId,
  nextStepNum,
  onAdded,
}: {
  groupId: string
  nextStepNum: number
  onAdded: () => void
}) {
  const [desc, setDesc] = useState('')
  const [busy, setBusy] = useState(false)

  const submit = async () => {
    if (!desc.trim()) return
    setBusy(true)
    try {
      await createPatchGroupStep(groupId, {
        step_num: nextStepNum,
        description: desc.trim(),
      })
      setDesc('')
      onAdded()
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="add-row">
      <input
        className="input compact"
        style={{ flex: 1 }}
        placeholder="Step description"
        value={desc}
        onChange={(e) => setDesc(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === 'Enter') submit()
        }}
      />
      <button className="btn" disabled={busy || !desc.trim()} onClick={submit}>
        + Add Step
      </button>
    </div>
  )
}

/* ════════════════════════════════════════════════════════════════════════════
   Plans
   ════════════════════════════════════════════════════════════════════════════ */

function PlansTab() {
  const [plans, setPlans] = useState<PatchPlan[]>([])
  const [groups, setGroups] = useState<PatchGroup[]>([])
  const [baskets, setBaskets] = useState<Basket[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const refresh = () => {
    setLoading(true)
    setError(null)
    Promise.all([listPatchPlans(), listPatchGroups(), listBaskets()])
      .then(([p, g, b]) => {
        setPlans(p)
        setGroups(g)
        setBaskets(b)
      })
      .catch((e: Error) => setError(e.message))
      .finally(() => setLoading(false))
  }
  useEffect(refresh, [])

  return (
    <div>
      {error && <div className="error-banner">{error}</div>}
      {loading && <div className="state-cell">Loading…</div>}
      {!loading && plans.length === 0 && (
        <div className="state-cell">
          No patch plans yet. A plan picks a Basket and orders one or more
          Groups to execute against servers running that Basket.
        </div>
      )}
      {plans.map((p) => (
        <PatchPlanCard key={p.id} plan={p} groups={groups} baskets={baskets} onChanged={refresh} />
      ))}
      <AddPatchPlanForm onAdded={refresh} />
    </div>
  )
}

function PatchPlanCard({
  plan,
  groups,
  baskets,
  onChanged,
}: {
  plan: PatchPlan
  groups: PatchGroup[]
  baskets: Basket[]
  onChanged: () => void
}) {
  const [open, setOpen] = useState(false)
  const [name, setName] = useState(plan.name)
  const totalSteps = plan.plan_groups.reduce((sum, pg) => sum + pg.step_count, 0)
  const assignedGroupIds = new Set(plan.plan_groups.map((pg) => pg.patch_group))
  const available = groups.filter((g) => !assignedGroupIds.has(g.id))

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
            if (name !== plan.name) updatePatchPlan(plan.id, { name }).then(onChanged)
          }}
        />
        <span className="meta">
          {plan.basket_name ?? 'no basket'} · {totalSteps} step{totalSteps === 1 ? '' : 's'}
        </span>
        <button
          className="btn-icon"
          onClick={() => {
            if (window.confirm(`Delete plan ${plan.name}?`))
              deletePatchPlan(plan.id).then(onChanged)
          }}
        >
          ×
        </button>
      </div>

      {open && (
        <div className="catalog-children">
          <div className="field" style={{ marginBottom: 12 }}>
            <div className="field-label">Basket</div>
            <select
              className="input compact"
              value={plan.basket ?? ''}
              onChange={(e) =>
                updatePatchPlan(plan.id, { basket: e.target.value || null }).then(onChanged)
              }
            >
              <option value="">— none —</option>
              {baskets.map((b) => (
                <option key={b.id} value={b.id}>
                  {b.name}
                </option>
              ))}
            </select>
          </div>

          <div className="field-label" style={{ marginBottom: 4 }}>
            Groups (in order)
          </div>
          {plan.plan_groups.length === 0 && (
            <div className="state-cell">No groups assigned yet.</div>
          )}
          {plan.plan_groups.map((pg) => (
            <div key={pg.patch_group} className="release-row">
              <span style={{ width: 24 }}>{pg.position + 1}.</span>
              <strong>{pg.group_name}</strong>
              <span className="meta">
                {pg.step_count} step{pg.step_count === 1 ? '' : 's'}
              </span>
              <button
                className="btn-icon"
                onClick={() => removePatchPlanGroup(plan.id, pg.patch_group).then(onChanged)}
              >
                ×
              </button>
            </div>
          ))}

          {available.length > 0 && (
            <div className="add-row">
              <select
                className="input compact"
                defaultValue=""
                onChange={(e) => {
                  const gid = e.target.value
                  if (!gid) return
                  addPatchPlanGroup(plan.id, {
                    patch_group: gid,
                    position: plan.plan_groups.length,
                  }).then(onChanged)
                  e.target.value = ''
                }}
              >
                <option value="">+ Add Group…</option>
                {available.map((g) => (
                  <option key={g.id} value={g.id}>
                    {g.name}
                  </option>
                ))}
              </select>
            </div>
          )}
        </div>
      )}
    </div>
  )
}

function AddPatchPlanForm({ onAdded }: { onAdded: () => void }) {
  const [name, setName] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const submit = async () => {
    if (!name.trim()) return
    setBusy(true)
    setError(null)
    try {
      await createPatchPlan(name.trim())
      setName('')
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
        placeholder="New plan name"
        value={name}
        onChange={(e) => setName(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === 'Enter') submit()
        }}
      />
      <button className="btn" disabled={busy || !name.trim()} onClick={submit}>
        + Add Plan
      </button>
      {error && <span className="error-text">{error}</span>}
    </div>
  )
}
