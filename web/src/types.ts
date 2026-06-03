export type AmsLevel = 'Essential' | 'Enhanced' | 'Expert'
export type ZabbixStatus = 'Good' | 'Issue'
export type Country = 'US' | 'CA'

export interface OrgDocument {
  id: string
  organization: string
  description: string
  url: string
  position: number
}

export interface SmeStaffRef {
  id: string
  name: string
  email: string | null
  phone: string | null
}

export interface Organization {
  id: string
  jira_org_id: string
  jira_name: string
  local_name: string | null
  display_name: string
  ams_level: AmsLevel | null
  zabbix_status: ZabbixStatus | null
  not_using_zabbix: boolean
  country: Country | null
  help_desk_phone: string | null
  roadmap: string | null
  notes: string | null
  open_ticket_count: number | null
  automated_ticket_count: number | null
  manual_ticket_count: number | null
  ticket_count_synced_at: string | null
  last_ticket_sync_error: string | null
  jira_synced_at: string | null
  documents: OrgDocument[]
  sme_staff: SmeStaffRef[]
  needs_patching: NeedsPatchingStatus
  patching_status: 'green' | 'yellow' | 'red' | 'unknown'
  cert_status: 'green' | 'yellow' | 'red' | 'unknown'
  zabbix_status_rollup: 'green' | 'yellow' | 'red' | 'unknown' | 'na'
}

export interface OrgUser {
  id: string
  organization: string
  jira_account_id: string
  display_name: string | null
  email: string | null
  // Local overrides — when set, take precedence in the UI. JIRA-synced
  // display_name / email remain visible via tooltip + as fallback.
  local_display_name: string | null
  local_email: string | null
  role: string | null
  alerts_enabled: boolean
  is_primary: boolean
  ams_report: boolean
  is_hidden: boolean
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
  | 'not_using_zabbix'
  | 'country'
  | 'help_desk_phone'
  | 'roadmap'
  | 'notes'
>

export type EditableUserFields = Pick<
  OrgUser,
  | 'role'
  | 'alerts_enabled'
  | 'is_primary'
  | 'ams_report'
  | 'is_hidden'
  | 'local_display_name'
  | 'local_email'
>

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
  ip_address: string | null
  notes: string | null
  cert_expires_on: string | null
  baskets: ServerBasketRef[]
  installed_software: ServerInstalledSoftwareEntry[]
  needs_patching: NeedsPatchingStatus
}

export type EditableServerFields = Pick<Server, 'name' | 'ip_address' | 'notes' | 'cert_expires_on'>

export type LifecycleStatus = 'Latest' | 'Supported' | 'EOL'
// Back-compat alias kept for callers that still want a "status type" name —
// the middle SoftwareVersion layer was squashed into Software, so what used
// to be "version status" is now "software status".
export type SoftwareVersionStatus = LifecycleStatus

export interface SoftwareRelease {
  id: string
  software: string
  release_name: string
  released_on: string | null
  status: LifecycleStatus
  position: number
}

export interface Software {
  id: string
  name: string
  // The version label that used to live on a SoftwareVersion child
  // (e.g. "9.5.0") — now a field on Software itself.
  version: string
  status: LifecycleStatus
  description: string | null
  releases: SoftwareRelease[]
}

export type NeedsPatchingStatus = 'yes' | 'no' | 'unknown'

export interface BasketSoftwareEntry {
  basket: string
  software: string
  software_name: string
  // version_label / version_status are sourced from the parent Software
  // row now (Software.version / Software.status), but the field names are
  // kept stable so the SPA's existing display code keeps working.
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
  // version_label is sourced from Software.version after the squash.
  version_label: string
  software_release: string | null
  release_name: string | null
  // Per-server override: when true, this server's installed release is
  // treated as the catalog Latest for Needs Patching + Patch Execution
  // automation. Used for interim fixes that don't apply to this customer.
  functionally_latest: boolean
}

export interface PatchGroupStep {
  id: string
  patch_group: string
  step_num: number
  description: string
  est_time: string | null
  per_server: boolean
  not_timed: boolean
}

export interface PatchGroup {
  id: string
  name: string
  // Software UUIDs this group is meant to patch — drives which plans
  // (via import) end up covering which softwares.
  software_ids: string[]
  software_names: string[]
  steps: PatchGroupStep[]
}

// Plan-owned step. PatchPlanGroup is gone after the 2026-06-03 redesign —
// plans copy steps from groups at import time and own them outright.
export interface PatchPlanStep {
  id: string
  patch_plan: string
  step_num: number
  description: string
  est_time: string | null
  per_server: boolean
  not_timed: boolean
}

export interface PatchPlan {
  id: string
  name: string
  software_ids: string[]
  software_names: string[]
  plan_steps: PatchPlanStep[]
}

export type PatchExecutionStatus = 'active' | 'completed' | 'aborted'

export interface PatchExecutionStep {
  id: string
  step_num: number
  description: string
  est_time: string | null
  per_server: boolean
  not_timed: boolean
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
  // Snapshot of the plan's software names at creation time, for display.
  software_names: string[]
  organization: string
  organization_name: string
  environment: string
  environment_name: string
  status: PatchExecutionStatus
  planned_date: string | null
  patch_date: string | null
  started_at: string | null
  completed_at: string | null
  total_time: string | null
  steps: PatchExecutionStep[]
  aborts: PatchExecutionAbort[]
}

export interface PatchExecutionCheckResult {
  execution_id: string | null
  org_name: string
  env_name: string
  plan_name: string
  created: boolean
  reason: string
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
  kind: 'activity' | 'cert' | 'patch' | 'patch_planned'
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
