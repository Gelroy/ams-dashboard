import { useEffect, useState } from 'react'

import {
  addInstalledSoftware,
  copyInstalledSoftwareFrom,
  copyServerToEnvPeers,
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

  if (loading) return <div className="state-cell">Loading…</div>

  return (
    <>
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
          existingServers={servers}
          onAdd={async (envId, name, copyFromServerId) => {
            const created = await createServer(orgId, { environment: envId, name })
            if (copyFromServerId) {
              try {
                await copyInstalledSoftwareFrom(orgId, created.id, copyFromServerId)
              } catch (e) {
                // Surface but don't block — the server is created; the user
                // can populate installed software manually if the copy failed.
                console.error('copy-from failed:', e)
              }
            }
            // Refetch the full tree so the new server's installed_software
            // (and the copy's effects) are reflected accurately.
            refresh()
          }}
        />
      )}
    </>
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
            {/* Fixed width on Server pushes the IP column right next to
                it instead of letting the auto-layout stretch Server to
                fill leftover space. Baskets gets the flex room instead. */}
            <th style={{ width: 200 }}>Server</th>
            {/* IP address — header intentionally empty; the masked input
                ###.###.###.### is self-evident. */}
            <th style={{ width: 140 }}></th>
            <th style={{ width: 90 }}>Env</th>
            <th>Baskets</th>
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
  const [ip, setIp] = useState(server.ip_address ?? '')

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
            style={{ width: '100%' }}
            value={name}
            onChange={(e) => setName(e.target.value)}
            onBlur={() => {
              if (name !== server.name) onPatch(server.id, { name })
            }}
          />
        </td>
        <td>
          <input
            className="input compact"
            style={{ width: '100%' }}
            value={ip}
            placeholder="___.___.___.___"
            inputMode="numeric"
            // 15 = max valid IPv4 length (e.g. "255.255.255.255")
            maxLength={15}
            onChange={(e) => setIp(maskIpv4(e.target.value))}
            onBlur={() => {
              const next = ip.trim() || null
              const current = server.ip_address ?? null
              if (next === current) return
              // Don't PATCH a half-typed value that the backend would
              // reject — clear input or valid IPv4 only.
              if (next !== null && !isValidIpv4(next)) {
                // Roll the input back so the user sees they need to finish.
                setIp(server.ip_address ?? '')
                return
              }
              onPatch(server.id, { ip_address: next })
            }}
            title="IPv4 address — leave blank if not recorded"
          />
        </td>
        <td>
          <span className="badge">{server.environment_name}</span>
        </td>
        <td className="meta" style={{ fontSize: 11 }}>
          {server.baskets.length === 0
            ? '—'
            : server.baskets.map((b) => b.name).join(', ')}
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
          <td colSpan={8} className="server-detail-cell">
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
  const [copyBusy, setCopyBusy] = useState(false)
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

  const copyToEnv = async () => {
    if (
      !window.confirm(
        'Do you want to copy all the details from this server to every other server in this environment?',
      )
    ) {
      return
    }
    setCopyBusy(true)
    setError(null)
    try {
      const { updated } = await copyServerToEnvPeers(orgId, server.id)
      if (updated === 0) {
        window.alert('No other servers in this environment to copy to.')
      }
      onChanged()
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setCopyBusy(false)
    }
  }

  return (
    <div className="server-detail">
      <div
        className="panel-header-row"
        style={{ marginBottom: 8, justifyContent: 'flex-end' }}
      >
        <button
          className="btn"
          disabled={copyBusy}
          onClick={copyToEnv}
          title="Replace every other server in this environment's notes, baskets, and installed software with this server's"
        >
          {copyBusy ? 'Copying…' : 'Copy to Environment'}
        </button>
      </div>
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
  // Optimistic copies of the two editable fields (release, functionally_latest).
  // The controlled inputs render from these immediately on change so the user
  // sees their pick stick instead of snapping back during the PATCH round-trip.
  // The optimistic value is overwritten when `entry` arrives fresh from the
  // parent's refresh (useEffects below). On PATCH failure we surface the
  // error and roll back.
  const [pendingRelease, setPendingRelease] = useState<string | null>(
    entry.software_release ?? null,
  )
  const [pendingFnLatest, setPendingFnLatest] = useState(entry.functionally_latest)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    setPendingRelease(entry.software_release ?? null)
  }, [entry.software_release])
  useEffect(() => {
    setPendingFnLatest(entry.functionally_latest)
  }, [entry.functionally_latest])

  // After the SoftwareVersion squash, a Software row IS a specific version,
  // so its releases hang off the Software directly. The previous version
  // dropdown has nothing left to choose between.
  const sw = catalog.find((s) => s.id === entry.software)
  const releases = sw?.releases ?? []

  const patch = (
    body: { software_release?: string | null; functionally_latest?: boolean },
    optimistic: () => void,
    rollback: () => void,
  ) => {
    optimistic()
    setSaving(true)
    setError(null)
    updateInstalledSoftware(orgId, serverId, entry.id, body)
      .then(() => onChanged())
      .catch((e: Error) => {
        rollback()
        setError(e.message)
      })
      .finally(() => setSaving(false))
  }

  return (
    <div className="release-row" style={{ flexWrap: 'wrap' }}>
      <strong style={{ width: 180 }}>{entry.software_name}</strong>
      <span className="meta" style={{ width: 80 }}>{entry.version_label}</span>
      <select
        className="input compact"
        value={pendingRelease ?? ''}
        disabled={saving}
        onChange={(e) => {
          const newReleaseId = e.target.value || null
          const prevRelease = pendingRelease
          patch(
            { software_release: newReleaseId },
            () => setPendingRelease(newReleaseId),
            () => setPendingRelease(prevRelease),
          )
        }}
      >
        <option value="">— release —</option>
        {releases.map((r) => (
          <option key={r.id} value={r.id}>
            {r.release_name} {r.status === 'Latest' ? '(Latest)' : ''}
          </option>
        ))}
      </select>
      {/* Functionally Latest — per-server override for interim fixes that
          don't apply (e.g. UNIX-only release on a Windows customer). When
          checked, this server is treated as up-to-date for Needs Patching
          and skipped by the auto-PatchExecution-on-new-Latest signal. */}
      <label
        className="filter-checkbox"
        title="Treat the currently installed release as Latest for this server (overrides the catalog). Use when an interim release doesn't apply to this customer."
      >
        <input
          type="checkbox"
          checked={pendingFnLatest}
          disabled={saving}
          onChange={(e) => {
            const newVal = e.target.checked
            const prev = pendingFnLatest
            patch(
              { functionally_latest: newVal },
              () => setPendingFnLatest(newVal),
              () => setPendingFnLatest(prev),
            )
          }}
        />
        Functionally Latest
      </label>
      <button
        className="btn-icon"
        disabled={saving}
        onClick={() => {
          if (window.confirm(`Remove ${entry.software_name}?`))
            removeInstalledSoftware(orgId, serverId, entry.id)
              .then(onChanged)
              .catch((e: Error) => setError(e.message))
        }}
      >
        ×
      </button>
      {saving && <span className="meta">saving…</span>}
      {error && (
        <span className="error-banner" style={{ flexBasis: '100%', marginTop: '0.25rem' }}>
          {error}
        </span>
      )}
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
  const [releaseId, setReleaseId] = useState('')
  const [busy, setBusy] = useState(false)

  // After the squash, picking a Software fully determines the version, so
  // we go straight from Software → Release. One fewer dropdown.
  const sw = available.find((s) => s.id === softwareId)
  const releases = sw?.releases ?? []

  if (available.length === 0) return null

  const submit = async () => {
    if (!softwareId) return
    setBusy(true)
    try {
      await addInstalledSoftware(orgId, serverId, {
        software: softwareId,
        software_release: releaseId || null,
      })
      setSoftwareId('')
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
          setReleaseId('')
        }}
      >
        <option value="">— Software —</option>
        {available.map((s) => (
          <option key={s.id} value={s.id}>
            {s.name} ({s.version})
          </option>
        ))}
      </select>
      <select
        className="input compact"
        value={releaseId}
        disabled={!softwareId}
        onChange={(e) => setReleaseId(e.target.value)}
      >
        <option value="">— Release —</option>
        {releases.map((r) => (
          <option key={r.id} value={r.id}>
            {r.release_name} {r.status === 'Latest' ? '(Latest)' : ''}
          </option>
        ))}
      </select>
      <button className="btn" disabled={busy || !softwareId} onClick={submit}>
        + Record
      </button>
    </div>
  )
}

function AddServerForm({
  envs,
  existingServers,
  onAdd,
}: {
  envs: Environment[]
  existingServers: Server[]
  onAdd: (envId: string, name: string, copyFromServerId?: string) => Promise<void>
}) {
  const [envId, setEnvId] = useState(envs[0]?.id ?? '')
  const [name, setName] = useState('')
  const [includeExisting, setIncludeExisting] = useState(false)
  const [sourceServerId, setSourceServerId] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  // Build label "ENV / server" so the user can disambiguate two servers
  // with the same name in different envs.
  const envNameById = new Map(envs.map((e) => [e.id, e.name]))
  const sortedSources = [...existingServers].sort((a, b) => {
    const ea = envNameById.get(a.environment) ?? ''
    const eb = envNameById.get(b.environment) ?? ''
    return ea === eb ? a.name.localeCompare(b.name) : ea.localeCompare(eb)
  })

  const submit = async () => {
    if (!envId || !name.trim()) return
    if (includeExisting && !sourceServerId) {
      setError('Pick a source server to copy from.')
      return
    }
    setBusy(true)
    setError(null)
    try {
      await onAdd(envId, name.trim(), includeExisting ? sourceServerId : undefined)
      setName('')
      setIncludeExisting(false)
      setSourceServerId('')
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
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
      {existingServers.length > 0 && (
        <div className="add-row">
          <label className="filter-checkbox">
            <input
              type="checkbox"
              checked={includeExisting}
              onChange={(e) => {
                setIncludeExisting(e.target.checked)
                if (!e.target.checked) setSourceServerId('')
              }}
            />
            Include existing software?
          </label>
          {includeExisting && (
            <select
              className="input compact"
              value={sourceServerId}
              onChange={(e) => setSourceServerId(e.target.value)}
            >
              <option value="">— copy from… —</option>
              {sortedSources.map((s) => (
                <option key={s.id} value={s.id}>
                  {(envNameById.get(s.environment) ?? '?')} / {s.name}
                </option>
              ))}
            </select>
          )}
        </div>
      )}
    </div>
  )
}

function PatchingBadge({ status }: { status: NeedsPatchingStatus }) {
  if (status === 'yes') return <span className="badge patch-yes">Needs Patching</span>
  if (status === 'no') return <span className="badge patch-no">Up to Date</span>
  return <span className="meta">—</span>
}

/** Mask raw user input into IPv4 shape ###.###.###.### — per-segment we
 *  keep only digits, cap at 3 chars each, and keep at most 4 segments. We
 *  don't auto-insert dots; the user types them (or pastes a real IP), and
 *  the function just sanitises whatever they typed. */
function maskIpv4(raw: string): string {
  return raw
    .split('.')
    .slice(0, 4)
    .map((s) => s.replace(/\D/g, '').slice(0, 3))
    .join('.')
}

/** Strict-ish IPv4 validator — four octets, each 0–255. Used on blur to
 *  decide whether to PATCH or roll the input back. Empty string is handled
 *  by the caller (treated as "clear the field"). */
function isValidIpv4(s: string): boolean {
  const m = s.match(/^(\d{1,3})\.(\d{1,3})\.(\d{1,3})\.(\d{1,3})$/)
  if (!m) return false
  return m.slice(1).every((part) => {
    const n = parseInt(part, 10)
    return n >= 0 && n <= 255
  })
}
