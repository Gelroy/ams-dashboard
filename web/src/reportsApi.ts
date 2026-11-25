/** Client for the monthly-report endpoints (/api/reports, /api/report-templates,
 *  /api/report-metrics, /api/report-metrics-keys). Months travel as "YYYY-MM". */
import { request, requestBlob } from './api'

export interface ReportSection {
  key?: string
  title: string
  body: string
}

export interface ReportTemplate {
  id: string
  name: string
  description: string
  report_title: string
  sections: ReportSection[]
  is_default: boolean
  updated_by_email: string
  updated_at: string
}

export type ReportTemplateDraft = Pick<
  ReportTemplate,
  'name' | 'description' | 'report_title' | 'sections' | 'is_default'
>

export type ReportStatus = 'draft' | 'approved'

export interface ReportIssue {
  level: 'blocker' | 'warning'
  section: string
  message: string
}

export interface ReportNotification {
  id: string
  email: string
  status: 'sent' | 'logged' | 'failed'
  detail: string
  created_at: string
}

export interface Report {
  id: string
  organization: string
  organization_name: string
  period: string
  period_label: string
  title: string
  status: ReportStatus
  template: string | null
  template_name: string
  generated_at: string
  created_by_email: string
  approved_at: string | null
  approved_by_email: string
  sections: ReportSection[]
  issues: ReportIssue[]
  recipients: string[]
  notifications: ReportNotification[]
  ai_summary: { model: string; generated_at: string; requested_by: string } | null
  can_write_ai_summary: boolean
  pdf_size: number | null
}

export interface OverviewRow {
  organization: string
  organization_name: string
  ams_level: string | null
  metrics_received: boolean
  tickets_synced: boolean
  tickets_count: number | null
  portal_users: number
  report_recipients: number
  report: {
    id: string
    status: ReportStatus
    generated_at: string
    approved_at: string | null
  } | null
}

export interface Overview {
  period: string
  period_label: string
  rows: OverviewRow[]
}

export interface TagReference {
  tags: { tag: string; description: string }[]
  metrics_paths: string[]
  metrics_sample_period: string | null
}

const json = (method: string, body?: unknown): RequestInit => ({
  method,
  body: body === undefined ? undefined : JSON.stringify(body),
})

// ── Reports ─────────────────────────────────────────────────────────
export const getOverview = (period: string) =>
  request<Overview>(`/reports/overview/?period=${encodeURIComponent(period)}`)

export const generateReport = (organization: string, period: string) =>
  request<Report>('/reports/', json('POST', { organization, period }))

export const generateAllReports = (period: string) =>
  request<{ created: number; skipped: number }>('/reports/generate-all/', json('POST', { period }))

export const getReport = (id: string) => request<Report>(`/reports/${id}/`)

export const saveReport = (id: string, patch: { title: string; sections: ReportSection[] }) =>
  request<Report>(`/reports/${id}/`, json('PATCH', patch))

export const regenerateReport = (id: string) =>
  request<Report>(`/reports/${id}/regenerate/`, json('POST', {}))

/** Can take half a minute: the AI service is called while the request waits. */
export const writeAiSummary = (id: string) =>
  request<Report>(`/reports/${id}/ai-summary/`, json('POST', {}))

export const approveReport = (id: string) =>
  request<Report>(`/reports/${id}/approve/`, json('POST', {}))

export const notifyReport = (id: string) =>
  request<Report>(`/reports/${id}/notify/`, json('POST', {}))

export const deleteReport = (id: string) => request<void>(`/reports/${id}/`, json('DELETE'))

export const getReportPdf = (id: string) => requestBlob(`/reports/${id}/pdf/`)

// ── Metrics ─────────────────────────────────────────────────────────
export const deliverMetrics = (organization: string, period: string, payload: unknown) =>
  request<{ id: string }>('/report-metrics/', json('POST', { organization, period, payload }))

// ── Delivery keys (unattended metrics delivery) ─────────────────────
export interface MetricsKey {
  id: string
  name: string
  prefix: string
  created_by_email: string
  created_at: string
  last_used_at: string | null
  revoked_at: string | null
  revoked_by_email: string
}

export const listMetricsKeys = () => request<MetricsKey[]>('/report-metrics-keys/')

/** The only response that ever contains the key itself. */
export const createMetricsKey = (name: string) =>
  request<MetricsKey & { key: string }>('/report-metrics-keys/', json('POST', { name }))

export const revokeMetricsKey = (id: string) =>
  request<void>(`/report-metrics-keys/${id}/`, json('DELETE'))

// ── Templates ───────────────────────────────────────────────────────
export const listTemplates = () => request<ReportTemplate[]>('/report-templates/')

export const createTemplate = (t: ReportTemplateDraft) =>
  request<ReportTemplate>('/report-templates/', json('POST', t))

export const updateTemplate = (id: string, t: ReportTemplateDraft) =>
  request<ReportTemplate>(`/report-templates/${id}/`, json('PUT', t))

export const deleteTemplate = (id: string) =>
  request<void>(`/report-templates/${id}/`, json('DELETE'))

export const getTagReference = () => request<TagReference>('/report-templates/tags/')

export const previewTemplate = (body: {
  organization: string
  period: string
  report_title: string
  sections: ReportSection[]
}) => requestBlob('/report-templates/preview/', json('POST', body))

// ── Helpers ─────────────────────────────────────────────────────────
/** Show a PDF blob in a new tab. The tab must be opened synchronously in
 *  the click handler (before the fetch) or the browser blocks it. */
export function openPdfWhenReady(pdf: Promise<Blob>): Promise<void> {
  const tab = window.open('', '_blank')
  return pdf.then(
    (blob) => {
      const url = URL.createObjectURL(blob)
      if (tab) tab.location.href = url
      else window.location.href = url
      window.setTimeout(() => URL.revokeObjectURL(url), 60_000)
    },
    (e: unknown) => {
      tab?.close()
      throw e
    },
  )
}

/** "2026-10" for the month before today — reports cover the month just ended. */
export function previousMonth(): string {
  const d = new Date()
  d.setDate(1)
  d.setMonth(d.getMonth() - 1)
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`
}
