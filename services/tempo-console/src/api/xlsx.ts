import { apiUpload } from './client'
import type { Batch } from './imports'

// Mirrors app.api.v1.imports.inspect_xlsx / stage_xlsx (app/imports/xlsx.py). A workbook upload is
// multi-sheet: inspect is a read-only, no-DB-write preview of every sheet; stage ATOMICALLY stages
// AND applies every recognised sheet, in dependency order, inside one transaction — any sheet's
// failure rolls back the whole workbook (no partial import). Source-workbook compatibility with
// Arch's actual v1/v2 files is unverified; this is fixture-tested import support.
export interface XlsxSheetInspect {
  sheet: string
  recognised: boolean
  data_class?: string
  entity?: string
  headers?: string[]
  row_count: number
  sample?: Record<string, string>[]
  suggested_mapping?: Record<string, string | null>
  missing_required?: string[]
}
export interface XlsxInspect {
  sheets: XlsxSheetInspect[]
}
export interface XlsxStagedSheet {
  sheet: string
  data_class: string
  entity: string
  batch: Batch | null
  note?: string
}
export interface XlsxStageResult {
  applied: XlsxStagedSheet[]
  skipped_sheets: string[]
}

export const inspectXlsx = (file: ArrayBuffer) => apiUpload<XlsxInspect>('/imports/xlsx/inspect', file, 'application/octet-stream')
export const stageXlsx = (file: ArrayBuffer, fileName: string) =>
  apiUpload<XlsxStageResult>(`/imports/xlsx/stage?file_name=${encodeURIComponent(fileName)}`, file, 'application/octet-stream')
