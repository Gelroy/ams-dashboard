import type { Organization, Paginated } from './types'

const API_BASE = '/api'

async function request<T>(path: string): Promise<T> {
  const r = await fetch(`${API_BASE}${path}`)
  if (!r.ok) {
    throw new Error(`HTTP ${r.status} ${r.statusText}`)
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
