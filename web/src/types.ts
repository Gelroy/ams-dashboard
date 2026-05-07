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

export interface Paginated<T> {
  count: number
  next: string | null
  previous: string | null
  results: T[]
}
