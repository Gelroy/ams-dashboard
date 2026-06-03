import { useEffect, useState } from 'react'

import {
  abortPatchExecution,
  checkForNeededExecutions,
  createPatchExecution,
  createPatchGroup,
  createPatchGroupStep,
  createPatchPlan,
  createPatchPlanStep,
  deletePatchExecution,
  deletePatchGroup,
  deletePatchGroupStep,
  deletePatchPlan,
  deletePatchPlanStep,
  importGroupIntoPlan,
  listEnvironments,
  listOrganizations,
  listPatchExecutions,
  listPatchGroups,
  listPatchPlans,
  listSoftware,
  markStepDone,
  resetPatchExecution,
  setStepElapsed,
  updatePatchExecution,
  updatePatchGroup,
  updatePatchGroupStep,
  updatePatchPlan,
  updatePatchPlanStep,
} from '../api'
import type {
  Organization,
  PatchExecution,
  PatchExecutionCheckResult,
  PatchExecutionStep,
  PatchGroup,
  PatchGroupStep,
  PatchPlan,
  PatchPlanStep,
  Software,
} from '../types'

// Executions tab is now first — it's the day-to-day surface for the team.
// Groups/Plans are configuration.
type Tab = 'executions' | 'groups' | 'plans'

export function PatchExecutionPage() {
  const [tab, setTab] = useState<Tab>('executions')

  return (
    <div>
      <div className="panel-header-row">
        <span className="panel-title">Patch Execution</span>
      </div>
      <div className="tabs">
        <TabBtn active={tab === 'executions'} onClick={() => setTab('executions')}>Executions</TabBtn>
        <TabBtn active={tab === 'groups'} onClick={() => setTab('groups')}>Groups</TabBtn>
        <TabBtn active={tab === 'plans'} onClick={() => setTab('plans')}>Plans</TabBtn>
      </div>

      {tab === 'executions' && <ExecutionsTab />}
      {tab === 'groups' && <GroupsTab />}
      {tab === 'plans' && <PlansTab />}
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
   Executions (first tab — daily work surface)
   ════════════════════════════════════════════════════════════════════════════ */

function ExecutionsTab() {
  const [executions, setExecutions] = useState<PatchExecution[]>([])
  const [orgs, setOrgs] = useState<Organization[]>([])
  const [plans, setPlans] = useState<PatchPlan[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [showAdd, setShowAdd] = useState(false)
  // Result banner for the manual "Check for Needed" run. Auto-clears when
  // the user dismisses or hits Check again.
  const [checkResults, setCheckResults] = useState<PatchExecutionCheckResult[] | null>(null)
  const [checking, setChecking] = useState(false)

  const refresh = () => {
    setLoading(true)
    setError(null)
    Promise.all([
      listPatchExecutions('active'),
      listOrganizations({ limit: 200, has_ams_level: true }),
      listPatchPlans(),
    ])
      .then(([ex, orgsRes, p]) => {
        setExecutions(ex)
        setOrgs(orgsRes.results)
        setPlans(p)
      })
      .catch((e: Error) => setError(e.message))
      .finally(() => setLoading(false))
  }
  useEffect(refresh, [])

  const runCheck = async () => {
    setChecking(true)
    setError(null)
    try {
      const { results } = await checkForNeededExecutions()
      setCheckResults(results)
      refresh()
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setChecking(false)
    }
  }

  return (
    <div>
      {error && <div className="error-banner">{error}</div>}

      <div className="add-row">
        <button className="btn btn-primary" onClick={runCheck} disabled={checking}>
          {checking ? 'Checking…' : 'Check for Needed Patch Executions'}
        </button>
        <button className="btn" onClick={() => setShowAdd(!showAdd)}>
          {showAdd ? 'Cancel' : '+ Add Execution'}
        </button>
      </div>

      {checkResults !== null && (
        <CheckResultsBanner
          results={checkResults}
          onClose={() => setCheckResults(null)}
        />
      )}

      {showAdd && (
        <AddExecutionForm
          orgs={orgs}
          plans={plans}
          onAdded={() => {
            setShowAdd(false)
            refresh()
          }}
        />
      )}

      {loading && <div className="state-cell">Loading…</div>}
      {!loading && executions.length === 0 && (
        <div className="state-cell">No active executions.</div>
      )}

      {executions.map((ex) => (
        <ExecutionCard key={ex.id} execution={ex} onChanged={refresh} />
      ))}
    </div>
  )
}

function CheckResultsBanner({
  results,
  onClose,
}: {
  results: PatchExecutionCheckResult[]
  onClose: () => void
}) {
  const created = results.filter((r) => r.created)
  const skipped = results.filter((r) => !r.created)
  return (
    <div
      className="catalog-card"
      style={{ background: '#f0f9ff', borderColor: '#bae6fd', padding: 12, marginBottom: 12 }}
    >
      <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 6 }}>
        <strong>
          {created.length} execution{created.length === 1 ? '' : 's'} created
          {skipped.length > 0 && ` · ${skipped.length} skipped`}
        </strong>
        <button className="btn-icon" onClick={onClose} title="Dismiss">×</button>
      </div>
      {created.length === 0 && skipped.length === 0 && (
        <div className="meta">Nothing to do — every AMS customer is at Latest for every covered software.</div>
      )}
      {created.map((r, i) => (
        <div key={`c${i}`} className="meta" style={{ padding: '2px 0' }}>
          ✓ {r.org_name} — {r.env_name} — {r.plan_name}
        </div>
      ))}
      {skipped.map((r, i) => (
        <div key={`s${i}`} className="meta" style={{ padding: '2px 0', color: '#a16207' }}>
          ⨯ {r.org_name} — {r.env_name} — {r.plan_name} ({r.reason})
        </div>
      ))}
    </div>
  )
}

function AddExecutionForm({
  orgs,
  plans,
  onAdded,
}: {
  orgs: Organization[]
  plans: PatchPlan[]
  onAdded: () => void
}) {
  const [orgId, setOrgId] = useState('')
  const [envId, setEnvId] = useState('')
  const [planId, setPlanId] = useState('')
  const [plannedDate, setPlannedDate] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [orgEnvs, setOrgEnvs] = useState<{ id: string; name: string }[]>([])

  useEffect(() => {
    if (!orgId) {
      setOrgEnvs([])
      return
    }
    listEnvironments(orgId)
      .then(setOrgEnvs)
      .catch(() => setOrgEnvs([]))
  }, [orgId])

  const submit = async () => {
    if (!orgId || !envId || !planId) return
    setBusy(true)
    setError(null)
    try {
      await createPatchExecution({
        organization: orgId,
        environment: envId,
        patch_plan: planId,
        planned_date: plannedDate || null,
      })
      onAdded()
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="catalog-card" style={{ padding: 12 }}>
      <div className="add-row">
        <select
          className="input compact"
          value={orgId}
          onChange={(e) => {
            setOrgId(e.target.value)
            setEnvId('')
          }}
        >
          <option value="">— Customer —</option>
          {orgs.map((o) => (
            <option key={o.id} value={o.id}>
              {o.display_name}
            </option>
          ))}
        </select>
        <select
          className="input compact"
          value={envId}
          disabled={!orgId}
          onChange={(e) => setEnvId(e.target.value)}
        >
          <option value="">— Env —</option>
          {orgEnvs.map((e) => (
            <option key={e.id} value={e.id}>
              {e.name}
            </option>
          ))}
        </select>
        <select
          className="input compact"
          value={planId}
          onChange={(e) => setPlanId(e.target.value)}
        >
          <option value="">— Plan —</option>
          {plans.map((p) => (
            <option key={p.id} value={p.id}>
              {p.name}
            </option>
          ))}
        </select>
        <input
          className="input compact"
          type="date"
          value={plannedDate}
          onChange={(e) => setPlannedDate(e.target.value)}
          title="Planned date (optional)"
          aria-label="Planned date"
        />
        <button
          className="btn btn-primary"
          disabled={busy || !orgId || !envId || !planId}
          onClick={submit}
        >
          Create
        </button>
        {error && <span className="error-text">{error}</span>}
      </div>
    </div>
  )
}

function ExecutionCard({
  execution,
  onChanged,
}: {
  execution: PatchExecution
  onChanged: () => void
}) {
  const [open, setOpen] = useState(false)
  const [aborting, setAborting] = useState(false)
  const [abortNotes, setAbortNotes] = useState('')
  const [plannedDate, setPlannedDate] = useState(execution.planned_date ?? '')
  const [editingPlanned, setEditingPlanned] = useState(false)
  const [savingPlanned, setSavingPlanned] = useState(false)
  const [plannedError, setPlannedError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [actionError, setActionError] = useState<string | null>(null)

  useEffect(() => {
    setPlannedDate(execution.planned_date ?? '')
  }, [execution.planned_date])

  const doReset = () => {
    if (!window.confirm('Reset this execution? All step progress will be cleared and it returns to Active.')) return
    setBusy(true)
    setActionError(null)
    resetPatchExecution(execution.id)
      .then(() => onChanged())
      .catch((e: Error) => setActionError(e.message))
      .finally(() => setBusy(false))
  }

  const doDelete = () => {
    if (!window.confirm('Delete this execution permanently? This cannot be undone.')) return
    setBusy(true)
    setActionError(null)
    deletePatchExecution(execution.id)
      .then(() => onChanged())
      .catch((e: Error) => setActionError(e.message))
      .finally(() => setBusy(false))
  }

  const saveStepElapsed = (stepId: string, value: string, current: string | null) => {
    const next = value.trim() || null
    if (next === (current ?? null)) return
    setStepElapsed(execution.id, stepId, next)
      .then(() => onChanged())
      .catch((e: Error) => setActionError(e.message))
  }

  const doneCount = execution.steps.filter((s) => s.done).length
  const total = execution.steps.length
  const started = !!execution.started_at

  const submitStep = (stepId: string) => markStepDone(execution.id, stepId).then(onChanged)

  const submitAbort = async () => {
    if (!abortNotes.trim()) return
    await abortPatchExecution(execution.id, abortNotes.trim())
    setAborting(false)
    setAbortNotes('')
    onChanged()
  }

  const savePlanned = (next: string) => {
    const normalized = next || null
    if (normalized === (execution.planned_date ?? null)) return
    setSavingPlanned(true)
    setPlannedError(null)
    updatePatchExecution(execution.id, { planned_date: normalized })
      .then(() => onChanged())
      .catch((e: Error) => {
        setPlannedError(e.message)
        setPlannedDate(execution.planned_date ?? '')
      })
      .finally(() => setSavingPlanned(false))
  }

  return (
    <div className="catalog-card">
      <div className="catalog-row">
        <button className="chevron-btn" onClick={() => setOpen(!open)}>
          {open ? '▼' : '▶'}
        </button>
        <strong>
          {execution.organization_name} — {execution.environment_name}
        </strong>
        <span className="meta">
          {execution.plan_name ?? 'no plan'} · {doneCount}/{total} steps
        </span>
        {editingPlanned ? (
          <input
            className="input compact"
            type="date"
            autoFocus
            value={plannedDate}
            disabled={savingPlanned}
            onChange={(e) => setPlannedDate(e.target.value)}
            onBlur={(e) => {
              savePlanned(e.target.value)
              setEditingPlanned(false)
            }}
            onClick={(e) => e.stopPropagation()}
            style={{ marginLeft: 'auto' }}
          />
        ) : (
          <span
            className="meta"
            style={{ marginLeft: 'auto', cursor: 'pointer' }}
            title="Planned date — click to edit"
            onClick={(e) => {
              e.stopPropagation()
              setEditingPlanned(true)
            }}
          >
            {execution.planned_date ? formatPlannedDate(execution.planned_date) : 'TBD'}
          </span>
        )}
        <span className="badge patch-yes">Active</span>
      </div>

      {open && (
        <div className="catalog-children">
          {execution.software_names.length > 0 && (
            <div className="meta" style={{ marginBottom: 8 }}>
              Covers: {execution.software_names.join(', ')}
            </div>
          )}
          {started && (
            <div className="meta" style={{ marginBottom: 8 }}>
              Started {new Date(execution.started_at!).toLocaleString()}
            </div>
          )}

          {plannedError && <div className="error-banner">{plannedError}</div>}
          {actionError && <div className="error-banner">{actionError}</div>}

          <div className="add-row" style={{ marginBottom: 8 }}>
            <button className="btn" disabled={busy} onClick={doReset}>
              Reset
            </button>
            <button
              className="btn"
              style={{ color: '#b91c1c' }}
              disabled={busy}
              onClick={doDelete}
            >
              Delete
            </button>
            {busy && <span className="meta">working…</span>}
          </div>

          {aborting ? (
            <div className="catalog-card" style={{ padding: 10, marginBottom: 10, background: '#fef6f6' }}>
              <div className="field-label">Abort reason (required)</div>
              <textarea
                className="input textarea"
                rows={3}
                value={abortNotes}
                onChange={(e) => setAbortNotes(e.target.value)}
              />
              <div className="add-row">
                <button className="btn btn-primary" onClick={submitAbort} disabled={!abortNotes.trim()}>
                  Confirm Abort
                </button>
                <button className="btn" onClick={() => setAborting(false)}>
                  Cancel
                </button>
              </div>
            </div>
          ) : started && (
            <button
              className="btn"
              style={{ marginBottom: 8, color: '#b91c1c' }}
              onClick={() => setAborting(true)}
            >
              Abort
            </button>
          )}

          {execution.aborts.length > 0 && (
            <div style={{ marginBottom: 8 }}>
              <div className="field-label">Previous attempts ({execution.aborts.length})</div>
              {execution.aborts.map((a) => (
                <div key={a.id} className="meta" style={{ padding: '4px 0' }}>
                  Attempt {a.attempt_num} · {a.attempt_date} · elapsed {a.elapsed} ·{' '}
                  {a.steps_completed}/{a.total_steps} steps · {a.notes}
                </div>
              ))}
            </div>
          )}

          {total === 0 ? (
            <div className="state-cell">
              No steps. Link a Plan with steps to define what to run.
            </div>
          ) : (
            <ExecutionStepTable
              execution={execution}
              onDone={submitStep}
              onSaveElapsed={saveStepElapsed}
            />
          )}
        </div>
      )}
    </div>
  )
}

function ExecutionStepTable({
  execution,
  onDone,
  onSaveElapsed,
}: {
  execution: PatchExecution
  onDone: (id: string) => Promise<void>
  onSaveElapsed: (id: string, value: string, current: string | null) => void
}) {
  return (
    <table className="data-table">
      <thead>
        <tr>
          <th style={{ width: 36 }}>#</th>
          <th>Description</th>
          <th style={{ width: 70 }}>Est.</th>
          <th style={{ width: 110 }}>Action</th>
          <th style={{ width: 100 }}>Elapsed</th>
        </tr>
      </thead>
      <tbody>
        {execution.steps.map((s, i) => (
          <ExecutionStepRow
            key={s.id}
            step={s}
            // not_timed steps don't gate on prior-step completion; for timed
            // steps the prior TIMED step (or the very first step) must be done.
            isUnlocked={
              s.not_timed ||
              i === 0 ||
              prevTimedStepDone(execution.steps, i)
            }
            onDone={onDone}
            onSaveElapsed={onSaveElapsed}
          />
        ))}
      </tbody>
    </table>
  )
}

/** True if the most-recent TIMED step before index `i` is done. Skips over
 * not_timed steps when walking backward — those can be done at any time and
 * shouldn't gate timed work. */
function prevTimedStepDone(steps: PatchExecutionStep[], i: number): boolean {
  for (let j = i - 1; j >= 0; j--) {
    if (steps[j].not_timed) continue
    return steps[j].done
  }
  return true // no prior timed step → unlocked
}

function ExecutionStepRow({
  step,
  isUnlocked,
  onDone,
  onSaveElapsed,
}: {
  step: PatchExecutionStep
  isUnlocked: boolean
  onDone: (id: string) => Promise<void>
  onSaveElapsed: (id: string, value: string, current: string | null) => void
}) {
  let action: React.ReactNode = null
  if (step.done) {
    action = <span style={{ color: '#047857' }}>✓ Done</span>
  } else if (isUnlocked) {
    action = (
      <button
        className="btn btn-primary"
        style={{ padding: '2px 10px', fontSize: 11 }}
        onClick={() => onDone(step.id)}
      >
        Done
      </button>
    )
  } else {
    action = <span className="meta">waiting</span>
  }

  return (
    <tr style={{ opacity: step.done ? 0.5 : 1 }}>
      <td>{step.step_num}</td>
      <td>
        {step.description}
        {step.not_timed && (
          <span className="meta" style={{ marginLeft: 6 }} title="Not timed — done at any time, no elapsed accumulation">
            (not timed)
          </span>
        )}
      </td>
      <td>{step.est_time ?? '—'}</td>
      <td>{action}</td>
      <td>
        {step.not_timed ? (
          <span className="meta">—</span>
        ) : (
          <input
            key={`${step.id}-${step.total_time ?? ''}`}
            className="input compact"
            style={{ width: 90 }}
            defaultValue={step.total_time ?? ''}
            placeholder="—"
            onBlur={(e) => onSaveElapsed(step.id, e.target.value, step.total_time)}
          />
        )}
      </td>
    </tr>
  )
}

function formatPlannedDate(iso: string): string {
  const d = new Date(iso + 'T00:00:00')
  return d.toLocaleDateString(undefined, { year: 'numeric', month: 'short', day: 'numeric' })
}

/* ════════════════════════════════════════════════════════════════════════════
   Groups (templates — softwares M2M + steps with not_timed)
   ════════════════════════════════════════════════════════════════════════════ */

function GroupsTab() {
  const [groups, setGroups] = useState<PatchGroup[]>([])
  const [catalog, setCatalog] = useState<Software[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const refresh = () => {
    setLoading(true)
    setError(null)
    Promise.all([listPatchGroups(), listSoftware()])
      .then(([g, c]) => {
        setGroups(g)
        setCatalog(c)
      })
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
          No patch groups yet. Groups are reusable runbook fragments. Add one to
          start; later you'll import its steps into a Plan.
        </div>
      )}
      {groups.map((g) => (
        <PatchGroupCard key={g.id} group={g} catalog={catalog} onChanged={refresh} />
      ))}
      <AddPatchGroupForm onAdded={refresh} />
    </div>
  )
}

function PatchGroupCard({
  group,
  catalog,
  onChanged,
}: {
  group: PatchGroup
  catalog: Software[]
  onChanged: () => void
}) {
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
          {group.software_names.length} sw · {group.steps.length} step{group.steps.length === 1 ? '' : 's'}
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
          <SoftwarePicker
            label="Related Software"
            selected={group.software_ids}
            catalog={catalog}
            onChange={(ids) => updatePatchGroup(group.id, { software_ids: ids }).then(onChanged)}
          />

          <div className="field-label" style={{ marginTop: 12, marginBottom: 4 }}>
            Steps
          </div>
          <table className="data-table" style={{ marginBottom: 8 }}>
            <thead>
              <tr>
                <th style={{ width: 36 }}>#</th>
                <th>Description</th>
                <th style={{ width: 80 }}>Est.</th>
                <th style={{ width: 80, textAlign: 'center' }}>Per Server</th>
                <th style={{ width: 80, textAlign: 'center' }}>NOT Timed</th>
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
  const [stepNum, setStepNum] = useState(String(step.step_num))

  return (
    <tr>
      <td>
        <input
          className="input compact"
          style={{ width: 40 }}
          value={stepNum}
          onChange={(e) => setStepNum(e.target.value)}
          onBlur={() => {
            const n = parseInt(stepNum, 10)
            if (!Number.isFinite(n) || n === step.step_num) {
              setStepNum(String(step.step_num))
              return
            }
            updatePatchGroupStep(groupId, step.id, { step_num: n }).then(onChanged)
          }}
        />
      </td>
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
            updatePatchGroupStep(groupId, step.id, { per_server: e.target.checked }).then(onChanged)
          }
        />
      </td>
      <td style={{ textAlign: 'center' }}>
        <input
          type="checkbox"
          checked={step.not_timed}
          onChange={(e) =>
            updatePatchGroupStep(groupId, step.id, { not_timed: e.target.checked }).then(onChanged)
          }
          title="Step doesn't accumulate run time and can be marked Done at any moment"
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
   Plans (software M2M + plan-owned steps + import-group action)
   ════════════════════════════════════════════════════════════════════════════ */

function PlansTab() {
  const [plans, setPlans] = useState<PatchPlan[]>([])
  const [groups, setGroups] = useState<PatchGroup[]>([])
  const [catalog, setCatalog] = useState<Software[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const refresh = () => {
    setLoading(true)
    setError(null)
    Promise.all([listPatchPlans(), listPatchGroups(), listSoftware()])
      .then(([p, g, c]) => {
        setPlans(p)
        setGroups(g)
        setCatalog(c)
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
          No patch plans yet. A Plan covers one or more Softwares and contains
          its own ordered steps (typically imported from Groups). The Check
          button on the Executions tab queues a PatchExecution per (env, plan).
        </div>
      )}
      {plans.map((p) => (
        <PatchPlanCard key={p.id} plan={p} groups={groups} catalog={catalog} onChanged={refresh} />
      ))}
      <AddPatchPlanForm onAdded={refresh} />
    </div>
  )
}

function PatchPlanCard({
  plan,
  groups,
  catalog,
  onChanged,
}: {
  plan: PatchPlan
  groups: PatchGroup[]
  catalog: Software[]
  onChanged: () => void
}) {
  const [open, setOpen] = useState(false)
  const [name, setName] = useState(plan.name)

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
          {plan.software_names.length} sw · {plan.plan_steps.length} step{plan.plan_steps.length === 1 ? '' : 's'}
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
          <SoftwarePicker
            label="Softwares Covered"
            selected={plan.software_ids}
            catalog={catalog}
            onChange={(ids) => updatePatchPlan(plan.id, { software_ids: ids }).then(onChanged)}
          />

          <div className="field-label" style={{ marginTop: 12, marginBottom: 4 }}>
            Steps
          </div>
          {plan.plan_steps.length === 0 && (
            <div className="state-cell" style={{ marginBottom: 8 }}>
              No steps. Import a Group or add steps individually.
            </div>
          )}
          {plan.plan_steps.length > 0 && (
            <table className="data-table" style={{ marginBottom: 8 }}>
              <thead>
                <tr>
                  <th style={{ width: 36 }}>#</th>
                  <th>Description</th>
                  <th style={{ width: 80 }}>Est.</th>
                  <th style={{ width: 80, textAlign: 'center' }}>Per Server</th>
                  <th style={{ width: 80, textAlign: 'center' }}>NOT Timed</th>
                  <th style={{ width: 36 }}></th>
                </tr>
              </thead>
              <tbody>
                {plan.plan_steps.map((s) => (
                  <PatchPlanStepRow
                    key={s.id}
                    planId={plan.id}
                    step={s}
                    onChanged={onChanged}
                  />
                ))}
              </tbody>
            </table>
          )}

          <div className="add-row" style={{ flexWrap: 'wrap', gap: 8 }}>
            <AddPatchPlanStepForm
              planId={plan.id}
              nextStepNum={
                (plan.plan_steps.length > 0
                  ? Math.max(...plan.plan_steps.map((s) => s.step_num))
                  : 0) + 1
              }
              onAdded={onChanged}
            />
            {groups.length > 0 && (
              <select
                className="input compact"
                defaultValue=""
                onChange={(e) => {
                  const gid = e.target.value
                  if (!gid) return
                  importGroupIntoPlan(plan.id, gid)
                    .then(onChanged)
                    .catch((err: Error) => alert(err.message))
                  e.target.value = ''
                }}
                title="Importing copies the group's steps to the end of this plan's step list and unions the group's softwares. The group is forgotten afterwards — edit freely."
              >
                <option value="">+ Import from Group…</option>
                {groups.map((g) => (
                  <option key={g.id} value={g.id}>
                    {g.name} ({g.steps.length} steps)
                  </option>
                ))}
              </select>
            )}
          </div>
        </div>
      )}
    </div>
  )
}

function PatchPlanStepRow({
  planId,
  step,
  onChanged,
}: {
  planId: string
  step: PatchPlanStep
  onChanged: () => void
}) {
  const [desc, setDesc] = useState(step.description)
  const [est, setEst] = useState(step.est_time ?? '')
  const [stepNum, setStepNum] = useState(String(step.step_num))

  return (
    <tr>
      <td>
        <input
          className="input compact"
          style={{ width: 40 }}
          value={stepNum}
          onChange={(e) => setStepNum(e.target.value)}
          onBlur={() => {
            const n = parseInt(stepNum, 10)
            if (!Number.isFinite(n) || n === step.step_num) {
              setStepNum(String(step.step_num))
              return
            }
            updatePatchPlanStep(planId, step.id, { step_num: n }).then(onChanged)
          }}
        />
      </td>
      <td>
        <input
          className="input compact"
          style={{ width: '100%' }}
          value={desc}
          onChange={(e) => setDesc(e.target.value)}
          onBlur={() => {
            if (desc !== step.description)
              updatePatchPlanStep(planId, step.id, { description: desc }).then(onChanged)
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
              updatePatchPlanStep(planId, step.id, { est_time: est || null }).then(onChanged)
          }}
        />
      </td>
      <td style={{ textAlign: 'center' }}>
        <input
          type="checkbox"
          checked={step.per_server}
          onChange={(e) =>
            updatePatchPlanStep(planId, step.id, { per_server: e.target.checked }).then(onChanged)
          }
        />
      </td>
      <td style={{ textAlign: 'center' }}>
        <input
          type="checkbox"
          checked={step.not_timed}
          onChange={(e) =>
            updatePatchPlanStep(planId, step.id, { not_timed: e.target.checked }).then(onChanged)
          }
          title="Step doesn't accumulate run time and can be marked Done at any moment"
        />
      </td>
      <td>
        <button
          className="btn-icon"
          onClick={() => {
            if (window.confirm('Delete this step?'))
              deletePatchPlanStep(planId, step.id).then(onChanged)
          }}
        >
          ×
        </button>
      </td>
    </tr>
  )
}

function AddPatchPlanStepForm({
  planId,
  nextStepNum,
  onAdded,
}: {
  planId: string
  nextStepNum: number
  onAdded: () => void
}) {
  const [desc, setDesc] = useState('')
  const [busy, setBusy] = useState(false)

  const submit = async () => {
    if (!desc.trim()) return
    setBusy(true)
    try {
      await createPatchPlanStep(planId, {
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
    <>
      <input
        className="input compact"
        style={{ flex: 1, minWidth: 220 }}
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
    </>
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

/* ════════════════════════════════════════════════════════════════════════════
   Shared bits
   ════════════════════════════════════════════════════════════════════════════ */

/** Multi-select for Software via toggleable chips. Kept simple — the catalog
 *  is small enough that we just render every Software as an on/off chip. */
function SoftwarePicker({
  label,
  selected,
  catalog,
  onChange,
}: {
  label: string
  selected: string[]
  catalog: Software[]
  onChange: (ids: string[]) => void
}) {
  const selectedSet = new Set(selected)
  const toggle = (id: string) => {
    const next = new Set(selectedSet)
    if (next.has(id)) next.delete(id)
    else next.add(id)
    onChange([...next])
  }
  return (
    <div className="sub-section">
      <div className="field-label">{label}</div>
      <div className="env-chips">
        {catalog.length === 0 && (
          <span className="meta">No software in the catalog yet.</span>
        )}
        {catalog.map((s) => {
          const on = selectedSet.has(s.id)
          return (
            <button
              key={s.id}
              type="button"
              className={on ? 'env-chip env-chip-on' : 'env-chip env-chip-off'}
              onClick={() => toggle(s.id)}
            >
              {on ? '✓ ' : ''}
              {s.name} {s.version}
            </button>
          )
        })}
      </div>
    </div>
  )
}
