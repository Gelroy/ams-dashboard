import { useEffect, useState } from 'react'

import {
  createAnalyticDefinition,
  deleteAnalyticDefinition,
  listAnalyticDefinitions,
  updateAnalyticDefinition,
} from '../api'
import type { AnalyticDefinition, AnalyticFrequency } from '../types'

const FREQUENCIES: AnalyticFrequency[] = ['Daily', 'Weekly', 'Monthly', 'Quarterly', 'Yearly']

export function AnalyticsPage() {
  const [defs, setDefs] = useState<AnalyticDefinition[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const refresh = () => {
    setLoading(true)
    setError(null)
    listAnalyticDefinitions()
      .then(setDefs)
      .catch((e: Error) => setError(e.message))
      .finally(() => setLoading(false))
  }
  useEffect(refresh, [])

  return (
    <div>
      <div className="panel-header-row">
        <span className="panel-title">Analytics Definitions</span>
        <span className="panel-hint">{defs.length} defined</span>
      </div>

      {error && <div className="error-banner">{error}</div>}
      {loading && <div className="state-cell">Loading…</div>}
      {!loading && defs.length === 0 && (
        <div className="state-cell">
          No analytics defined yet. These are the metrics you track per
          customer/environment — record counts, peak CPU, peak disk, etc.
        </div>
      )}

      <div>
        {defs.map((d) => (
          <DefinitionRow key={d.id} def={d} onChanged={refresh} />
        ))}
      </div>

      <AddDefinitionForm onAdded={refresh} />
    </div>
  )
}

function DefinitionRow({ def, onChanged }: { def: AnalyticDefinition; onChanged: () => void }) {
  const [name, setName] = useState(def.name)

  return (
    <div className="catalog-card">
      <div className="catalog-row">
        <input
          className="input"
          value={name}
          onChange={(e) => setName(e.target.value)}
          onBlur={() => {
            if (name !== def.name) updateAnalyticDefinition(def.id, { name }).then(onChanged)
          }}
        />
        <select
          className="input compact"
          value={def.frequency}
          onChange={(e) =>
            updateAnalyticDefinition(def.id, {
              frequency: e.target.value as AnalyticFrequency,
            }).then(onChanged)
          }
        >
          {FREQUENCIES.map((f) => (
            <option key={f} value={f}>
              {f}
            </option>
          ))}
        </select>
        <button
          className="btn-icon"
          onClick={() => {
            if (window.confirm(`Delete analytic ${def.name}?`))
              deleteAnalyticDefinition(def.id).then(onChanged)
          }}
        >
          ×
        </button>
      </div>
    </div>
  )
}

function AddDefinitionForm({ onAdded }: { onAdded: () => void }) {
  const [name, setName] = useState('')
  const [frequency, setFrequency] = useState<AnalyticFrequency>('Monthly')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const submit = async () => {
    if (!name.trim()) return
    setBusy(true)
    setError(null)
    try {
      await createAnalyticDefinition({ name: name.trim(), frequency })
      setName('')
      setFrequency('Monthly')
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
        placeholder="New analytic name"
        value={name}
        onChange={(e) => setName(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === 'Enter') submit()
        }}
      />
      <select
        className="input compact"
        value={frequency}
        onChange={(e) => setFrequency(e.target.value as AnalyticFrequency)}
      >
        {FREQUENCIES.map((f) => (
          <option key={f} value={f}>
            {f}
          </option>
        ))}
      </select>
      <button className="btn" disabled={busy || !name.trim()} onClick={submit}>
        + Add Analytic
      </button>
      {error && <span className="error-text">{error}</span>}
    </div>
  )
}
