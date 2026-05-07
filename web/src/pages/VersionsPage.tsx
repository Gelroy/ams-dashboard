import { useEffect, useState } from 'react'

import {
  createRelease,
  createSoftware,
  createVersion,
  deleteRelease,
  deleteSoftware,
  deleteVersion,
  listSoftware,
  updateRelease,
  updateSoftware,
  updateVersion,
} from '../api'
import type {
  Software,
  SoftwareRelease,
  SoftwareVersion,
  SoftwareVersionStatus,
} from '../types'

const STATUSES: SoftwareVersionStatus[] = ['Latest', 'Supported', 'EOL']

// Composing release names from a version + suffix.
// "1.0" → prefix "1.0."     ; suffix "1" → "1.0.1"
// "11.0.6.x" → prefix "11.0.6." (trailing wildcard stripped); suffix "13" → "11.0.6.13"
function versionPrefix(versionLabel: string): string {
  const stripped = versionLabel.replace(/\.[xX*]$/, '').replace(/\.+$/, '')
  return stripped + '.'
}
function composeReleaseName(versionLabel: string, suffix: string): string {
  return versionPrefix(versionLabel) + suffix.replace(/^\.+/, '').trim()
}
function suffixOf(versionLabel: string, releaseName: string): string {
  const prefix = versionPrefix(versionLabel)
  return releaseName.startsWith(prefix) ? releaseName.slice(prefix.length) : releaseName
}

export function VersionsPage() {
  const [items, setItems] = useState<Software[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const refresh = () => {
    setLoading(true)
    setError(null)
    listSoftware()
      .then(setItems)
      .catch((e: Error) => setError(e.message))
      .finally(() => setLoading(false))
  }

  useEffect(refresh, [])

  return (
    <div>
      <div className="panel-header-row">
        <span className="panel-title">Software Catalog</span>
        <span className="panel-hint">{items.length} software</span>
      </div>

      {error && <div className="error-banner">{error}</div>}
      {loading && <div className="state-cell">Loading…</div>}

      {!loading && items.length === 0 && (
        <div className="state-cell">No software yet — add some below.</div>
      )}

      <div>
        {items.map((sw) => (
          <SoftwareCard key={sw.id} software={sw} onChanged={refresh} />
        ))}
      </div>

      <AddSoftwareForm onAdded={refresh} />
    </div>
  )
}

function SoftwareCard({ software, onChanged }: { software: Software; onChanged: () => void }) {
  const [open, setOpen] = useState(false)
  const [name, setName] = useState(software.name)

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
            if (name !== software.name) updateSoftware(software.id, { name }).then(onChanged)
          }}
        />
        <span className="meta">{software.versions.length} versions</span>
        <button
          className="btn-icon"
          title="Delete software"
          onClick={() => {
            if (window.confirm(`Delete ${software.name} and all its versions/releases?`)) {
              deleteSoftware(software.id).then(onChanged)
            }
          }}
        >
          ×
        </button>
      </div>

      {open && (
        <div className="catalog-children">
          {software.versions.map((v) => (
            <VersionCard
              key={v.id}
              softwareId={software.id}
              version={v}
              onChanged={onChanged}
            />
          ))}
          <AddVersionForm
            softwareId={software.id}
            nextPosition={software.versions.length}
            onAdded={onChanged}
          />
        </div>
      )}
    </div>
  )
}

function VersionCard({
  softwareId,
  version,
  onChanged,
}: {
  softwareId: string
  version: SoftwareVersion
  onChanged: () => void
}) {
  const [open, setOpen] = useState(false)
  const [vName, setVName] = useState(version.version)
  const [error, setError] = useState<string | null>(null)

  const patch = (p: Partial<SoftwareVersion>) => {
    setError(null)
    updateVersion(softwareId, version.id, p)
      .then(onChanged)
      .catch((e: Error) => setError(e.message))
  }

  return (
    <div className="catalog-card nested">
      <div className="catalog-row">
        <button className="chevron-btn" onClick={() => setOpen(!open)}>
          {open ? '▼' : '▶'}
        </button>
        <input
          className="input compact"
          style={{ width: 100 }}
          value={vName}
          onChange={(e) => setVName(e.target.value)}
          onBlur={() => {
            if (vName !== version.version) patch({ version: vName })
          }}
        />
        <select
          className="input compact"
          value={version.status}
          onChange={(e) => patch({ status: e.target.value as SoftwareVersionStatus })}
        >
          {STATUSES.map((s) => (
            <option key={s} value={s}>
              {s}
            </option>
          ))}
        </select>
        <span className="meta">{version.releases.length} releases</span>
        <button
          className="btn-icon"
          title="Delete version"
          onClick={() => {
            if (window.confirm(`Delete version ${version.version}?`)) {
              deleteVersion(softwareId, version.id).then(onChanged)
            }
          }}
        >
          ×
        </button>
      </div>
      {error && <div className="error-text" style={{ marginLeft: 28 }}>{error}</div>}

      {open && (
        <div className="catalog-children">
          {version.releases.map((r) => (
            <ReleaseRow
              key={r.id}
              softwareId={softwareId}
              versionLabel={version.version}
              versionId={version.id}
              release={r}
              onChanged={onChanged}
            />
          ))}
          <AddReleaseForm
            softwareId={softwareId}
            versionLabel={version.version}
            versionId={version.id}
            nextPosition={version.releases.length}
            onAdded={onChanged}
          />
        </div>
      )}
    </div>
  )
}

function ReleaseRow({
  softwareId,
  versionLabel,
  versionId,
  release,
  onChanged,
}: {
  softwareId: string
  versionLabel: string
  versionId: string
  release: SoftwareRelease
  onChanged: () => void
}) {
  const prefix = versionPrefix(versionLabel)
  const [suffix, setSuffix] = useState(suffixOf(versionLabel, release.release_name))

  return (
    <div className="release-row">
      <span className="release-prefix">{prefix}</span>
      <input
        className="input compact"
        style={{ width: 90 }}
        value={suffix}
        onChange={(e) => setSuffix(e.target.value)}
        onBlur={() => {
          const composed = composeReleaseName(versionLabel, suffix)
          if (composed !== release.release_name)
            updateRelease(softwareId, versionId, release.id, { release_name: composed }).then(
              onChanged,
            )
        }}
      />
      <input
        type="date"
        className="input compact"
        value={release.released_on ?? ''}
        onChange={(e) =>
          updateRelease(softwareId, versionId, release.id, {
            released_on: e.target.value || null,
          }).then(onChanged)
        }
      />
      <select
        className="input compact"
        value={release.status}
        onChange={(e) =>
          updateRelease(softwareId, versionId, release.id, {
            status: e.target.value as SoftwareVersionStatus,
          }).then(onChanged)
        }
      >
        {STATUSES.map((s) => (
          <option key={s} value={s}>
            {s}
          </option>
        ))}
      </select>
      {release.status === 'Latest' && <span className="badge badge-latest">Latest</span>}
      <button
        className="btn-icon"
        title="Delete release"
        onClick={() => {
          if (window.confirm(`Delete release ${release.release_name}?`))
            deleteRelease(softwareId, versionId, release.id).then(onChanged)
        }}
      >
        ×
      </button>
    </div>
  )
}

function AddSoftwareForm({ onAdded }: { onAdded: () => void }) {
  const [name, setName] = useState('')
  const [busy, setBusy] = useState(false)

  const submit = async () => {
    if (!name.trim()) return
    setBusy(true)
    try {
      await createSoftware(name.trim())
      setName('')
      onAdded()
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="add-row">
      <input
        className="input compact"
        placeholder="New software name"
        value={name}
        onChange={(e) => setName(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === 'Enter') submit()
        }}
      />
      <button className="btn" disabled={busy || !name.trim()} onClick={submit}>
        + Add Software
      </button>
    </div>
  )
}

function AddVersionForm({
  softwareId,
  nextPosition,
  onAdded,
}: {
  softwareId: string
  nextPosition: number
  onAdded: () => void
}) {
  const [version, setVersion] = useState('')
  const [status, setStatus] = useState<SoftwareVersionStatus>('Supported')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const submit = async () => {
    if (!version.trim()) return
    setBusy(true)
    setError(null)
    try {
      await createVersion(softwareId, { version: version.trim(), status, position: nextPosition })
      setVersion('')
      setStatus('Supported')
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
        placeholder="Version (e.g. 1.0)"
        value={version}
        onChange={(e) => setVersion(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === 'Enter') submit()
        }}
      />
      <select
        className="input compact"
        value={status}
        onChange={(e) => setStatus(e.target.value as SoftwareVersionStatus)}
      >
        {STATUSES.map((s) => (
          <option key={s} value={s}>
            {s}
          </option>
        ))}
      </select>
      <button className="btn" disabled={busy || !version.trim()} onClick={submit}>
        + Add Version
      </button>
      {error && <span className="error-text">{error}</span>}
    </div>
  )
}

function AddReleaseForm({
  softwareId,
  versionLabel,
  versionId,
  nextPosition,
  onAdded,
}: {
  softwareId: string
  versionLabel: string
  versionId: string
  nextPosition: number
  onAdded: () => void
}) {
  const prefix = versionPrefix(versionLabel)
  const [suffix, setSuffix] = useState('')
  const [date, setDate] = useState('')
  const [status, setStatus] = useState<SoftwareVersionStatus>('Latest')
  const [busy, setBusy] = useState(false)

  const submit = async () => {
    const trimmed = suffix.trim().replace(/^\.+/, '')
    if (!trimmed) return
    setBusy(true)
    try {
      await createRelease(softwareId, versionId, {
        release_name: composeReleaseName(versionLabel, trimmed),
        released_on: date || null,
        status,
        position: nextPosition,
      })
      setSuffix('')
      setDate('')
      setStatus('Latest')
      onAdded()
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="add-row">
      <span className="release-prefix">{prefix}</span>
      <input
        className="input compact"
        style={{ width: 90 }}
        placeholder="suffix"
        value={suffix}
        onChange={(e) => setSuffix(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === 'Enter') submit()
        }}
      />
      <input
        type="date"
        className="input compact"
        value={date}
        onChange={(e) => setDate(e.target.value)}
      />
      <select
        className="input compact"
        value={status}
        onChange={(e) => setStatus(e.target.value as SoftwareVersionStatus)}
      >
        {STATUSES.map((s) => (
          <option key={s} value={s}>
            {s}
          </option>
        ))}
      </select>
      <button className="btn" disabled={busy || !suffix.trim()} onClick={submit}>
        + Add Release
      </button>
    </div>
  )
}
