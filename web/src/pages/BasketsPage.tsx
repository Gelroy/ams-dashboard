import { useEffect, useState } from 'react'

import {
  addBasketSoftware,
  createBasket,
  deleteBasket,
  listBaskets,
  listSoftware,
  removeBasketSoftware,
  updateBasket,
  updateBasketSoftware,
} from '../api'
import type { Basket, BasketSoftwareEntry, Software } from '../types'

export function BasketsPage() {
  const [baskets, setBaskets] = useState<Basket[]>([])
  const [catalog, setCatalog] = useState<Software[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const refresh = () => {
    setLoading(true)
    setError(null)
    Promise.all([listBaskets(), listSoftware()])
      .then(([b, c]) => {
        setBaskets(b)
        setCatalog(c)
      })
      .catch((e: Error) => setError(e.message))
      .finally(() => setLoading(false))
  }

  useEffect(refresh, [])

  return (
    <div>
      <div className="panel-header-row">
        <span className="panel-title">Version Baskets</span>
        <span className="panel-hint">{baskets.length} basket{baskets.length === 1 ? '' : 's'}</span>
      </div>

      {error && <div className="error-banner">{error}</div>}
      {loading && <div className="state-cell">Loading…</div>}

      {!loading && baskets.length === 0 && (
        <div className="state-cell">
          No baskets yet. A basket bundles software at specific Versions; servers
          assigned to a basket are flagged Needs-Patching when their installed
          release isn’t the Latest in the pinned Version.
        </div>
      )}

      <div>
        {baskets.map((b) => (
          <BasketCard key={b.id} basket={b} catalog={catalog} onChanged={refresh} />
        ))}
      </div>

      <AddBasketForm onAdded={refresh} />
    </div>
  )
}

function BasketCard({
  basket,
  catalog,
  onChanged,
}: {
  basket: Basket
  catalog: Software[]
  onChanged: () => void
}) {
  const [open, setOpen] = useState(false)
  const [name, setName] = useState(basket.name)
  const [description, setDescription] = useState(basket.description ?? '')

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
            if (name !== basket.name) updateBasket(basket.id, { name }).then(onChanged)
          }}
        />
        <span className="meta">
          {basket.software_entries.length} software
        </span>
        <button
          className="btn-icon"
          title="Delete basket"
          onClick={() => {
            if (window.confirm(`Delete basket ${basket.name}?`))
              deleteBasket(basket.id).then(onChanged)
          }}
        >
          ×
        </button>
      </div>

      {open && (
        <div className="catalog-children">
          <div className="field" style={{ marginBottom: 8 }}>
            <div className="field-label">Description</div>
            <input
              className="input"
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              onBlur={() => {
                if (description !== (basket.description ?? ''))
                  updateBasket(basket.id, { description: description || null }).then(onChanged)
              }}
            />
          </div>

          {basket.software_entries.length === 0 && (
            <div className="state-cell">No software pinned yet.</div>
          )}
          {basket.software_entries.map((e) => (
            <BasketSoftwareRow
              key={e.software}
              basketId={basket.id}
              entry={e}
              catalog={catalog}
              onChanged={onChanged}
            />
          ))}

          <AddBasketSoftwareForm
            basketId={basket.id}
            catalog={catalog}
            existing={basket.software_entries.map((e) => e.software)}
            onAdded={onChanged}
          />
        </div>
      )}
    </div>
  )
}

function BasketSoftwareRow({
  basketId,
  entry,
  catalog,
  onChanged,
}: {
  basketId: string
  entry: BasketSoftwareEntry
  catalog: Software[]
  onChanged: () => void
}) {
  const sw = catalog.find((s) => s.id === entry.software)
  const versionOptions = sw?.versions ?? []
  return (
    <div className="release-row">
      <strong style={{ width: 180 }}>{entry.software_name}</strong>
      <select
        className="input compact"
        value={entry.software_version}
        onChange={(e) =>
          updateBasketSoftware(basketId, entry.software, {
            software_version: e.target.value,
          }).then(onChanged)
        }
      >
        {versionOptions.map((v) => (
          <option key={v.id} value={v.id}>
            {v.version} ({v.status})
          </option>
        ))}
      </select>
      <span className="meta" style={{ flex: 1 }}>
        Latest:{' '}
        {entry.latest_release_name ? (
          <span className="badge badge-latest">{entry.latest_release_name}</span>
        ) : (
          '— none flagged Latest yet'
        )}
      </span>
      <button
        className="btn-icon"
        title="Remove from basket"
        onClick={() => {
          if (window.confirm(`Remove ${entry.software_name} from this basket?`))
            removeBasketSoftware(basketId, entry.software).then(onChanged)
        }}
      >
        ×
      </button>
    </div>
  )
}

function AddBasketForm({ onAdded }: { onAdded: () => void }) {
  const [name, setName] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const submit = async () => {
    if (!name.trim()) return
    setBusy(true)
    setError(null)
    try {
      await createBasket(name.trim())
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
        placeholder="New basket name"
        value={name}
        onChange={(e) => setName(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === 'Enter') submit()
        }}
      />
      <button className="btn" disabled={busy || !name.trim()} onClick={submit}>
        + Add Basket
      </button>
      {error && <span className="error-text">{error}</span>}
    </div>
  )
}

function AddBasketSoftwareForm({
  basketId,
  catalog,
  existing,
  onAdded,
}: {
  basketId: string
  catalog: Software[]
  existing: string[]
  onAdded: () => void
}) {
  const available = catalog.filter((s) => !existing.includes(s.id))
  const [softwareId, setSoftwareId] = useState('')
  const [versionId, setVersionId] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const sw = available.find((s) => s.id === softwareId)
  const versions = sw?.versions ?? []

  if (available.length === 0) return null

  const submit = async () => {
    if (!softwareId || !versionId) return
    setBusy(true)
    setError(null)
    try {
      await addBasketSoftware(basketId, { software: softwareId, software_version: versionId })
      setSoftwareId('')
      setVersionId('')
      onAdded()
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="add-row">
      <select
        className="input compact"
        value={softwareId}
        onChange={(e) => {
          setSoftwareId(e.target.value)
          setVersionId('')
        }}
      >
        <option value="">— Software —</option>
        {available.map((s) => (
          <option key={s.id} value={s.id}>
            {s.name}
          </option>
        ))}
      </select>
      <select
        className="input compact"
        value={versionId}
        disabled={!softwareId}
        onChange={(e) => setVersionId(e.target.value)}
      >
        <option value="">— Version —</option>
        {versions.map((v) => (
          <option key={v.id} value={v.id}>
            {v.version} ({v.status})
          </option>
        ))}
      </select>
      <button className="btn" disabled={busy || !softwareId || !versionId} onClick={submit}>
        + Add
      </button>
      {error && <span className="error-text">{error}</span>}
    </div>
  )
}
