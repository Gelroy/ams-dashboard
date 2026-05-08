import type {
  Basket,
  EditableOrgFields,
  EditableServerFields,
  EditableUserFields,
  Environment,
  Organization,
  OrgUser,
  Paginated,
  Server,
  ServerInstalledSoftwareEntry,
  Software,
  SoftwareRelease,
  SoftwareVersion,
  SoftwareVersionStatus,
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

// Software catalog. /api/software/ returns the full nested tree.
export function listSoftware(): Promise<Software[]> {
  return request<Software[]>(`/software/`)
}

export function createSoftware(name: string): Promise<Software> {
  return request<Software>(`/software/`, {
    method: 'POST',
    body: JSON.stringify({ name }),
  })
}

export function updateSoftware(
  id: string,
  patch: Partial<Pick<Software, 'name' | 'description'>>,
): Promise<Software> {
  return request<Software>(`/software/${id}/`, {
    method: 'PATCH',
    body: JSON.stringify(patch),
  })
}

export function deleteSoftware(id: string): Promise<void> {
  return fetch(`/api/software/${id}/`, { method: 'DELETE' }).then((r) => {
    if (!r.ok) throw new Error(`HTTP ${r.status} ${r.statusText}`)
  })
}

export function createVersion(
  softwareId: string,
  payload: { version: string; status: SoftwareVersionStatus; position: number },
): Promise<SoftwareVersion> {
  return request<SoftwareVersion>(`/software/${softwareId}/versions/`, {
    method: 'POST',
    body: JSON.stringify(payload),
  })
}

export function updateVersion(
  softwareId: string,
  versionId: string,
  patch: Partial<Pick<SoftwareVersion, 'version' | 'status' | 'position'>>,
): Promise<SoftwareVersion> {
  return request<SoftwareVersion>(`/software/${softwareId}/versions/${versionId}/`, {
    method: 'PATCH',
    body: JSON.stringify(patch),
  })
}

export function deleteVersion(softwareId: string, versionId: string): Promise<void> {
  return fetch(`/api/software/${softwareId}/versions/${versionId}/`, { method: 'DELETE' }).then(
    (r) => {
      if (!r.ok) throw new Error(`HTTP ${r.status} ${r.statusText}`)
    },
  )
}

export function createRelease(
  softwareId: string,
  versionId: string,
  payload: {
    release_name: string
    released_on?: string | null
    status?: SoftwareVersionStatus
    position?: number
  },
): Promise<SoftwareRelease> {
  return request<SoftwareRelease>(
    `/software/${softwareId}/versions/${versionId}/releases/`,
    { method: 'POST', body: JSON.stringify(payload) },
  )
}

export function updateRelease(
  softwareId: string,
  versionId: string,
  releaseId: string,
  patch: Partial<Pick<SoftwareRelease, 'release_name' | 'released_on' | 'status' | 'position'>>,
): Promise<SoftwareRelease> {
  return request<SoftwareRelease>(
    `/software/${softwareId}/versions/${versionId}/releases/${releaseId}/`,
    { method: 'PATCH', body: JSON.stringify(patch) },
  )
}

export function deleteRelease(
  softwareId: string,
  versionId: string,
  releaseId: string,
): Promise<void> {
  return fetch(
    `/api/software/${softwareId}/versions/${versionId}/releases/${releaseId}/`,
    { method: 'DELETE' },
  ).then((r) => {
    if (!r.ok) throw new Error(`HTTP ${r.status} ${r.statusText}`)
  })
}

// Baskets
export function listBaskets(): Promise<Basket[]> {
  return request<Basket[]>(`/baskets/`)
}

export function createBasket(name: string, description?: string): Promise<Basket> {
  return request<Basket>(`/baskets/`, {
    method: 'POST',
    body: JSON.stringify({ name, description: description ?? null }),
  })
}

export function updateBasket(
  id: string,
  patch: Partial<Pick<Basket, 'name' | 'description'>>,
): Promise<Basket> {
  return request<Basket>(`/baskets/${id}/`, {
    method: 'PATCH',
    body: JSON.stringify(patch),
  })
}

export function deleteBasket(id: string): Promise<void> {
  return fetch(`/api/baskets/${id}/`, { method: 'DELETE' }).then((r) => {
    if (!r.ok) throw new Error(`HTTP ${r.status} ${r.statusText}`)
  })
}

export function addBasketSoftware(
  basketId: string,
  payload: { software: string; software_version: string },
): Promise<unknown> {
  return request(`/baskets/${basketId}/software/`, {
    method: 'POST',
    body: JSON.stringify(payload),
  })
}

export function updateBasketSoftware(
  basketId: string,
  softwareId: string,
  patch: { software_version: string },
): Promise<unknown> {
  return request(`/baskets/${basketId}/software/${softwareId}/`, {
    method: 'PATCH',
    body: JSON.stringify(patch),
  })
}

export function removeBasketSoftware(basketId: string, softwareId: string): Promise<void> {
  return fetch(`/api/baskets/${basketId}/software/${softwareId}/`, { method: 'DELETE' }).then(
    (r) => {
      if (!r.ok) throw new Error(`HTTP ${r.status} ${r.statusText}`)
    },
  )
}

// Per-server basket assignment
export function getServerBaskets(orgId: string, serverId: string): Promise<{ basket_ids: string[] }> {
  return request<{ basket_ids: string[] }>(
    `/organizations/${orgId}/servers/${serverId}/baskets/`,
  )
}

export function setServerBaskets(
  orgId: string,
  serverId: string,
  basketIds: string[],
): Promise<{ basket_ids: string[] }> {
  return request<{ basket_ids: string[] }>(
    `/organizations/${orgId}/servers/${serverId}/baskets/`,
    { method: 'PUT', body: JSON.stringify({ basket_ids: basketIds }) },
  )
}

// Per-server installed software
export function listInstalledSoftware(
  orgId: string,
  serverId: string,
): Promise<ServerInstalledSoftwareEntry[]> {
  return request<ServerInstalledSoftwareEntry[]>(
    `/organizations/${orgId}/servers/${serverId}/installed/`,
  )
}

export function addInstalledSoftware(
  orgId: string,
  serverId: string,
  payload: { software: string; software_version: string; software_release?: string | null },
): Promise<ServerInstalledSoftwareEntry> {
  return request<ServerInstalledSoftwareEntry>(
    `/organizations/${orgId}/servers/${serverId}/installed/`,
    { method: 'POST', body: JSON.stringify(payload) },
  )
}

export function updateInstalledSoftware(
  orgId: string,
  serverId: string,
  id: string,
  patch: { software_version?: string; software_release?: string | null },
): Promise<ServerInstalledSoftwareEntry> {
  return request<ServerInstalledSoftwareEntry>(
    `/organizations/${orgId}/servers/${serverId}/installed/${id}/`,
    { method: 'PATCH', body: JSON.stringify(patch) },
  )
}

export function removeInstalledSoftware(
  orgId: string,
  serverId: string,
  id: string,
): Promise<void> {
  return fetch(`/api/organizations/${orgId}/servers/${serverId}/installed/${id}/`, {
    method: 'DELETE',
  }).then((r) => {
    if (!r.ok) throw new Error(`HTTP ${r.status} ${r.statusText}`)
  })
}

// Patch Groups
export function listPatchGroups(): Promise<import('./types').PatchGroup[]> {
  return request(`/patch-groups/`)
}

export function createPatchGroup(name: string): Promise<import('./types').PatchGroup> {
  return request(`/patch-groups/`, {
    method: 'POST',
    body: JSON.stringify({ name }),
  })
}

export function updatePatchGroup(
  id: string,
  patch: { name?: string },
): Promise<import('./types').PatchGroup> {
  return request(`/patch-groups/${id}/`, {
    method: 'PATCH',
    body: JSON.stringify(patch),
  })
}

export function deletePatchGroup(id: string): Promise<void> {
  return fetch(`/api/patch-groups/${id}/`, { method: 'DELETE' }).then((r) => {
    if (!r.ok) throw new Error(`HTTP ${r.status} ${r.statusText}`)
  })
}

export function createPatchGroupStep(
  groupId: string,
  payload: { step_num: number; description: string; est_time?: string | null; per_server?: boolean },
): Promise<import('./types').PatchGroupStep> {
  return request(`/patch-groups/${groupId}/steps/`, {
    method: 'POST',
    body: JSON.stringify(payload),
  })
}

export function updatePatchGroupStep(
  groupId: string,
  stepId: string,
  patch: Partial<Pick<import('./types').PatchGroupStep, 'description' | 'est_time' | 'per_server' | 'step_num'>>,
): Promise<import('./types').PatchGroupStep> {
  return request(`/patch-groups/${groupId}/steps/${stepId}/`, {
    method: 'PATCH',
    body: JSON.stringify(patch),
  })
}

export function deletePatchGroupStep(groupId: string, stepId: string): Promise<void> {
  return fetch(`/api/patch-groups/${groupId}/steps/${stepId}/`, { method: 'DELETE' }).then((r) => {
    if (!r.ok) throw new Error(`HTTP ${r.status} ${r.statusText}`)
  })
}

// Patch Plans
export function listPatchPlans(): Promise<import('./types').PatchPlan[]> {
  return request(`/patch-plans/`)
}

export function createPatchPlan(name: string): Promise<import('./types').PatchPlan> {
  return request(`/patch-plans/`, {
    method: 'POST',
    body: JSON.stringify({ name }),
  })
}

export function updatePatchPlan(
  id: string,
  patch: { name?: string; basket?: string | null },
): Promise<import('./types').PatchPlan> {
  return request(`/patch-plans/${id}/`, {
    method: 'PATCH',
    body: JSON.stringify(patch),
  })
}

export function deletePatchPlan(id: string): Promise<void> {
  return fetch(`/api/patch-plans/${id}/`, { method: 'DELETE' }).then((r) => {
    if (!r.ok) throw new Error(`HTTP ${r.status} ${r.statusText}`)
  })
}

export function addPatchPlanGroup(
  planId: string,
  payload: { patch_group: string; position: number },
): Promise<unknown> {
  return request(`/patch-plans/${planId}/groups/`, {
    method: 'POST',
    body: JSON.stringify(payload),
  })
}

export function removePatchPlanGroup(planId: string, groupId: string): Promise<void> {
  return fetch(`/api/patch-plans/${planId}/groups/${groupId}/`, { method: 'DELETE' }).then((r) => {
    if (!r.ok) throw new Error(`HTTP ${r.status} ${r.statusText}`)
  })
}
