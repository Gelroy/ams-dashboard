import { useEffect, useState } from 'react'

import {
  createEnvironment,
  createServer,
  deleteEnvironment,
  deleteServer,
  listEnvironments,
  listServers,
  updateServer,
} from '../api'
import type { Environment, Server } from '../types'

interface Props {
  orgId: string
}

export function CustomerSystemsSection({ orgId }: Props) {
  const [envs, setEnvs] = useState<Environment[]>([])
  const [servers, setServers] = useState<Server[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    Promise.all([listEnvironments(orgId), listServers(orgId)])
      .then(([envData, serverData]) => {
        if (cancelled) return
        setEnvs(envData)
        setServers(serverData)
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
        onPatch={async (id, patch) => {
          const updated = await updateServer(orgId, id, patch)
          setServers(servers.map((s) => (s.id === id ? updated : s)))
        }}
        onDelete={async (id) => {
          if (!window.confirm('Delete this server?')) return
          await deleteServer(orgId, id)
          setServers(servers.filter((s) => s.id !== id))
        }}
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

function ServerTable({
  envs,
  servers,
  onPatch,
  onDelete,
}: {
  envs: Environment[]
  servers: Server[]
  onPatch: (id: string, patch: Partial<Server>) => Promise<void>
  onDelete: (id: string) => Promise<void>
}) {
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
            <th>Server</th>
            <th style={{ width: 100 }}>Environment</th>
            <th style={{ width: 160 }}>Cert Expires</th>
            <th style={{ width: 60 }}></th>
          </tr>
        </thead>
        <tbody>
          {servers.map((s) => (
            <ServerRow key={s.id} server={s} onPatch={onPatch} onDelete={onDelete} />
          ))}
        </tbody>
      </table>
    </div>
  )
}

function ServerRow({
  server,
  onPatch,
  onDelete,
}: {
  server: Server
  onPatch: (id: string, patch: Partial<Server>) => Promise<void>
  onDelete: (id: string) => Promise<void>
}) {
  const [name, setName] = useState(server.name)

  return (
    <tr>
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
      <td style={{ textAlign: 'center' }}>
        <button className="btn-icon" onClick={() => onDelete(server.id)} title="Delete">
          ×
        </button>
      </td>
    </tr>
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
