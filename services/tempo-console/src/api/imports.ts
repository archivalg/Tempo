import { apiRequest, apiUpload, downloadFile, newIdempotencyKey } from './client'

export interface FieldDef { name: string; type: string; required: boolean; description: string; example: string; choices?: string[] }
export interface ContractDef { data_class: string; entity: string | null; title: string; purpose: string; key: string[]; fields: FieldDef[]; batch_options: FieldDef[]; notes: string[]; limits: { max_rows_per_batch: number } }
export interface Inspect { headers: string[]; row_count: number; sample: Record<string, string>[]; suggested_mapping: Record<string, string | null>; used_saved_mapping: boolean; missing_required: string[]; fields: FieldDef[]; batch_options: FieldDef[] }
export interface Message { level: 'error' | 'warning'; field: string; code: string; text: string }
export interface Batch {
  id: string; data_class: string; entity: string | null; channel: string; source_label: string; state: 'validated' | 'applied' | 'undone' | 'rejected'; mode: string
  total_rows: number; ok_rows: number; warning_rows: number; error_rows: number; replayed: boolean; can_apply: boolean; can_undo: boolean
  created_at: string; applied_at: string | null
  summary: { blocking?: string[]; notes?: string[]; creates?: number; updates?: number; unchanged?: number; total_units?: number; incomplete_periods?: number; incomplete_sample?: string[]; shadowed?: string[]; applied?: Record<string, unknown>; applied_partial?: boolean; options?: Record<string, unknown> }
  rejected_sample?: { row: number; messages: Message[]; values: Record<string, string> }[]
}
export interface ClassStatus { data_class: string; entity: string | null; title: string; last_success_at: string | null; last_batch: string | null; last_rows: number | null; waiting_batches: number; rejected_rows: number }
export interface DataStatus {
  classes: ClassStatus[]; sites: { site_id: string; name: string; forecast_source: 'generated' | 'supplied' }[]
  authority: { site_id: string; activity: string; authority: string; reason: string }[]; forecast_versions: { site_id: string; version: string; rows: number; first: string; last: string }[]
}
export interface Step { key: string; title: string; state: 'done' | 'todo'; detail: string; link: string | null }
export interface Checklist { steps: Step[]; done: number; total: number; next: string | null; complete: boolean }
export interface Credential { id: string; name: string; prefix: string; site_ids: string[] | null; status: string; expires_at: string | null; last_used_at: string | null; secret?: string; note?: string }

const q = (o: Record<string, string | undefined>) => { const p = new URLSearchParams(); for (const [k, v] of Object.entries(o)) if (v) p.set(k, v); return p.size ? `?${p}` : '' }
export const getContracts = () => apiRequest<{ contracts: ContractDef[] }>('/imports/contracts')
export const downloadTemplate = (dc: string, entity?: string | null) => downloadFile(`/imports/contracts/${dc}/template.csv${q({ entity: entity ?? undefined })}`)
export const inspectCsv = (dc: string, entity: string | null, file: ArrayBuffer) => apiUpload<Inspect>(`/imports/csv/inspect${q({ data_class: dc, entity: entity ?? undefined })}`, file)
export const stageCsv = (dc: string, entity: string | null, file: ArrayBuffer, mapping: Record<string, string | null>, options: Record<string, string>, fileName: string, saveMapping: boolean) =>
  apiUpload<Batch>(`/imports/csv/stage${q({ data_class: dc, entity: entity ?? undefined, mapping: JSON.stringify(mapping), file_name: fileName, save_mapping: saveMapping ? 'true' : undefined, ...options })}`, file)
export const listBatches = () => apiRequest<Batch[]>('/imports/batches')
export const getBatch = (id: string) => apiRequest<Batch>(`/imports/batches/${id}`)
export const applyBatch = (id: string, acceptPartial: boolean) => apiRequest<Batch>(`/imports/batches/${id}/apply`, { method: 'POST', body: { accept_partial: acceptPartial } })
export const undoBatch = (id: string) => apiRequest<Batch>(`/imports/batches/${id}/undo`, { method: 'POST' })
export const downloadRejected = (id: string) => downloadFile(`/imports/batches/${id}/errors.csv`)
export const getDataStatus = () => apiRequest<DataStatus>('/imports/status')
export const setForecastSource = (site: string, source: 'generated' | 'supplied') => apiRequest<{ forecast_source: string }>(`/sites/${site}/forecast-source`, { method: 'PUT', body: { source } })
export const getChecklist = () => apiRequest<Checklist>('/setup/checklist')
export const listCredentials = () => apiRequest<Credential[]>('/admin/api-credentials')
export const createCredential = (name: string, siteIds: string[] | null, validDays: number) => apiRequest<Credential>('/admin/api-credentials', { method: 'POST', body: { name, site_ids: siteIds, valid_days: validDays }, idempotencyKey: newIdempotencyKey() })
export const rotateCredential = (id: string) => apiRequest<Credential>(`/admin/api-credentials/${id}/rotate`, { method: 'POST' })
export const revokeCredential = (id: string) => apiRequest<Credential>(`/admin/api-credentials/${id}/revoke`, { method: 'POST' })
