# Tempo data contracts — version 1.8

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
| `position_grade` | text | no | Leave blank if grade-specific rates do not apply; otherwise matched against Grade/provider rates. | `` |
| `award` | text | no | Leave blank if no award/agreement applies; otherwise matched against Award rules for overtime. | `` |

- Rows are matched on worker_ref, so the same person is updated, not duplicated.
- An award name alone sets nothing — upload a matching Award rule for it to affect costing.

## Work standards (master data)

Seconds of labour per unit of work, per activity. Needed before forecasts and actuals can name an activity.

`data_class`: `master` · `entity`: `work_standards` · key: `activity`

| Field | Type | Required | Meaning | Example |
|---|---|---|---|---|
| `activity` | text | yes | Activity name; must already have a work standard. | `picking` |
| `seconds_per_unit` | number | yes | Standard labour seconds for one unit. | `45` |
| `effective_from` | date | no | Date the standard starts (defaults to today). | `2026-10-01` |
| `function` | text | no | Leave blank if you do not group activities by function. | `` |
| `flow` | text | no | Leave blank if you do not group activities by flow (for example inbound or outbound). | `` |
| `required_skill` | text | no | Leave blank if no particular skill/certification is required; otherwise a worker needs a current, unexpired skill of this code to be assigned. | `` |

- A changed value closes the previous standard on the day the new one starts.
- function/flow are carried through to scheduling results unchanged.
- required_skill is a qualification check, separate from any award/agreement restriction (see Award eligibility restrictions).

## Sites (master data)

Create or update your sites. Needs the configure permission because it adds places people can be rostered.

`data_class`: `master` · `entity`: `sites` · key: `site_id`

| Field | Type | Required | Meaning | Example |
|---|---|---|---|---|
| `site_id` | text | yes | Your stable ID for the site; letters, numbers, underscore or hyphen. | `syd_dc_02` |
| `name` | text | yes | Display name. | `Sydney DC` |
| `timezone` | text | yes | IANA time zone name. An existing site's time zone cannot be changed by upload. | `Australia/Sydney` |
| `operating_mode` | enum (standalone/overlay) | no | standalone (default): Tempo is the roster and attendance system. overlay: another system is. | `standalone` |

- The person uploading is given access to a new site. Give other people access in Administration.

## Customers (master data)

The customers whose work your sites handle.

`data_class`: `master` · `entity`: `customers` · key: `customer_id`

| Field | Type | Required | Meaning | Example |
|---|---|---|---|---|
| `customer_id` | text | yes | Your stable customer ID. | `cust_A` |
| `name` | text | yes | Customer name. | `Acme Retail` |
| `status` | enum (active/inactive) | no | Defaults to active. | `active` |


## Availability and leave (master data)

Times a person cannot be rostered: unavailable, leave or a rostered day off. Rows are matched to people by worker_ref from the staff upload.

`data_class`: `master` · `entity`: `availability` · key: `worker_ref`, `kind`, `from`

| Field | Type | Required | Meaning | Example |
|---|---|---|---|---|
| `worker_ref` | text | yes | The worker_ref used in the staff upload. | `E1042` |
| `kind` | enum (unavailable/leave/rdo) | yes | What kind of entry. | `leave` |
| `from` | datetime | yes | Start. ISO 8601 with offset, or site-local time. | `2026-10-12 00:00` |
| `to` | datetime | yes | End (after the start; at most 60 days). | `2026-10-16 00:00` |

- Uploading the same entry again changes nothing. Entries created by an upload can be undone as a batch.

## Labour rates (master data)

Hourly cost per employment type and role, used for planned cost. Without a rate, cost is shown as unavailable, never as zero.

`data_class`: `master` · `entity`: `rates` · key: `employment_type`, `role`

| Field | Type | Required | Meaning | Example |
|---|---|---|---|---|
| `employment_type` | enum (permanent/casual/labour_hire) | yes | How the person is engaged. | `casual` |
| `role` | text | no | Role or skill the rate applies to; blank or general applies to all roles. | `picker` |
| `hourly_rate` | number | yes | Cost per paid hour (AUD), as you want it used for planning. | `42.50` |
| `overtime_multiplier` | number | no | Overtime multiplier, for example 1.5. | `1.5` |
| `surcharge` | number | no | Extra per hour, for example an agency margin. | `8` |

- Rates are indicative planning inputs, not a pay or award calculation.

## Zones (master data)

Named areas within a site (for example PICK, PACK, STAGE) used by activity role mapping.

`data_class`: `master` · `entity`: `zones` · key: `site_id`, `zone_id`

| Field | Type | Required | Meaning | Example |
|---|---|---|---|---|
| `site` | text | yes | Site ID as shown in Tempo. | `mel_dc_01` |
| `zone_id` | text | yes | Your stable ID for the zone; letters, numbers, underscore or hyphen. | `PICK` |
| `zone_name` | text | yes | Display name. | `Picking` |


## Activity roles (master data)

Which role performs an activity in which zone, and its relative share of that activity's workload when more than one role/zone covers it.

`data_class`: `master` · `entity`: `activity_roles` · key: `site_id`, `activity`, `role`, `zone_id`

| Field | Type | Required | Meaning | Example |
|---|---|---|---|---|
| `site` | text | yes | Site ID as shown in Tempo. | `mel_dc_01` |
| `activity` | text | yes | Activity name; must already have a work standard. | `picking` |
| `role` | text | yes | Role or skill performing this activity. | `picker` |
| `zone_id` | text | yes | Zone this role works the activity in; must already exist. | `PICK` |
| `weight` | number | no | Relative share of this activity's workload for this role/zone (defaults to 1.0). Weights for the same activity are normalised, not added, so the same workload is never double-counted. | `1.0` |


## Operating calendar (master data)

A site's open hours by weekday, used to validate shift templates against real operating hours.

`data_class`: `master` · `entity`: `operating_calendar` · key: `site_id`, `weekday`

| Field | Type | Required | Meaning | Example |
|---|---|---|---|---|
| `site` | text | yes | Site ID as shown in Tempo. | `mel_dc_01` |
| `weekday` | enum (monday/tuesday/wednesday/thursday/friday/saturday/sunday) | yes | Day of the week. | `monday` |
| `is_24h` | bool | no | True if the site runs 24 hours this weekday. Cannot be combined with closed or with open/close times. | `false` |
| `is_closed` | bool | no | True if the site does not operate at all this weekday. | `false` |
| `open_time` | text | no | Opening time, 24-hour HH:MM site-local. Required unless 24-hour or closed. | `06:00` |
| `close_time` | text | no | Closing time, 24-hour HH:MM site-local. An equal open/close time is rejected — use the 24-hour or closed setting instead. | `23:00` |

- Every weekday must state 24-hour, closed, or both open_time and close_time; nothing is silently inferred.

## Shift templates (master data)

Named shifts for a site: a start/end time and which weekdays they run. An end time at or before the start time crosses midnight.

`data_class`: `master` · `entity`: `shift_templates` · key: `site_id`, `shift_code`

| Field | Type | Required | Meaning | Example |
|---|---|---|---|---|
| `site` | text | yes | Site ID as shown in Tempo. | `mel_dc_01` |
| `shift_code` | text | yes | Your stable ID for the shift. | `morning` |
| `start_time` | text | yes | Start time, 24-hour HH:MM site-local. | `06:00` |
| `end_time` | text | yes | End time, 24-hour HH:MM site-local. At or before start_time means the shift crosses midnight. | `14:00` |
| `weekdays` | list | yes | Weekdays this shift runs, separated by semicolons. | `monday;tuesday;wednesday;thursday;friday` |
| `effective_from` | date | no | Date the template starts (defaults to today). | `2026-10-01` |

- A changed start/end/weekdays for the same shift_code closes the previous template on the day the new one starts.
- A shift that falls outside the site's operating calendar for one of its weekdays is accepted with a warning, never silently changed.

## Shift breaks (master data)

Scheduled breaks within a shift template, offset from the shift's own start so overnight shifts stay unambiguous.

`data_class`: `master` · `entity`: `shift_breaks` · key: `site_id`, `shift_code`, `starts_after_minutes`, `duration_minutes`

| Field | Type | Required | Meaning | Example |
|---|---|---|---|---|
| `site` | text | yes | Site ID as shown in Tempo. | `mel_dc_01` |
| `shift_code` | text | yes | The shift_code from Shift templates. | `night` |
| `starts_after_minutes` | int | yes | Minutes after the shift's own start when the break begins. | `240` |
| `duration_minutes` | int | yes | Length of the break in minutes. | `30` |
| `is_paid` | bool | yes | Whether this break is paid. | `false` |

- A break must fit entirely inside its shift's elapsed time.

## Process templates (master data)

A named sequence of activities an order or receipt must pass through before despatch (for example pick, pack, dispatch).

`data_class`: `master` · `entity`: `process_templates` · key: `site_id`, `process_code`, `customer_id`

| Field | Type | Required | Meaning | Example |
|---|---|---|---|---|
| `site` | text | yes | Site ID as shown in Tempo. | `mel_dc_01` |
| `process_code` | text | yes | Your stable ID for this process. | `outbound_standard` |
| `customer_id` | text | no | Leave blank for the site's default process; set to override it for one customer. | `` |

- Give a customer-specific override its own process_code (for example outbound_standard_acme) rather than reusing the default's code.

## Process steps (master data)

The activities in a process template, in order. Re-uploading a step with the same sequence number updates it.

`data_class`: `master` · `entity`: `process_steps` · key: `site_id`, `process_code`, `sequence`

| Field | Type | Required | Meaning | Example |
|---|---|---|---|---|
| `site` | text | yes | Site ID as shown in Tempo. | `mel_dc_01` |
| `process_code` | text | yes | The process_code from Process templates. | `outbound_standard` |
| `sequence` | int | yes | Order this step runs in (1, 2, 3, ...). | `1` |
| `activity` | text | yes | Activity for this step; must already have a work standard. | `picking` |
| `lag_minutes` | int | no | Minimum gap after the previous step finishes before this one may start (defaults to 0). | `0` |
| `equipment_id` | text | no | Leave blank if this step needs no shared equipment; otherwise an equipment_id already set up at this site. | `` |
| `zone_id` | text | no | Leave blank if this step's output does not enter a staging zone; otherwise a zone_id already set up at this site. | `` |


## Orders (master data)

A known outbound order: when it was received, when it must be despatched, and how much work it needs.

`data_class`: `master` · `entity`: `orders` · key: `site_id`, `order_id`

| Field | Type | Required | Meaning | Example |
|---|---|---|---|---|
| `site` | text | yes | Site ID as shown in Tempo. | `mel_dc_01` |
| `order_id` | text | yes | Your stable ID for the order. | `SO-10045` |
| `customer_id` | text | no | Customer ID if this order belongs to one. | `cust_A` |
| `order_received` | datetime | yes | When the order was received. ISO 8601 with offset, or site-local time. | `2026-10-12 09:00` |
| `despatch_due` | datetime | yes | When the order must be despatched by. | `2026-10-12 13:00` |
| `units` | number | no | Quantity in units. Required unless lines is given. | `100` |
| `lines` | number | no | Quantity in lines, converted to units using a configured Unit conversion. Ignored if units is given. | `` |
| `unit` | text | no | Target unit for planning (defaults to units). | `units` |
| `process_code` | text | yes | The process_code from Process templates this order follows. | `outbound_standard` |

- despatch_due must be after order_received.
- units and lines are never added together — units is used whenever it is given.

## Worker activity rates (master data)

A person's own productivity rate for one activity, overriding the activity standard for them.

`data_class`: `master` · `entity`: `worker_activity_rates` · key: `worker_ref`, `activity`, `effective_from`

| Field | Type | Required | Meaning | Example |
|---|---|---|---|---|
| `worker_ref` | text | yes | The worker_ref used in the staff upload. | `E1042` |
| `activity` | text | yes | Activity this rate applies to; must already have a work standard. | `picking` |
| `unit` | text | no | Unit this rate is measured in (defaults to units). | `units` |
| `rate_per_hour` | number | yes | Units per hour at this activity for this person. | `280` |
| `effective_from` | date | no | Date this rate starts (defaults to today). | `2026-10-01` |

- A changed rate for the same person and activity closes the previous one on the day the new one starts.

## Unit conversions (master data)

A factor to convert one unit into another, optionally scoped to one activity.

`data_class`: `master` · `entity`: `unit_conversions` · key: `activity`, `from_unit`, `to_unit`

| Field | Type | Required | Meaning | Example |
|---|---|---|---|---|
| `activity` | text | no | Leave blank for a global conversion, or name the activity this conversion is specific to. | `` |
| `from_unit` | text | yes | Unit you are converting from. | `lines` |
| `to_unit` | text | yes | Unit you are converting to. | `units` |
| `factor` | number | yes | Multiply a from_unit quantity by this to get to_unit (for example 10 lines x 3.2 = 32 units). | `3.2` |

- An activity-specific conversion is used ahead of a global one for the same from_unit/to_unit pair.

## Fill priorities (master data)

The order to fill labour gaps when not everything can be covered. Lower numbers fill first; equal numbers are equal priority.

`data_class`: `master` · `entity`: `fill_priorities` · key: `scope`, `value`

| Field | Type | Required | Meaning | Example |
|---|---|---|---|---|
| `scope` | enum (activity/employment_type) | yes | What kind of thing this priority applies to. 'customer' is not yet supported and is rejected, not silently accepted. | `activity` |
| `value` | text | yes | The specific activity or employment type this priority applies to. | `picking` |
| `priority` | int | yes | Lower fills first. Equal values are equal priority — never inferred as ranked. | `1` |

- Customer-scoped fill priority is explicitly out of scope for this release — upload rejects it rather than accepting an inert row.

## Absenteeism (master data)

Expected absence rate for a site, optionally narrowed by activity, weekday and shift. The most specific match is used; leave a field blank to make a rule broader.

`data_class`: `master` · `entity`: `absenteeism` · key: `site_id`, `activity`, `weekday`, `shift_code`

| Field | Type | Required | Meaning | Example |
|---|---|---|---|---|
| `site` | text | yes | Site ID as shown in Tempo. | `mel_dc_01` |
| `activity` | text | no | Leave blank to apply to every activity. | `` |
| `weekday` | enum (/monday/tuesday/wednesday/thursday/friday/saturday/sunday) | no | Leave blank to apply to every weekday. | `` |
| `shift_code` | text | no | Leave blank to apply to every shift. | `` |
| `absence_pct` | number | yes | Expected absence rate as a percentage (10 means 10%). | `10` |

- Scheduled hours = productive hours / (1 - absence rate); a 10% rate needs about 11.11% extra scheduled capacity.

## Equipment (master data)

A shared pool of equipment units at a site (for example high-reach trucks), limiting how many activities needing it can run at once.

`data_class`: `master` · `entity`: `equipment` · key: `site_id`, `equipment_id`

| Field | Type | Required | Meaning | Example |
|---|---|---|---|---|
| `site` | text | yes | Site ID as shown in Tempo. | `mel_dc_01` |
| `equipment_id` | text | yes | Your stable ID for this equipment pool. | `HIGH_REACH` |
| `description` | text | yes | Display name. | `High-reach forklift` |
| `quantity_available` | int | yes | How many units of this equipment exist at the site. | `3` |


## Headcount limits (master data)

Minimum and maximum people allowed on one activity at once, optionally for one shift.

`data_class`: `master` · `entity`: `headcount_limits` · key: `site_id`, `activity`, `shift_code`

| Field | Type | Required | Meaning | Example |
|---|---|---|---|---|
| `site` | text | yes | Site ID as shown in Tempo. | `mel_dc_01` |
| `activity` | text | yes | Activity this limit applies to; must already have a work standard. | `picking` |
| `shift_code` | text | no | Leave blank to apply across every shift. | `` |
| `min_headcount` | int | yes | Minimum people required when this activity runs at all. | `1` |
| `max_headcount` | int | yes | Maximum people allowed at once. | `6` |

- A minimum above the maximum is rejected, not silently accepted.

## Grade/provider rates (master data)

An hourly rate narrowed to one position grade or labour provider, for when the general employment-type/role rate is not specific enough.

`data_class`: `master` · `entity`: `grade_rates` · key: `employment_type`, `role`, `position_grade`, `provider_id`, `effective_from`

| Field | Type | Required | Meaning | Example |
|---|---|---|---|---|
| `employment_type` | enum (permanent/casual/labour_hire) | yes | How the person is engaged. | `labour_hire` |
| `role` | text | yes | Role or skill the rate applies to. | `picker` |
| `position_grade` | text | no | Leave blank to apply regardless of grade. | `` |
| `provider_id` | text | no | Leave blank to apply regardless of labour provider; otherwise must be a provider already on file. | `` |
| `hourly_rate` | number | yes | Cost per paid hour, as you want it used for planning. | `48.00` |
| `overtime_multiplier` | number | no | Overtime multiplier, for example 1.5. | `1.5` |
| `surcharge` | number | no | Extra per hour, for example an agency margin. | `8` |
| `currency` | text | no | Defaults to AUD. | `AUD` |
| `effective_from` | date | no | Date this rate starts (defaults to today). | `2026-10-01` |
| `effective_to` | date | no | Date this rate stops applying, if known. | `` |

- A grade- or provider-specific rate is used ahead of the general employment-type/role rate.
- Award names are identifiers here, not an award-compliance calculation.

## Productivity loss (master data)

An explicit congestion rate reduction or off-task hours reduction, for a site and optionally one activity/weekday/shift. Never a crowding curve.

`data_class`: `master` · `entity`: `productivity_loss` · key: `site_id`, `type`, `activity`, `weekday`, `shift_code`

| Field | Type | Required | Meaning | Example |
|---|---|---|---|---|
| `site` | text | yes | Site ID as shown in Tempo. | `mel_dc_01` |
| `type` | enum (congestion/off_task) | yes | congestion reduces the rate; off_task reduces available hours. | `congestion` |
| `activity` | text | no | Leave blank to apply to every activity. | `` |
| `weekday` | enum (/monday/tuesday/wednesday/thursday/friday/saturday/sunday) | no | Leave blank to apply to every weekday. | `` |
| `shift_code` | text | no | Leave blank to apply to every shift. | `` |
| `percent_loss` | number | no | Required for type congestion: percentage rate reduction (10 means 10%). | `10` |
| `off_task_hours` | number | no | Required for type off_task: hours removed from availability. | `` |

- Give exactly one of percent_loss (congestion) or off_task_hours (off_task), never both.

## Staging capacity (master data)

Maximum concurrent occupancy for a zone, in an explicit unit (for example pallets). Zone must already exist.

`data_class`: `master` · `entity`: `staging_capacity` · key: `site_id`, `zone_id`

| Field | Type | Required | Meaning | Example |
|---|---|---|---|---|
| `site` | text | yes | Site ID as shown in Tempo. | `mel_dc_01` |
| `zone_id` | text | yes | Zone this capacity applies to; must already exist. | `STAGE` |
| `capacity` | number | yes | Maximum concurrent occupancy. | `120` |
| `unit` | text | yes | Unit capacity and every movement for this zone must share (for example pallets). | `pallets` |

- A movement in a different unit than the zone's capacity is rejected, never guess-converted.

## Staging movements (master data)

Arrivals, departures and initial occupancy for a staging zone, used to check against its capacity.

`data_class`: `master` · `entity`: `staging_movements` · key: `site_id`, `zone_id`, `occurred_at`, `movement_type`

| Field | Type | Required | Meaning | Example |
|---|---|---|---|---|
| `site` | text | yes | Site ID as shown in Tempo. | `mel_dc_01` |
| `zone_id` | text | yes | Zone this movement applies to; must already have a Staging capacity row. | `STAGE` |
| `occurred_at` | datetime | yes | When this movement happened. ISO 8601 with offset, or site-local time. | `2026-10-12 06:00` |
| `movement_type` | enum (initial/arrival/departure) | yes | initial occupancy, an arrival, or a departure. | `arrival` |
| `quantity` | number | yes | Quantity moved, in the zone's capacity unit. | `20` |
| `unit` | text | yes | Must match the zone's Staging capacity unit exactly. | `pallets` |


## Indirect headcount (master data)

A fixed headcount required for a role at a site/weekday/time window, independent of direct-work volume (supervisors, inventory control, etc.).

`data_class`: `master` · `entity`: `indirect_headcount` · key: `site_id`, `role`, `weekday`, `start_time`, `end_time`

| Field | Type | Required | Meaning | Example |
|---|---|---|---|---|
| `site` | text | yes | Site ID as shown in Tempo. | `mel_dc_01` |
| `role` | text | yes | Role required; matched against a worker's skills/certifications. | `supervisor` |
| `weekday` | enum (monday/tuesday/wednesday/thursday/friday/saturday/sunday) | yes | Day of the week. | `monday` |
| `start_time` | text | yes | Start time, 24-hour HH:MM site-local. | `06:00` |
| `end_time` | text | yes | End time, 24-hour HH:MM site-local. | `14:00` |
| `headcount` | int | yes | Number of people required, regardless of demand that day. | `3` |

- Required even on a zero-volume day — indirect coverage is not derived from workload.

## Weekly availability pattern (master data)

A person's recurring default availability for one weekday, and the earliest/latest time they can work it. A dated leave/unavailable entry (Availability) always overrides this for that specific date.

`data_class`: `master` · `entity`: `weekly_availability` · key: `worker_ref`, `weekday`

| Field | Type | Required | Meaning | Example |
|---|---|---|---|---|
| `worker_ref` | text | yes | The worker_ref used in the staff upload. | `E1042` |
| `weekday` | enum (monday/tuesday/wednesday/thursday/friday/saturday/sunday) | yes | Day of the week. | `monday` |
| `available` | bool | no | Defaults to true. False means unavailable this weekday regardless of times. | `true` |
| `earliest_start` | text | no | Earliest time this person can start, 24-hour HH:MM. Leave blank with latest_finish for no window (available all day). | `06:00` |
| `latest_finish` | text | no | Latest time this person can finish, 24-hour HH:MM. At or before earliest_start crosses midnight (an overnight window). | `14:00` |

- A dated Availability entry (leave, unavailable, rdo) always overrides this pattern for that date.
- Give both earliest_start and latest_finish, or neither — one without the other is rejected.

## Day rates (master data)

An activity's standard rate for one weekday, ranking above the plain activity standard for anyone without a personal rate.

`data_class`: `master` · `entity`: `day_rates` · key: `activity`, `weekday`

| Field | Type | Required | Meaning | Example |
|---|---|---|---|---|
| `activity` | text | yes | Activity name; must already have a work standard. | `picking` |
| `weekday` | enum (monday/tuesday/wednesday/thursday/friday/saturday/sunday) | yes | Day of the week. | `monday` |
| `rate_per_hour` | number | yes | Units per hour on this weekday. | `90` |

- Used only when a worker has no personal activity rate for that activity.

## Award rules (master data)

The actual ordinary-hours and overtime numbers behind an award/agreement name — an award name alone is never a complete rule.

`data_class`: `master` · `entity`: `award_rules` · key: `award_code`

| Field | Type | Required | Meaning | Example |
|---|---|---|---|---|
| `award_code` | text | yes | The award/agreement identifier used on Staff uploads. | `retail_award_2024` |
| `ordinary_hours_per_day` | number | yes | Hours per day before overtime applies. | `8` |
| `overtime_multiplier` | number | yes | Multiplier applied to hours beyond ordinary_hours_per_day. | `1.5` |


## Award eligibility restrictions (master data)

An EXPLICIT statement that workers under an award/agreement may not perform an activity. Nothing is inferred from the award's name — only rows uploaded here restrict anything.

`data_class`: `master` · `entity`: `award_eligibility_restrictions` · key: `award_code`, `activity`

| Field | Type | Required | Meaning | Example |
|---|---|---|---|---|
| `award_code` | text | yes | The award/agreement identifier used on Staff uploads. | `retail_award_2024` |
| `activity` | text | yes | Activity name; must already have a work standard. | `picking` |

- An award with no row here restricts nothing — eligibility otherwise follows skills/certifications and activity rates as usual.

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
