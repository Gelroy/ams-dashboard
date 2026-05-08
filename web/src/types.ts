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
  needs_patching: NeedsPatchingStatus
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
  baskets: ServerBasketRef[]
  installed_software: ServerInstalledSoftwareEntry[]
  needs_patching: NeedsPatchingStatus
}

export type EditableServerFields = Pick<Server, 'name' | 'notes' | 'cert_expires_on'>

export type LifecycleStatus = 'Latest' | 'Supported' | 'EOL'
// Back-compat alias used by existing imports.
export type SoftwareVersionStatus = LifecycleStatus

export interface SoftwareRelease {
  id: string
  software_version: string
  release_name: string
  released_on: string | null
  status: LifecycleStatus
  position: number
}

export interface SoftwareVersion {
  id: string
  software: string
  version: string
  status: LifecycleStatus
  position: number
  releases: SoftwareRelease[]
}

export interface Software {
  id: string
  name: string
  description: string | null
  versions: SoftwareVersion[]
}

export type NeedsPatchingStatus = 'yes' | 'no' | 'unknown'

export interface BasketSoftwareEntry {
  basket: string
  software: string
  software_name: string
  software_version: string
  version_label: string
  version_status: LifecycleStatus
  latest_release_id: string | null
  latest_release_name: string | null
}

export interface Basket {
  id: string
  name: string
  description: string | null
  software_entries: BasketSoftwareEntry[]
}

export interface ServerBasketRef {
  id: string
  name: string
}

export interface ServerInstalledSoftwareEntry {
  id: string
  software: string
  software_name: string
  software_version: string
  version_label: string
  software_release: string | null
  release_name: string | null
}

export interface PatchGroupStep {
  id: string
  patch_group: string
  step_num: number
  description: string
  est_time: string | null
  per_server: boolean
}

export interface PatchGroup {
  id: string
  name: string
  steps: PatchGroupStep[]
}

export interface PatchPlanGroupRef {
  patch_plan: string
  patch_group: string
  group_name: string
  position: number
  step_count: number
}

export interface PatchPlan {
  id: string
  name: string
  basket: string | null
  basket_name: string | null
  plan_groups: PatchPlanGroupRef[]
}

export type PatchExecutionStatus = 'active' | 'completed' | 'aborted'

export interface PatchExecutionStep {
  id: string
  step_num: number
  description: string
  est_time: string | null
  per_server: boolean
  started_at: string | null
  finished_at: string | null
  total_time: string | null
  done: boolean
}

export interface PatchExecutionAbort {
  id: string
  attempt_num: number
  attempt_date: string | null
  elapsed: string | null
  steps_completed: number
  total_steps: number
  notes: string
  created_at: string
}

export interface PatchExecution {
  id: string
  patch_plan: string | null
  plan_name: string | null
  basket: string
  basket_name: string | null
  organization: string
  organization_name: string
  environment: string
  environment_name: string
  status: PatchExecutionStatus
  patch_date: string | null
  started_at: string | null
  completed_at: string | null
  total_time: string | null
  steps: PatchExecutionStep[]
  aborts: PatchExecutionAbort[]
}

export interface PatchHistoryEntry {
  id: string
  organization: string
  environment: string
  environment_name: string
  patched_on: string
  software_name: string
  from_release: string | null
  to_release: string
}

export type AnalyticFrequency = 'Daily' | 'Weekly' | 'Monthly' | 'Quarterly' | 'Yearly'
export type AnalyticScope = 'environment' | 'server'

export interface AnalyticDefinition {
  id: string
  name: string
  frequency: AnalyticFrequency
  scope: AnalyticScope
}

export interface CustomerAnalyticHistoryEntry {
  id: string
  customer_analytic: string
  captured_at: string
  value: string | null  // DecimalField → string in DRF
  description: string | null
}

export interface CustomerAnalytic {
  id: string
  organization: string
  environment: string
  environment_name: string
  server: string | null
  server_name: string | null
  analytic_definition: string
  definition_name: string
  frequency: AnalyticFrequency
  scope: AnalyticScope
  history: CustomerAnalyticHistoryEntry[]
}

export interface Staff {
  id: string
  name: string
  email: string | null
  phone: string | null
  cognito_sub: string | null
  sme_organization_ids: string[]
}

export type ActivityType = 'Meeting' | 'Patch' | 'Cert' | 'Review' | 'Other'
export type ActivityPriority = 'High' | 'Medium' | 'Low'
export type ActivityStatus = 'scheduled' | 'completed'

export interface Activity {
  id: string
  name: string
  scheduled_at: string
  organization: string | null
  organization_name: string | null
  assigned_staff: string | null
  assigned_staff_name: string | null
  type: ActivityType
  priority: ActivityPriority
  duration: string | null
  notes: string | null
  status: ActivityStatus
  completed_at: string | null
}

export interface CriticalEvent {
  date: string
  time: string | null
  kind: 'activity' | 'cert' | 'patch'
  label: string
  source_kind: string
  source_id: string
  organization_id: string | null
  type?: ActivityType
  priority?: ActivityPriority
}

export interface CriticalCalendar {
  start: string
  end: string
  events: CriticalEvent[]
}
