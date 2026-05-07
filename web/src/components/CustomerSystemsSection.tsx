import { useEffect, useState } from 'react'

import {
  addInstalledSoftware,
  createEnvironment,
  createServer,
  deleteEnvironment,
  deleteServer,
  listBaskets,
  listEnvironments,
  listServers,
  listSoftware,
  removeInstalledSoftware,
  setServerBaskets,
  updateInstalledSoftware,
  updateServer,
} from '../api'
import type {
  Basket,
  Environment,
  NeedsPatchingStatus,
  Server,
  ServerInstalledSoftwareEntry,
  Software,
} from '../types'

interface Props {
  orgId: string
}

export function CustomerSystemsSection({ orgId }: Props) {
  const [envs, setEnvs] = useState<Environment[]>([])
  const [servers, setServers] = useState<Server[]>([])
  const [baskets, setBaskets] = useState<Basket[]>([])
  const [catalog, setCatalog] = useState<Software[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [expanded, setExpanded] = useState<string | null>(null)

  const refresh = () => {
    setLoading(true)
    Promise.all([listEnvironments(orgId), listServers(orgId), listBaskets(), listSoftware()])
      .then(([envData, serverData, basketData, catData]) => {
        setEnvs(envData)
        setServers(serverData)
        setBaskets(basketData)
        setCatalog(catData)
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
        <h3 className="section-title">Customer Systems</h3>
        <div className="state-cell">Loading…</div>
      </section>
    )

  return (
    <section className="detail-section">
      <h3 className="section-title">Customer Systems</h3>
      {error && <div className="error-banner">{error}</div>}

      <EnvChips
        envs={envs}
        servers={servers}
        onAdd={async (name) => {
          const e = await createEnvironment(orgId, name, envs.length)
          setEnvs([...envs, e])
        }}
        onDelete={async (env) => {
          await deleteEnvironment(orgId, env.id)
          setEnvs(envs.filter((x) => x.id !== env.id))
        }}
      />

      <ServerTable
        envs={envs}
        servers={servers}
        baskets={baskets}
        catalog={catalog}
        expanded={expanded}
        onToggleExpand={(id) => setExpanded(expanded === id ? null : id)}
        orgId={orgId}
        onPatch={async (id, patch) => {
          const updated = await updateServer(orgId, id, patch)
          setServers(servers.map((s) => (s.id === id ? updated : s)))
        }}
        onDelete={async (id) => {
          if (!window.confirm('Delete this server?')) return
          await deleteServer(orgId, id)
          setServers(servers.filter((s) => s.id !== id))
          if (expanded === id) setExpanded(null)
        }}
        onChanged={refresh}
      />

      {envs.length > 0 && (
        <AddServerForm
          envs={envs}
          onAdd={async (envId, name) => {
            const created = await createServer(orgId, { environment: envId, name })
            setServers([...servers, created])
          }}
        />
      )}
    </section>
  )
}

function EnvChips({
  envs,
  servers,
  onAdd,
  onDelete,
}: {
  envs: Environment[]
  servers: Server[]
  onAdd: (name: string) => Promise<void>
  onDelete: (env: Environment) => Promise<void>
}) {
  const [adding, setAdding] = useState(false)
  const [name, setName] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const submit = async () => {
    if (!name.trim()) return
    setBusy(true)
    setError(null)
    try {
      await onAdd(name.trim().toUpperCase())
      setName('')
      setAdding(false)
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="env-chips">
      {envs.map((e) => {
        const inUse = servers.some((s) => s.environment === e.id)
        return (
          <span key={e.id} className="env-chip">
            {e.name}
            <button
              className="chip-remove"
              title={inUse ? 'Has servers — remove them first' : 'Delete'}
              disabled={inUse}
              onClick={() => onDelete(e)}
            >
              ×
            </button>
          </span>
        )
      })}
      {adding ? (
        <span className="env-chip-add">
          <input
            className="input compact"
            value={name}
            placeholder="Name"
            autoFocus
            onChange={(e) => setName(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter') submit()
              if (e.key === 'Escape') setAdding(false)
            }}
          />
          <button className="btn" disabled={busy} onClick={submit}>
            Add
          </button>
          <button className="btn" onClick={() => setAdding(false)}>
            Cancel
          </button>
        </span>
      ) : (
        <button className="btn btn-link" onClick={() => setAdding(true)}>
          + Add Environment
        </button>
      )}
      {error && <span className="error-text">{error}</span>}
    </div>
  )
}

interface ServerTableProps {
  envs: Environment[]
  servers: Server[]
  baskets: Basket[]
  catalog: Software[]
  expanded: string | null
  onToggleExpand: (id: string) => void
  orgId: string
  onPatch: (id: string, patch: Partial<Server>) => Promise<void>
  onDelete: (id: string) => Promise<void>
  onChanged: () => void
}

function ServerTable({
  envs,
  servers,
  baskets,
  catalog,
  expanded,
  onToggleExpand,
  orgId,
  onPatch,
  onDelete,
  onChanged,
}: ServerTableProps) {
  if (envs.length === 0) {
    return <div className="state-cell">Add an environment first to start tracking servers.</div>
  }
  if (servers.length === 0) {
    return <div className="state-cell">No servers yet.</div>
  }
  return (
    <div className="table-wrap" style={{ marginTop: 12 }}>
      <table className="data-table">
        <thead>
          <tr>
            <th style={{ width: 24 }}></th>
            <th>Server</th>
            <th style={{ width: 90 }}>Env</th>
            <th style={{ width: 140 }}>Cert Expires</th>
            <th style={{ width: 130 }}>Patching</th>
            <th style={{ width: 50 }}></th>
          </tr>
        </thead>
        <tbody>
          {servers.map((s) => (
            <ServerRow
              key={s.id}
              server={s}
              baskets={baskets}
              catalog={catalog}
              expanded={expanded === s.id}
              onToggleExpand={() => onToggleExpand(s.id)}
              orgId={orgId}
              onPatch={onPatch}
              onDelete={onDelete}
              onChanged={onChanged}
            />
          ))}
        </tbody>
      </table>
    </div>
  )
}

function ServerRow({
  server,
  baskets,
  catalog,
  expanded,
  onToggleExpand,
  orgId,
  onPatch,
  onDelete,
  onChanged,
}: {
  server: Server
  baskets: Basket[]
  catalog: Software[]
  expanded: boolean
  onToggleExpand: () => void
  orgId: string
  onPatch: (id: string, patch: Partial<Server>) => Promise<void>
  onDelete: (id: string) => Promise<void>
  onChanged: () => void
}) {
  const [name, setName] = useState(server.name)

  return (
    <>
      <tr>
        <td>
          <button className="chevron-btn" onClick={onToggleExpand}>
            {expanded ? '▼' : '▶'}
          </button>
        </td>
        <td>
          <input
            className="input compact"
            value={name}
            onChange={(e) => setName(e.target.value)}
            onBlur={() => {
              if (name !== server.name) onPatch(server.id, { name })
            }}
          />
        </td>
        <td>
          <span className="badge">{server.environment_name}</span>
        </td>
        <td>
          <input
            type="date"
            className="input compact"
            value={server.cert_expires_on ?? ''}
            onChange={(e) => onPatch(server.id, { cert_expires_on: e.target.value || null })}
          />
        </td>
        <td>
          <PatchingBadge status={server.needs_patching} />
        </td>
        <td style={{ textAlign: 'center' }}>
          <button className="btn-icon" onClick={() => onDelete(server.id)} title="Delete">
            ×
          </button>
        </td>
      </tr>
      {expanded && (
        <tr>
          <td colSpan={6} className="server-detail-cell">
            <ServerDetailPanel
              server={server}
              baskets={baskets}
              catalog={catalog}
              orgId={orgId}
              onChanged={onChanged}
            />
          </td>
        </tr>
      )}
    </>
  )
}

function ServerDetailPanel({
  server,
  baskets,
  catalog,
  orgId,
  onChanged,
}: {
  server: Server
  baskets: Basket[]
  catalog: Software[]
  orgId: string
  onChanged: () => void
}) {
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const assignedIds = new Set(server.baskets.map((b) => b.id))

  const toggleBasket = async (basketId: string) => {
    setBusy(true)
    setError(null)
    const next = new Set(assignedIds)
    if (next.has(basketId)) next.delete(basketId)
    else next.add(basketId)
    try {
      await setServerBaskets(orgId, server.id, [...next])
      onChanged()
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="server-detail">
      <div className="sub-section">
        <div className="field-label">Assigned Baskets</div>
        <div className="env-chips">
          {baskets.length === 0 && <span className="meta">No baskets defined yet — see the Baskets panel.</span>}
          {baskets.map((b) => {
            const on = assignedIds.has(b.id)
            return (
              <button
                key={b.id}
                className={on ? 'env-chip env-chip-on' : 'env-chip env-chip-off'}
                disabled={busy}
                onClick={() => toggleBasket(b.id)}
              >
                {on ? '✓ ' : ''}
                {b.name}
              </button>
            )
          })}
        </div>
        {error && <div className="error-text">{error}</div>}
      </div>

      <div className="sub-section">
        <div className="field-label">Installed Software</div>
        <InstalledSoftwareList
          orgId={orgId}
          server={server}
          catalog={catalog}
          onChanged={onChanged}
        />
      </div>
    </div>
  )
}

function InstalledSoftwareList({
  orgId,
  server,
  catalog,
  onChanged,
}: {
  orgId: string
  server: Server
  catalog: Software[]
  onChanged: () => void
}) {
  return (
    <div>
      {server.installed_software.length === 0 && (
        <div className="meta" style={{ padding: '4px 0' }}>
          Nothing recorded yet.
        </div>
      )}
      {server.installed_software.map((entry) => (
        <InstalledRow
          key={entry.id}
          orgId={orgId}
          serverId={server.id}
          entry={entry}
          catalog={catalog}
          onChanged={onChanged}
        />
      ))}
      <AddInstalledForm
        orgId={orgId}
        serverId={server.id}
        catalog={catalog}
        existing={server.installed_software.map((e) => e.software)}
        onAdded={onChanged}
      />
    </div>
  )
}

function InstalledRow({
  orgId,
  serverId,
  entry,
  catalog,
  onChanged,
}: {
  orgId: string
  serverId: string
  entry: ServerInstalledSoftwareEntry
  catalog: Software[]
  onChanged: () => void
}) {
  const sw = catalog.find((s) => s.id === entry.software)
  const versions = sw?.versions ?? []
  const releases = versions.find((v) => v.id === entry.software_version)?.releases ?? []

  return (
    <div className="release-row">
      <strong style={{ width: 180 }}>{entry.software_name}</strong>
      <select
        className="input compact"
        value={entry.software_version}
        onChange={(e) =>
          updateInstalledSoftware(orgId, serverId, entry.id, {
            software_version: e.target.value,
            software_release: null,
          }).then(onChanged)
        }
      >
        {versions.map((v) => (
          <option key={v.id} value={v.id}>
            {v.version}
          </option>
        ))}
      </select>
      <select
        className="input compact"
        value={entry.software_release ?? ''}
        onChange={(e) =>
          updateInstalledSoftware(orgId, serverId, entry.id, {
            software_release: e.target.value || null,
          }).then(onChanged)
        }
      >
        <option value="">— release —</option>
        {releases.map((r) => (
          <option key={r.id} value={r.id}>
            {r.release_name} {r.status === 'Latest' ? '(Latest)' : ''}
          </option>
        ))}
      </select>
      <button
        className="btn-icon"
        onClick={() => {
          if (window.confirm(`Remove ${entry.software_name}?`))
            removeInstalledSoftware(orgId, serverId, entry.id).then(onChanged)
        }}
      >
        ×
      </button>
    </div>
  )
}

function AddInstalledForm({
  orgId,
  serverId,
  catalog,
  existing,
  onAdded,
}: {
  orgId: string
  serverId: string
  catalog: Software[]
  existing: string[]
  onAdded: () => void
}) {
  const available = catalog.filter((s) => !existing.includes(s.id))
  const [softwareId, setSoftwareId] = useState('')
  const [versionId, setVersionId] = useState('')
  const [releaseId, setReleaseId] = useState('')
  const [busy, setBusy] = useState(false)

  const sw = available.find((s) => s.id === softwareId)
  const versions = sw?.versions ?? []
  const releases = versions.find((v) => v.id === versionId)?.releases ?? []

  if (available.length === 0) return null

  const submit = async () => {
    if (!softwareId || !versionId) return
    setBusy(true)
    try {
      await addInstalledSoftware(orgId, serverId, {
        software: softwareId,
        software_version: versionId,
        software_release: releaseId || null,
      })
      setSoftwareId('')
      setVersionId('')
      setReleaseId('')
      onAdded()
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
          setReleaseId('')
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
        onChange={(e) => {
          setVersionId(e.target.value)
          setReleaseId('')
        }}
      >
        <option value="">— Version —</option>
        {versions.map((v) => (
          <option key={v.id} value={v.id}>
            {v.version}
          </option>
        ))}
      </select>
      <select
        className="input compact"
        value={releaseId}
        disabled={!versionId}
        onChange={(e) => setReleaseId(e.target.value)}
      >
        <option value="">— Release —</option>
        {releases.map((r) => (
          <option key={r.id} value={r.id}>
            {r.release_name} {r.status === 'Latest' ? '(Latest)' : ''}
          </option>
        ))}
      </select>
      <button className="btn" disabled={busy || !softwareId || !versionId} onClick={submit}>
        + Record
      </button>
    </div>
  )
}

function AddServerForm({
  envs,
  onAdd,
}: {
  envs: Environment[]
  onAdd: (envId: string, name: string) => Promise<void>
}) {
  const [envId, setEnvId] = useState(envs[0]?.id ?? '')
  const [name, setName] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const submit = async () => {
    if (!envId || !name.trim()) return
    setBusy(true)
    setError(null)
    try {
      await onAdd(envId, name.trim())
      setName('')
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="add-row">
      <select className="input compact" value={envId} onChange={(e) => setEnvId(e.target.value)}>
        {envs.map((e) => (
          <option key={e.id} value={e.id}>
            {e.name}
          </option>
        ))}
      </select>
      <input
        className="input compact"
        placeholder="New server name"
        value={name}
        onChange={(e) => setName(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === 'Enter') submit()
        }}
      />
      <button className="btn" disabled={busy || !name.trim()} onClick={submit}>
        + Add Server
      </button>
      {error && <span className="error-text">{error}</span>}
    </div>
  )
}

function PatchingBadge({ status }: { status: NeedsPatchingStatus }) {
  if (status === 'yes') return <span className="badge patch-yes">Needs Patching</span>
  if (status === 'no') return <span className="badge patch-no">Up to Date</span>
  return <span className="meta">—</span>
}
