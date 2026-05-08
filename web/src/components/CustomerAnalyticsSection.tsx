import { useEffect, useState } from 'react'

import {
  createCustomerAnalytic,
  deleteAnalyticHistory,
  deleteCustomerAnalytic,
  listAnalyticDefinitions,
  listCustomerAnalytics,
  listEnvironments,
  recordAnalyticHistory,
} from '../api'
import type { AnalyticDefinition, CustomerAnalytic, Environment } from '../types'

interface Props {
  orgId: string
}

export function CustomerAnalyticsSection({ orgId }: Props) {
  const [items, setItems] = useState<CustomerAnalytic[]>([])
  const [defs, setDefs] = useState<AnalyticDefinition[]>([])
  const [envs, setEnvs] = useState<Environment[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const refresh = () => {
    setLoading(true)
    setError(null)
    Promise.all([
      listCustomerAnalytics(orgId),
      listAnalyticDefinitions(),
      listEnvironments(orgId),
    ])
      .then(([ca, d, e]) => {
        setItems(ca)
        setDefs(d)
        setEnvs(e)
      })
      .catch((e: Error) => setError(e.message))
      .finally(() => setLoading(false))
  }

  useEffect(() => {
    refresh()
  }, [orgId])

  if (loading)
    return (
      <section className="detail-section">
        <h3 className="section-title">Analytics</h3>
        <div className="state-cell">Loading…</div>
      </section>
    )

  return (
    <section className="detail-section">
      <h3 className="section-title">Analytics</h3>
      {error && <div className="error-banner">{error}</div>}

      {items.length === 0 && (
        <div className="state-cell">No analytics tracked for this customer yet.</div>
      )}

      {items.map((ca) => (
        <CustomerAnalyticCard key={ca.id} customerAnalytic={ca} onChanged={refresh} />
      ))}

      <AddCustomerAnalyticForm
        orgId={orgId}
        defs={defs}
        envs={envs}
        existing={items.map((ca) => `${ca.environment}:${ca.analytic_definition}`)}
        onAdded={refresh}
      />
    </section>
  )
}

function CustomerAnalyticCard({
  customerAnalytic,
  onChanged,
}: {
  customerAnalytic: CustomerAnalytic
  onChanged: () => void
}) {
  const [open, setOpen] = useState(false)
  return (
    <div className="catalog-card">
      <div className="catalog-row">
        <button className="chevron-btn" onClick={() => setOpen(!open)}>
          {open ? '▼' : '▶'}
        </button>
        <strong>{customerAnalytic.definition_name}</strong>
        <span className="badge">{customerAnalytic.environment_name}</span>
        <span className="badge">{customerAnalytic.frequency}</span>
        <span className="meta">
          {customerAnalytic.history.length} capture
          {customerAnalytic.history.length === 1 ? '' : 's'}
        </span>
        <button
          className="btn-icon"
          onClick={() => {
            if (window.confirm(`Stop tracking ${customerAnalytic.definition_name} in ${customerAnalytic.environment_name}?`))
              deleteCustomerAnalytic(customerAnalytic.id).then(onChanged)
          }}
        >
          ×
        </button>
      </div>

      {open && (
        <div className="catalog-children">
          {customerAnalytic.history.length > 0 && (
            <table className="data-table" style={{ marginBottom: 8 }}>
              <thead>
                <tr>
                  <th style={{ width: 180 }}>When</th>
                  <th style={{ width: 140 }}>Value</th>
                  <th>Description</th>
                  <th style={{ width: 36 }}></th>
                </tr>
              </thead>
              <tbody>
                {customerAnalytic.history.map((h) => (
                  <tr key={h.id}>
                    <td className="meta">{new Date(h.captured_at).toLocaleString()}</td>
                    <td>{h.value ?? '—'}</td>
                    <td>{h.description ?? '—'}</td>
                    <td>
                      <button
                        className="btn-icon"
                        onClick={() => {
                          if (window.confirm('Delete this capture?'))
                            deleteAnalyticHistory(customerAnalytic.id, h.id).then(onChanged)
                        }}
                      >
                        ×
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
          <RecordCaptureForm customerAnalyticId={customerAnalytic.id} onAdded={onChanged} />
        </div>
      )}
    </div>
  )
}

function RecordCaptureForm({
  customerAnalyticId,
  onAdded,
}: {
  customerAnalyticId: string
  onAdded: () => void
}) {
  const [value, setValue] = useState('')
  const [description, setDescription] = useState('')
  const [busy, setBusy] = useState(false)

  const submit = async () => {
    if (!value.trim() && !description.trim()) return
    setBusy(true)
    try {
      await recordAnalyticHistory(customerAnalyticId, {
        value: value.trim() ? value.trim() : null,
        description: description.trim() || null,
      })
      setValue('')
      setDescription('')
      onAdded()
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="add-row">
      <input
        className="input compact"
        style={{ width: 140 }}
        placeholder="Value (e.g. 42, 87.3)"
        value={value}
        onChange={(e) => setValue(e.target.value)}
      />
      <input
        className="input compact"
        style={{ flex: 1 }}
        placeholder="Description (optional)"
        value={description}
        onChange={(e) => setDescription(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === 'Enter') submit()
        }}
      />
      <button className="btn" disabled={busy || (!value.trim() && !description.trim())} onClick={submit}>
        + Record
      </button>
    </div>
  )
}

function AddCustomerAnalyticForm({
  orgId,
  defs,
  envs,
  existing,
  onAdded,
}: {
  orgId: string
  defs: AnalyticDefinition[]
  envs: Environment[]
  existing: string[]
  onAdded: () => void
}) {
  const [defId, setDefId] = useState('')
  const [envId, setEnvId] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const isDuplicate = !!defId && !!envId && existing.includes(`${envId}:${defId}`)

  const submit = async () => {
    if (!defId || !envId || isDuplicate) return
    setBusy(true)
    setError(null)
    try {
      await createCustomerAnalytic({
        organization: orgId,
        environment: envId,
        analytic_definition: defId,
      })
      setDefId('')
      setEnvId('')
      onAdded()
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setBusy(false)
    }
  }

  if (defs.length === 0) {
    return (
      <div className="meta" style={{ marginTop: 8 }}>
        Define analytics first in the Analytics sidebar panel.
      </div>
    )
  }

  return (
    <div className="add-row">
      <select className="input compact" value={defId} onChange={(e) => setDefId(e.target.value)}>
        <option value="">— Analytic —</option>
        {defs.map((d) => (
          <option key={d.id} value={d.id}>
            {d.name} ({d.frequency})
          </option>
        ))}
      </select>
      <select className="input compact" value={envId} onChange={(e) => setEnvId(e.target.value)}>
        <option value="">— Env —</option>
        {envs.map((e) => (
          <option key={e.id} value={e.id}>
            {e.name}
          </option>
        ))}
      </select>
      <button className="btn" disabled={busy || !defId || !envId || isDuplicate} onClick={submit}>
        + Track
      </button>
      {isDuplicate && <span className="meta">already tracked</span>}
      {error && <span className="error-text">{error}</span>}
    </div>
  )
}
