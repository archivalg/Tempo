# Tempo data contracts — version 1.0

Generated from the validators' own definitions. Four data classes can be loaded by CSV upload (Data → Load data) or by API (`POST /v1/imports/batches`).
Limits: 20,000 rows per batch. Times are ISO 8601 with an offset, or site-local `YYYY-MM-DD HH:MM` (a local time that does not exist or happens twice is refused with instructions).

Rules that apply to every class: nothing changes until a batch is applied; the same content or the same `Idempotency-Key` is never applied twice; rejected rows are reported with reasons and can be downloaded; accepted rows can be applied on their own only by choice; workload is counted from one kind (events or totals) per site and activity.

## Staff (master data)

Create or update workers. Re-uploading the same file changes nothing.

`data_class`: `master` · `entity`: `workers` · key: `worker_ref`

| Field | Type | Required | Meaning | Example |
|---|---|---|---|---|
| `worker_ref` | text | yes | Your stable ID for the person (payroll or HR number). Never reused for someone else. | `E1042` |
| `name` | text | yes | Full name. Treated as personal information. | `Sam Taylor` |
| `site` | text | yes | Site ID as shown in Tempo. | `mel_dc_01` |
| `employment_type` | enum (permanent/casual/labour_hire) | yes | How the person is engaged. | `casual` |
| `status` | enum (active/inactive) | no | Defaults to active. Use inactive for people who have left (history is kept). | `active` |
| `skills` | list | no | Skills or certifications, separated by semicolons. Listed skills are added; none are removed. | `picker;forklift` |
| `employee_no` | text | no | Payroll number if different from worker_ref. | `104233` |

- Rows are matched on worker_ref, so the same person is updated, not duplicated.

## Work standards (master data)

Seconds of labour per unit of work, per activity. Needed before forecasts and actuals can name an activity.

`data_class`: `master` · `entity`: `work_standards` · key: `activity`

| Field | Type | Required | Meaning | Example |
|---|---|---|---|---|
| `activity` | text | yes | Activity name; must already have a work standard. | `picking` |
| `seconds_per_unit` | number | yes | Standard labour seconds for one unit. | `45` |
| `effective_from` | date | no | Date the standard starts (defaults to today). | `2026-10-01` |

- A changed value closes the previous standard on the day the new one starts.

## Forecast workload

Expected units per activity and period. Customer-supplied forecasts are versioned and shown with their origin.

`data_class`: `forecast` · key: `site`, `activity`, `period_start`, `grain`

| Field | Type | Required | Meaning | Example |
|---|---|---|---|---|
| `site` | text | yes | Site ID as shown in Tempo. | `mel_dc_01` |
| `activity` | text | yes | Activity name; must already have a work standard. | `picking` |
| `period_start` | datetime | yes | Start of the period. ISO 8601 with offset (2026-10-05T00:00:00+11:00) or site-local time (2026-10-05 00:00). Hours start on the hour; days at local midnight. | `2026-10-05` |
| `grain` | enum (hour/day) | yes | Length of the period. | `day` |
| `units` | number | yes | Expected units in the period. | `26500` |
| `lower` | number | no | Optional low estimate. | `24000` |
| `upper` | number | no | Optional high estimate. | `29000` |

Batch options (sent once, not per row):

| Option | Type | Required | Meaning |
|---|---|---|---|
| `forecast_version` | text | yes | A label for this forecast (for example 2026-10-W2-v1). A label can be used once. |
| `generated_at` | datetime | no | When the customer produced the forecast. |

- A revised forecast flags draft rosters for review. It never rewrites a published roster.

## Workload events (actuals, one row per event)

Individual operational events: what was processed, when.

`data_class`: `transactions` · key: `source`, `event_id`

| Field | Type | Required | Meaning | Example |
|---|---|---|---|---|
| `event_id` | text | yes | Your unique ID for the event. Resending the same event changes nothing. | `RCV-88231` |
| `site` | text | yes | Site ID as shown in Tempo. | `mel_dc_01` |
| `activity` | text | yes | Activity name; must already have a work standard. | `picking` |
| `occurred_at` | datetime | yes | When it happened. ISO 8601 with offset, or site-local time. | `2026-09-28 14:32` |
| `quantity` | number | yes | Units processed (not negative). | `12` |
| `unit` | text | no | Unit label (defaults to units). All rows for an activity must use one unit. | `units` |
| `customer` | text | no | Customer ID if you track workload per customer. | `cust_A` |
| `action` | enum (create/correct/cancel) | no | create (default), correct or cancel. | `create` |
| `revision` | int | no | Increasing number for corrections. A lower revision than the one held is ignored as out of date. | `2` |
| `source` | text | no | Name of the sending system (defaults to default). Event IDs are unique per source. | `wms` |

- Events feed hourly workload actuals. If bulk totals are authoritative for the same site and activity, events are stored but not counted.

## Workload totals (actuals, per period)

Hourly or daily totals when individual events are not available.

`data_class`: `bulk` · key: `site`, `activity`, `period_start`, `grain`

| Field | Type | Required | Meaning | Example |
|---|---|---|---|---|
| `site` | text | yes | Site ID as shown in Tempo. | `mel_dc_01` |
| `activity` | text | yes | Activity name; must already have a work standard. | `picking` |
| `period_start` | datetime | yes | Start of the period. ISO 8601 with offset (2026-10-05T00:00:00+11:00) or site-local time (2026-10-05 00:00). Hours start on the hour; days at local midnight. | `2026-10-05` |
| `grain` | enum (hour/day) | yes | Length of the period. | `day` |
| `units` | number | yes | Total units processed in the period (not negative). | `26140` |
| `customer` | text | no | Customer ID if you track workload per customer. | `cust_A` |

Batch options (sent once, not per row):

| Option | Type | Required | Meaning |
|---|---|---|---|
| `mode` | enum (upsert/replace_slice) | yes | upsert: add or update these periods only. replace_slice: replace everything in the stated date range for the activities in the file. |
| `slice_start` | date | no | First local date of the slice (required for replace_slice). |
| `slice_end` | date | no | Last local date of the slice, inclusive (required for replace_slice). |
| `control_total` | number | no | Optional total of units you expect; the import is held if the file does not add up to it. |
| `take_over` | bool | no | Allow this upload to replace workload that came from a different source for the same periods. |

- Replacing a slice needs its range stated; an ambiguous replacement is refused.
