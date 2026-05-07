import type {
  EditableOrgFields,
  EditableServerFields,
  EditableUserFields,
  Environment,
  Organization,
  OrgUser,
  Paginated,
  Server,
} from './types'

const API_BASE = '/api'

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const r = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers: {
      'Content-Type': 'application/json',
      Accept: 'application/json',
      ...(init?.headers ?? {}),
    },
  })
  if (!r.ok) {
    let detail = ''
    try {
      detail = ` — ${await r.text()}`
    } catch {
      // ignore
    }
    throw new Error(`HTTP ${r.status} ${r.statusText}${detail}`)
  }
  return r.json() as Promise<T>
}

export interface ListOrganizationsParams {
  q?: string
  ams_level?: string
  limit?: number
  offset?: number
}

export function listOrganizations(
  params: ListOrganizationsParams = {},
): Promise<Paginated<Organization>> {
  const qs = new URLSearchParams()
  if (params.q) qs.set('q', params.q)
  if (params.ams_level) qs.set('ams_level', params.ams_level)
  if (params.limit != null) qs.set('limit', String(params.limit))
  if (params.offset != null) qs.set('offset', String(params.offset))
  const tail = qs.toString() ? `?${qs.toString()}` : ''
  return request<Paginated<Organization>>(`/organizations/${tail}`)
}

export function getOrganization(id: string): Promise<Organization> {
  return request<Organization>(`/organizations/${id}/`)
}

export function updateOrganization(
  id: string,
  patch: Partial<EditableOrgFields>,
): Promise<Organization> {
  return request<Organization>(`/organizations/${id}/`, {
    method: 'PATCH',
    body: JSON.stringify(patch),
  })
}

export function listOrgUsers(orgId: string): Promise<Paginated<OrgUser>> {
  return request<Paginated<OrgUser>>(`/organizations/${orgId}/users/`)
}

export function updateOrgUser(
  orgId: string,
  userId: string,
  patch: Partial<EditableUserFields>,
): Promise<OrgUser> {
  return request<OrgUser>(`/organizations/${orgId}/users/${userId}/`, {
    method: 'PATCH',
    body: JSON.stringify(patch),
  })
}

// Environments are non-paginated.
export function listEnvironments(orgId: string): Promise<Environment[]> {
  return request<Environment[]>(`/organizations/${orgId}/environments/`)
}

export function createEnvironment(orgId: string, name: string, position: number): Promise<Environment> {
  return request<Environment>(`/organizations/${orgId}/environments/`, {
    method: 'POST',
    body: JSON.stringify({ name, position }),
  })
}

export function deleteEnvironment(orgId: string, envId: string): Promise<void> {
  return fetch(`/api/organizations/${orgId}/environments/${envId}/`, { method: 'DELETE' }).then(
    (r) => {
      if (!r.ok) throw new Error(`HTTP ${r.status} ${r.statusText}`)
    },
  )
}

export function listServers(orgId: string): Promise<Server[]> {
  return request<Server[]>(`/organizations/${orgId}/servers/`)
}

export function createServer(
  orgId: string,
  payload: { environment: string; name: string; cert_expires_on?: string | null; notes?: string | null },
): Promise<Server> {
  return request<Server>(`/organizations/${orgId}/servers/`, {
    method: 'POST',
    body: JSON.stringify(payload),
  })
}

export function updateServer(
  orgId: string,
  serverId: string,
  patch: Partial<EditableServerFields>,
): Promise<Server> {
  return request<Server>(`/organizations/${orgId}/servers/${serverId}/`, {
    method: 'PATCH',
    body: JSON.stringify(patch),
  })
}

export function deleteServer(orgId: string, serverId: string): Promise<void> {
  return fetch(`/api/organizations/${orgId}/servers/${serverId}/`, { method: 'DELETE' }).then(
    (r) => {
      if (!r.ok) throw new Error(`HTTP ${r.status} ${r.statusText}`)
    },
  )
}
