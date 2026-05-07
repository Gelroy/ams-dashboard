export type AmsLevel = 'Essential' | 'Enhanced' | 'Expert'
export type ZabbixStatus = 'Good' | 'Issue'

export interface Organization {
  id: string
  jira_org_id: string
  jira_name: string
  local_name: string | null
  display_name: string
  ams_level: AmsLevel | null
  zabbix_status: ZabbixStatus | null
  help_desk_phone: string | null
  connection_guide_url: string | null
  notes: string | null
  open_ticket_count: number | null
  ticket_count_synced_at: string | null
  last_ticket_sync_error: string | null
  jira_synced_at: string | null
}

export interface OrgUser {
  id: string
  organization: string
  jira_account_id: string
  display_name: string | null
  email: string | null
  role: string | null
  alerts_enabled: boolean
  is_primary: boolean
}

export interface Paginated<T> {
  count: number
  next: string | null
  previous: string | null
  results: T[]
}

export type EditableOrgFields = Pick<
  Organization,
  | 'local_name'
  | 'ams_level'
  | 'zabbix_status'
  | 'help_desk_phone'
  | 'connection_guide_url'
  | 'notes'
>

export type EditableUserFields = Pick<OrgUser, 'role' | 'alerts_enabled' | 'is_primary'>

export interface Environment {
  id: string
  organization: string
  name: string
  position: number
}

export interface Server {
  id: string
  environment: string
  environment_name: string
  name: string
  notes: string | null
  cert_expires_on: string | null
}

export type EditableServerFields = Pick<Server, 'name' | 'notes' | 'cert_expires_on'>

export type SoftwareVersionStatus = 'Latest' | 'Supported' | 'EOL'

export interface SoftwareRelease {
  id: string
  software_version: string
  release_name: string
  released_on: string | null
  position: number
}

export interface SoftwareVersion {
  id: string
  software: string
  version: string
  status: SoftwareVersionStatus
  position: number
  releases: SoftwareRelease[]
}

export interface Software {
  id: string
  name: string
  description: string | null
  versions: SoftwareVersion[]
}
