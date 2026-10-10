"""Versioned data contracts for the four data classes (roadmap M1). One definition drives the CSV template, the API reference,
the column mapping and the validators, so they cannot drift apart. Breaking changes need a new CONTRACT_VERSION."""
from __future__ import annotations

import csv
import io
from dataclasses import dataclass, field

CONTRACT_VERSION = "1.8"  # 1.8 adds award_eligibility_restrictions, required_skill on work_standards, open-order backlog (additive; earlier contracts are unchanged)
MAX_ROWS = 20_000          # synchronous limit; larger files must be split (a background worker does not exist yet)
MAX_BYTES = 8 * 1024 * 1024


@dataclass(frozen=True)
class Field:
    name: str
    kind: str                       # text | enum | number | int | datetime | date | list
    required: bool
    description: str
    example: str
    choices: tuple[str, ...] = ()
    synonyms: tuple[str, ...] = ()  # header names we recognise automatically


@dataclass(frozen=True)
class Contract:
    data_class: str
    entity: str | None
    title: str
    purpose: str
    key: tuple[str, ...]
    fields: tuple[Field, ...]
    batch_options: tuple[Field, ...] = ()
    notes: tuple[str, ...] = ()

    @property
    def names(self) -> list[str]:
        return [f.name for f in self.fields]


SITE = Field("site", "text", True, "Site ID as shown in Tempo.", "mel_dc_01", synonyms=("site_id", "location", "warehouse", "dc"))
ACTIVITY = Field("activity", "text", True, "Activity name; must already have a work standard.", "picking", synonyms=("task", "work_type", "function"))
GRAIN = Field("grain", "enum", True, "Length of the period.", "day", ("hour", "day"), ("period", "granularity"))
PERIOD_START = Field("period_start", "datetime", True, "Start of the period. ISO 8601 with offset (2026-10-05T00:00:00+11:00) or site-local time (2026-10-05 00:00). Hours start on the hour; days at local midnight.", "2026-10-05",
                     synonyms=("start", "date", "period", "from", "datetime"))

CONTRACTS: dict[tuple[str, str | None], Contract] = {(c.data_class, c.entity): c for c in (
    Contract("master", "workers", "Staff (master data)", "Create or update workers. Re-uploading the same file changes nothing.", ("worker_ref",), (
        Field("worker_ref", "text", True, "Your stable ID for the person (payroll or HR number). Never reused for someone else.", "E1042", synonyms=("employee_id", "staff_id", "id", "worker_id", "emp_no")),
        Field("name", "text", True, "Full name. Treated as personal information.", "Sam Taylor", synonyms=("full_name", "employee_name", "worker_name")),
        SITE,
        Field("employment_type", "enum", True, "How the person is engaged.", "casual", ("permanent", "casual", "labour_hire"), ("type", "employment", "contract_type")),
        Field("status", "enum", False, "Defaults to active. Use inactive for people who have left (history is kept).", "active", ("active", "inactive"), ("active_flag",)),
        Field("skills", "list", False, "Skills or certifications, separated by semicolons. Listed skills are added; none are removed.", "picker;forklift", synonyms=("roles", "certifications", "licences")),
        Field("employee_no", "text", False, "Payroll number if different from worker_ref.", "104233", synonyms=("payroll_no", "payroll_number")),
        Field("position_grade", "text", False, "Leave blank if grade-specific rates do not apply; otherwise matched against Grade/provider rates.", "", synonyms=("grade",)),
        Field("award", "text", False, "Leave blank if no award/agreement applies; otherwise matched against Award rules for overtime.", "", synonyms=("agreement",)),
    ), notes=("Rows are matched on worker_ref, so the same person is updated, not duplicated.", "An award name alone sets nothing — upload a matching Award rule for it to affect costing.")),
    Contract("master", "work_standards", "Work standards (master data)", "Seconds of labour per unit of work, per activity. Needed before forecasts and actuals can name an activity.", ("activity",), (
        ACTIVITY,
        Field("seconds_per_unit", "number", True, "Standard labour seconds for one unit.", "45", synonyms=("seconds", "sec_per_unit", "time_per_unit", "standard")),
        Field("effective_from", "date", False, "Date the standard starts (defaults to today).", "2026-10-01", synonyms=("start_date", "from")),
        Field("function", "text", False, "Leave blank if you do not group activities by function.", "", synonyms=("process_function",)),
        Field("flow", "text", False, "Leave blank if you do not group activities by flow (for example inbound or outbound).", "", synonyms=("process_flow", "direction")),
        Field("required_skill", "text", False, "Leave blank if no particular skill/certification is required; otherwise a worker needs a current, unexpired skill of this code to be assigned.", "", synonyms=("skill", "required_certification")),
    ), notes=("A changed value closes the previous standard on the day the new one starts.", "function/flow are carried through to scheduling results unchanged.",
              "required_skill is a qualification check, separate from any award/agreement restriction (see Award eligibility restrictions).")),
    Contract("master", "sites", "Sites (master data)", "Create or update your sites. Needs the configure permission because it adds places people can be rostered.", ("site_id",), (
        Field("site_id", "text", True, "Your stable ID for the site; letters, numbers, underscore or hyphen.", "syd_dc_02", synonyms=("site", "id", "code", "site_code")),
        Field("name", "text", True, "Display name.", "Sydney DC", synonyms=("site_name", "warehouse")),
        Field("timezone", "text", True, "IANA time zone name. An existing site's time zone cannot be changed by upload.", "Australia/Sydney", synonyms=("time_zone", "tz")),
        Field("operating_mode", "enum", False, "standalone (default): Tempo is the roster and attendance system. overlay: another system is.", "standalone", ("standalone", "overlay"), ("mode",)),
    ), notes=("The person uploading is given access to a new site. Give other people access in Administration.",)),
    Contract("master", "customers", "Customers (master data)", "The customers whose work your sites handle.", ("customer_id",), (
        Field("customer_id", "text", True, "Your stable customer ID.", "cust_A", synonyms=("customer", "id", "code", "account")),
        Field("name", "text", True, "Customer name.", "Acme Retail", synonyms=("customer_name",)),
        Field("status", "enum", False, "Defaults to active.", "active", ("active", "inactive")),
    )),
    Contract("master", "availability", "Availability and leave (master data)", "Times a person cannot be rostered: unavailable, leave or a rostered day off. Rows are matched to people by worker_ref from the staff upload.", ("worker_ref", "kind", "from"), (
        Field("worker_ref", "text", True, "The worker_ref used in the staff upload.", "E1042", synonyms=("employee_id", "staff_id", "id", "worker_id")),
        Field("kind", "enum", True, "What kind of entry.", "leave", ("unavailable", "leave", "rdo"), ("type", "status")),
        Field("from", "datetime", True, "Start. ISO 8601 with offset, or site-local time.", "2026-10-12 00:00", synonyms=("start", "start_at", "from_date")),
        Field("to", "datetime", True, "End (after the start; at most 60 days).", "2026-10-16 00:00", synonyms=("end", "end_at", "to_date")),
    ), notes=("Uploading the same entry again changes nothing. Entries created by an upload can be undone as a batch.",)),
    Contract("master", "rates", "Labour rates (master data)", "Hourly cost per employment type and role, used for planned cost. Without a rate, cost is shown as unavailable, never as zero.", ("employment_type", "role"), (
        Field("employment_type", "enum", True, "How the person is engaged.", "casual", ("permanent", "casual", "labour_hire"), ("type", "labour_type")),
        Field("role", "text", False, "Role or skill the rate applies to; blank or general applies to all roles.", "picker", synonyms=("skill", "position")),
        Field("hourly_rate", "number", True, "Cost per paid hour (AUD), as you want it used for planning.", "42.50", synonyms=("rate", "cost_per_hour", "hourly")),
        Field("overtime_multiplier", "number", False, "Overtime multiplier, for example 1.5.", "1.5", synonyms=("overtime", "ot_multiplier")),
        Field("surcharge", "number", False, "Extra per hour, for example an agency margin.", "8", synonyms=("agency_surcharge", "margin")),
    ), notes=("Rates are indicative planning inputs, not a pay or award calculation.",)),
    Contract("master", "zones", "Zones (master data)", "Named areas within a site (for example PICK, PACK, STAGE) used by activity role mapping.", ("site_id", "zone_id"), (
        SITE,
        Field("zone_id", "text", True, "Your stable ID for the zone; letters, numbers, underscore or hyphen.", "PICK", synonyms=("zone", "code", "zone_code")),
        Field("zone_name", "text", True, "Display name.", "Picking", synonyms=("name",)),
    )),
    Contract("master", "activity_roles", "Activity roles (master data)", "Which role performs an activity in which zone, and its relative share of that activity's workload when more than one role/zone covers it.", ("site_id", "activity", "role", "zone_id"), (
        SITE, ACTIVITY,
        Field("role", "text", True, "Role or skill performing this activity.", "picker", synonyms=("skill", "position")),
        Field("zone_id", "text", True, "Zone this role works the activity in; must already exist.", "PICK", synonyms=("zone",)),
        Field("weight", "number", False, "Relative share of this activity's workload for this role/zone (defaults to 1.0). Weights for the same activity are normalised, not added, so the same workload is never double-counted.", "1.0", synonyms=("share",)),
    )),
    Contract("master", "operating_calendar", "Operating calendar (master data)", "A site's open hours by weekday, used to validate shift templates against real operating hours.", ("site_id", "weekday"), (
        SITE,
        Field("weekday", "enum", True, "Day of the week.", "monday", ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")),
        Field("is_24h", "bool", False, "True if the site runs 24 hours this weekday. Cannot be combined with closed or with open/close times.", "false"),
        Field("is_closed", "bool", False, "True if the site does not operate at all this weekday.", "false"),
        Field("open_time", "text", False, "Opening time, 24-hour HH:MM site-local. Required unless 24-hour or closed.", "06:00"),
        Field("close_time", "text", False, "Closing time, 24-hour HH:MM site-local. An equal open/close time is rejected — use the 24-hour or closed setting instead.", "23:00"),
    ), notes=("Every weekday must state 24-hour, closed, or both open_time and close_time; nothing is silently inferred.",)),
    Contract("master", "shift_templates", "Shift templates (master data)", "Named shifts for a site: a start/end time and which weekdays they run. An end time at or before the start time crosses midnight.", ("site_id", "shift_code"), (
        SITE,
        Field("shift_code", "text", True, "Your stable ID for the shift.", "morning", synonyms=("shift", "code")),
        Field("start_time", "text", True, "Start time, 24-hour HH:MM site-local.", "06:00"),
        Field("end_time", "text", True, "End time, 24-hour HH:MM site-local. At or before start_time means the shift crosses midnight.", "14:00"),
        Field("weekdays", "list", True, "Weekdays this shift runs, separated by semicolons.", "monday;tuesday;wednesday;thursday;friday", synonyms=("days",)),
        Field("effective_from", "date", False, "Date the template starts (defaults to today).", "2026-10-01", synonyms=("start_date", "from")),
    ), notes=("A changed start/end/weekdays for the same shift_code closes the previous template on the day the new one starts.", "A shift that falls outside the site's operating calendar for one of its weekdays is accepted with a warning, never silently changed.")),
    Contract("master", "shift_breaks", "Shift breaks (master data)", "Scheduled breaks within a shift template, offset from the shift's own start so overnight shifts stay unambiguous.", ("site_id", "shift_code", "starts_after_minutes", "duration_minutes"), (
        SITE,
        Field("shift_code", "text", True, "The shift_code from Shift templates.", "night", synonyms=("shift",)),
        Field("starts_after_minutes", "int", True, "Minutes after the shift's own start when the break begins.", "240", synonyms=("offset_minutes",)),
        Field("duration_minutes", "int", True, "Length of the break in minutes.", "30"),
        Field("is_paid", "bool", True, "Whether this break is paid.", "false"),
    ), notes=("A break must fit entirely inside its shift's elapsed time.",)),
    Contract("master", "process_templates", "Process templates (master data)", "A named sequence of activities an order or receipt must pass through before despatch (for example pick, pack, dispatch).", ("site_id", "process_code", "customer_id"), (
        SITE,
        Field("process_code", "text", True, "Your stable ID for this process.", "outbound_standard", synonyms=("process", "code")),
        Field("customer_id", "text", False, "Leave blank for the site's default process; set to override it for one customer.", "", synonyms=("customer",)),
    ), notes=("Give a customer-specific override its own process_code (for example outbound_standard_acme) rather than reusing the default's code.",)),
    Contract("master", "process_steps", "Process steps (master data)", "The activities in a process template, in order. Re-uploading a step with the same sequence number updates it.", ("site_id", "process_code", "sequence"), (
        SITE,
        Field("process_code", "text", True, "The process_code from Process templates.", "outbound_standard", synonyms=("process",)),
        Field("sequence", "int", True, "Order this step runs in (1, 2, 3, ...).", "1", synonyms=("step", "order")),
        Field("activity", "text", True, "Activity for this step; must already have a work standard.", "picking", synonyms=("task",)),
        Field("lag_minutes", "int", False, "Minimum gap after the previous step finishes before this one may start (defaults to 0).", "0", synonyms=("lag",)),
        Field("equipment_id", "text", False, "Leave blank if this step needs no shared equipment; otherwise an equipment_id already set up at this site.", "", synonyms=("equipment",)),
        Field("zone_id", "text", False, "Leave blank if this step's output does not enter a staging zone; otherwise a zone_id already set up at this site.", "", synonyms=("zone",)),
    )),
    Contract("master", "orders", "Orders (master data)", "A known outbound order: when it was received, when it must be despatched, and how much work it needs.", ("site_id", "order_id"), (
        SITE,
        Field("order_id", "text", True, "Your stable ID for the order.", "SO-10045", synonyms=("order_ref", "order_number")),
        Field("customer_id", "text", False, "Customer ID if this order belongs to one.", "cust_A", synonyms=("customer",)),
        Field("order_received", "datetime", True, "When the order was received. ISO 8601 with offset, or site-local time.", "2026-10-12 09:00", synonyms=("received", "received_at")),
        Field("despatch_due", "datetime", True, "When the order must be despatched by.", "2026-10-12 13:00", synonyms=("due", "due_at", "deadline")),
        Field("units", "number", False, "Quantity in units. Required unless lines is given.", "100", synonyms=("quantity",)),
        Field("lines", "number", False, "Quantity in lines, converted to units using a configured Unit conversion. Ignored if units is given.", "", synonyms=("line_count",)),
        Field("unit", "text", False, "Target unit for planning (defaults to units).", "units"),
        Field("process_code", "text", True, "The process_code from Process templates this order follows.", "outbound_standard", synonyms=("process",)),
    ), notes=("despatch_due must be after order_received.", "units and lines are never added together — units is used whenever it is given.")),
    Contract("master", "worker_activity_rates", "Worker activity rates (master data)", "A person's own productivity rate for one activity, overriding the activity standard for them.", ("worker_ref", "activity", "effective_from"), (
        Field("worker_ref", "text", True, "The worker_ref used in the staff upload.", "E1042", synonyms=("employee_id", "staff_id", "id", "worker_id")),
        Field("activity", "text", True, "Activity this rate applies to; must already have a work standard.", "picking", synonyms=("task",)),
        Field("unit", "text", False, "Unit this rate is measured in (defaults to units).", "units"),
        Field("rate_per_hour", "number", True, "Units per hour at this activity for this person.", "280", synonyms=("rate", "units_per_hour")),
        Field("effective_from", "date", False, "Date this rate starts (defaults to today).", "2026-10-01", synonyms=("start_date", "from")),
    ), notes=("A changed rate for the same person and activity closes the previous one on the day the new one starts.",)),
    Contract("master", "unit_conversions", "Unit conversions (master data)", "A factor to convert one unit into another, optionally scoped to one activity.", ("activity", "from_unit", "to_unit"), (
        Field("activity", "text", False, "Leave blank for a global conversion, or name the activity this conversion is specific to.", "", synonyms=("task",)),
        Field("from_unit", "text", True, "Unit you are converting from.", "lines", synonyms=("from",)),
        Field("to_unit", "text", True, "Unit you are converting to.", "units", synonyms=("to",)),
        Field("factor", "number", True, "Multiply a from_unit quantity by this to get to_unit (for example 10 lines x 3.2 = 32 units).", "3.2"),
    ), notes=("An activity-specific conversion is used ahead of a global one for the same from_unit/to_unit pair.",)),
    Contract("master", "fill_priorities", "Fill priorities (master data)", "The order to fill labour gaps when not everything can be covered. Lower numbers fill first; equal numbers are equal priority.", ("scope", "value"), (
        Field("scope", "enum", True, "What kind of thing this priority applies to. 'customer' is not yet supported and is rejected, not silently accepted.", "activity", ("activity", "employment_type")),
        Field("value", "text", True, "The specific activity or employment type this priority applies to.", "picking"),
        Field("priority", "int", True, "Lower fills first. Equal values are equal priority — never inferred as ranked.", "1"),
    ), notes=("Customer-scoped fill priority is explicitly out of scope for this release — upload rejects it rather than accepting an inert row.",)),
    Contract("master", "absenteeism", "Absenteeism (master data)", "Expected absence rate for a site, optionally narrowed by activity, weekday and shift. The most specific match is used; leave a field blank to make a rule broader.", ("site_id", "activity", "weekday", "shift_code"), (
        SITE,
        Field("activity", "text", False, "Leave blank to apply to every activity.", "", synonyms=("task",)),
        Field("weekday", "enum", False, "Leave blank to apply to every weekday.", "", ("", "monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")),
        Field("shift_code", "text", False, "Leave blank to apply to every shift.", "", synonyms=("shift",)),
        Field("absence_pct", "number", True, "Expected absence rate as a percentage (10 means 10%).", "10", synonyms=("absence_rate", "absence")),
    ), notes=("Scheduled hours = productive hours / (1 - absence rate); a 10% rate needs about 11.11% extra scheduled capacity.",)),
    Contract("master", "equipment", "Equipment (master data)", "A shared pool of equipment units at a site (for example high-reach trucks), limiting how many activities needing it can run at once.", ("site_id", "equipment_id"), (
        SITE,
        Field("equipment_id", "text", True, "Your stable ID for this equipment pool.", "HIGH_REACH", synonyms=("equipment", "code")),
        Field("description", "text", True, "Display name.", "High-reach forklift"),
        Field("quantity_available", "int", True, "How many units of this equipment exist at the site.", "3", synonyms=("quantity", "count")),
    )),
    Contract("master", "headcount_limits", "Headcount limits (master data)", "Minimum and maximum people allowed on one activity at once, optionally for one shift.", ("site_id", "activity", "shift_code"), (
        SITE,
        Field("activity", "text", True, "Activity this limit applies to; must already have a work standard.", "picking", synonyms=("task",)),
        Field("shift_code", "text", False, "Leave blank to apply across every shift.", "", synonyms=("shift",)),
        Field("min_headcount", "int", True, "Minimum people required when this activity runs at all.", "1"),
        Field("max_headcount", "int", True, "Maximum people allowed at once.", "6"),
    ), notes=("A minimum above the maximum is rejected, not silently accepted.",)),
    Contract("master", "grade_rates", "Grade/provider rates (master data)", "An hourly rate narrowed to one position grade or labour provider, for when the general employment-type/role rate is not specific enough.", ("employment_type", "role", "position_grade", "provider_id", "effective_from"), (
        Field("employment_type", "enum", True, "How the person is engaged.", "labour_hire", ("permanent", "casual", "labour_hire")),
        Field("role", "text", True, "Role or skill the rate applies to.", "picker", synonyms=("skill", "position")),
        Field("position_grade", "text", False, "Leave blank to apply regardless of grade.", "", synonyms=("grade",)),
        Field("provider_id", "text", False, "Leave blank to apply regardless of labour provider; otherwise must be a provider already on file.", "", synonyms=("provider",)),
        Field("hourly_rate", "number", True, "Cost per paid hour, as you want it used for planning.", "48.00", synonyms=("rate", "cost_per_hour")),
        Field("overtime_multiplier", "number", False, "Overtime multiplier, for example 1.5.", "1.5"),
        Field("surcharge", "number", False, "Extra per hour, for example an agency margin.", "8"),
        Field("currency", "text", False, "Defaults to AUD.", "AUD"),
        Field("effective_from", "date", False, "Date this rate starts (defaults to today).", "2026-10-01"),
        Field("effective_to", "date", False, "Date this rate stops applying, if known.", ""),
    ), notes=("A grade- or provider-specific rate is used ahead of the general employment-type/role rate.", "Award names are identifiers here, not an award-compliance calculation.")),
    Contract("master", "productivity_loss", "Productivity loss (master data)", "An explicit congestion rate reduction or off-task hours reduction, for a site and optionally one activity/weekday/shift. Never a crowding curve.", ("site_id", "type", "activity", "weekday", "shift_code"), (
        SITE,
        Field("type", "enum", True, "congestion reduces the rate; off_task reduces available hours.", "congestion", ("congestion", "off_task")),
        Field("activity", "text", False, "Leave blank to apply to every activity.", "", synonyms=("task",)),
        Field("weekday", "enum", False, "Leave blank to apply to every weekday.", "", ("", "monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")),
        Field("shift_code", "text", False, "Leave blank to apply to every shift.", "", synonyms=("shift",)),
        Field("percent_loss", "number", False, "Required for type congestion: percentage rate reduction (10 means 10%).", "10"),
        Field("off_task_hours", "number", False, "Required for type off_task: hours removed from availability.", ""),
    ), notes=("Give exactly one of percent_loss (congestion) or off_task_hours (off_task), never both.",)),
    Contract("master", "staging_capacity", "Staging capacity (master data)", "Maximum concurrent occupancy for a zone, in an explicit unit (for example pallets). Zone must already exist.", ("site_id", "zone_id"), (
        SITE,
        Field("zone_id", "text", True, "Zone this capacity applies to; must already exist.", "STAGE", synonyms=("zone",)),
        Field("capacity", "number", True, "Maximum concurrent occupancy.", "120"),
        Field("unit", "text", True, "Unit capacity and every movement for this zone must share (for example pallets).", "pallets"),
    ), notes=("A movement in a different unit than the zone's capacity is rejected, never guess-converted.",)),
    Contract("master", "staging_movements", "Staging movements (master data)", "Arrivals, departures and initial occupancy for a staging zone, used to check against its capacity.", ("site_id", "zone_id", "occurred_at", "movement_type"), (
        SITE,
        Field("zone_id", "text", True, "Zone this movement applies to; must already have a Staging capacity row.", "STAGE", synonyms=("zone",)),
        Field("occurred_at", "datetime", True, "When this movement happened. ISO 8601 with offset, or site-local time.", "2026-10-12 06:00"),
        Field("movement_type", "enum", True, "initial occupancy, an arrival, or a departure.", "arrival", ("initial", "arrival", "departure")),
        Field("quantity", "number", True, "Quantity moved, in the zone's capacity unit.", "20"),
        Field("unit", "text", True, "Must match the zone's Staging capacity unit exactly.", "pallets"),
    )),
    Contract("master", "indirect_headcount", "Indirect headcount (master data)", "A fixed headcount required for a role at a site/weekday/time window, independent of direct-work volume (supervisors, inventory control, etc.).", ("site_id", "role", "weekday", "start_time", "end_time"), (
        SITE,
        Field("role", "text", True, "Role required; matched against a worker's skills/certifications.", "supervisor", synonyms=("skill",)),
        Field("weekday", "enum", True, "Day of the week.", "monday", ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")),
        Field("start_time", "text", True, "Start time, 24-hour HH:MM site-local.", "06:00"),
        Field("end_time", "text", True, "End time, 24-hour HH:MM site-local.", "14:00"),
        Field("headcount", "int", True, "Number of people required, regardless of demand that day.", "3"),
    ), notes=("Required even on a zero-volume day — indirect coverage is not derived from workload.",)),
    Contract("master", "weekly_availability", "Weekly availability pattern (master data)", "A person's recurring default availability for one weekday, and the earliest/latest time they can work it. A dated leave/unavailable entry (Availability) always overrides this for that specific date.", ("worker_ref", "weekday"), (
        Field("worker_ref", "text", True, "The worker_ref used in the staff upload.", "E1042", synonyms=("employee_id", "staff_id", "id", "worker_id")),
        Field("weekday", "enum", True, "Day of the week.", "monday", ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")),
        Field("available", "bool", False, "Defaults to true. False means unavailable this weekday regardless of times.", "true"),
        Field("earliest_start", "text", False, "Earliest time this person can start, 24-hour HH:MM. Leave blank with latest_finish for no window (available all day).", "06:00"),
        Field("latest_finish", "text", False, "Latest time this person can finish, 24-hour HH:MM. At or before earliest_start crosses midnight (an overnight window).", "14:00"),
    ), notes=("A dated Availability entry (leave, unavailable, rdo) always overrides this pattern for that date.", "Give both earliest_start and latest_finish, or neither — one without the other is rejected.")),
    Contract("master", "day_rates", "Day rates (master data)", "An activity's standard rate for one weekday, ranking above the plain activity standard for anyone without a personal rate.", ("activity", "weekday"), (
        ACTIVITY,
        Field("weekday", "enum", True, "Day of the week.", "monday", ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")),
        Field("rate_per_hour", "number", True, "Units per hour on this weekday.", "90"),
    ), notes=("Used only when a worker has no personal activity rate for that activity.",)),
    Contract("master", "award_rules", "Award rules (master data)", "The actual ordinary-hours and overtime numbers behind an award/agreement name — an award name alone is never a complete rule.", ("award_code",), (
        Field("award_code", "text", True, "The award/agreement identifier used on Staff uploads.", "retail_award_2024", synonyms=("award",)),
        Field("ordinary_hours_per_day", "number", True, "Hours per day before overtime applies.", "8"),
        Field("overtime_multiplier", "number", True, "Multiplier applied to hours beyond ordinary_hours_per_day.", "1.5"),
    )),
    Contract("master", "award_eligibility_restrictions", "Award eligibility restrictions (master data)", "An EXPLICIT statement that workers under an award/agreement may not perform an activity. Nothing is inferred from the award's name — only rows uploaded here restrict anything.", ("award_code", "activity"), (
        Field("award_code", "text", True, "The award/agreement identifier used on Staff uploads.", "retail_award_2024", synonyms=("award",)),
        ACTIVITY,
    ), notes=("An award with no row here restricts nothing — eligibility otherwise follows skills/certifications and activity rates as usual.",)),
    Contract("forecast", None, "Forecast workload", "Expected units per activity and period. Customer-supplied forecasts are versioned and shown with their origin.", ("site", "activity", "period_start", "grain"), (
        SITE, ACTIVITY, PERIOD_START, GRAIN,
        Field("units", "number", True, "Expected units in the period.", "26500", synonyms=("forecast", "volume", "quantity", "expected")),
        Field("lower", "number", False, "Optional low estimate.", "24000", synonyms=("low", "min")),
        Field("upper", "number", False, "Optional high estimate.", "29000", synonyms=("high", "max")),
    ), batch_options=(
        Field("forecast_version", "text", True, "A label for this forecast (for example 2026-10-W2-v1). A label can be used once.", "2026-10-W2-v1"),
        Field("generated_at", "datetime", False, "When the customer produced the forecast.", "2026-10-01T06:00:00+11:00"),
    ), notes=("A revised forecast flags draft rosters for review. It never rewrites a published roster.",)),
    Contract("transactions", None, "Workload events (actuals, one row per event)", "Individual operational events: what was processed, when.", ("source", "event_id"), (
        Field("event_id", "text", True, "Your unique ID for the event. Resending the same event changes nothing.", "RCV-88231", synonyms=("id", "transaction_id", "txn_id", "reference")),
        SITE, ACTIVITY,
        Field("occurred_at", "datetime", True, "When it happened. ISO 8601 with offset, or site-local time.", "2026-09-28 14:32", synonyms=("timestamp", "time", "event_time", "datetime")),
        Field("quantity", "number", True, "Units processed (not negative).", "12", synonyms=("units", "qty", "volume")),
        Field("unit", "text", False, "Unit label (defaults to units). All rows for an activity must use one unit.", "units", synonyms=("uom",)),
        Field("customer", "text", False, "Customer ID if you track workload per customer.", "cust_A", synonyms=("customer_id",)),
        Field("action", "enum", False, "create (default), correct or cancel.", "create", ("create", "correct", "cancel")),
        Field("revision", "int", False, "Increasing number for corrections. A lower revision than the one held is ignored as out of date.", "2"),
        Field("source", "text", False, "Name of the sending system (defaults to default). Event IDs are unique per source.", "wms", synonyms=("system",)),
    ), notes=("Events feed hourly workload actuals. If bulk totals are authoritative for the same site and activity, events are stored but not counted.",)),
    Contract("bulk", None, "Workload totals (actuals, per period)", "Hourly or daily totals when individual events are not available.", ("site", "activity", "period_start", "grain"), (
        SITE, ACTIVITY, PERIOD_START, GRAIN,
        Field("units", "number", True, "Total units processed in the period (not negative).", "26140", synonyms=("quantity", "volume", "total", "actual")),
        Field("customer", "text", False, "Customer ID if you track workload per customer.", "cust_A", synonyms=("customer_id",)),
    ), batch_options=(
        Field("mode", "enum", True, "upsert: add or update these periods only. replace_slice: replace everything in the stated date range for the activities in the file.", "upsert", ("upsert", "replace_slice")),
        Field("slice_start", "date", False, "First local date of the slice (required for replace_slice).", "2026-10-01"),
        Field("slice_end", "date", False, "Last local date of the slice, inclusive (required for replace_slice).", "2026-10-07"),
        Field("control_total", "number", False, "Optional total of units you expect; the import is held if the file does not add up to it.", "180000"),
        Field("take_over", "bool", False, "Allow this upload to replace workload that came from a different source for the same periods.", "false"),
    ), notes=("Replacing a slice needs its range stated; an ambiguous replacement is refused.",)),
)}

DATA_CLASSES = {"master": ("workers", "work_standards", "sites", "customers", "availability", "rates", "zones", "activity_roles", "operating_calendar", "shift_templates", "shift_breaks",
                            "process_templates", "process_steps", "orders", "worker_activity_rates", "unit_conversions",
                            "fill_priorities", "absenteeism", "equipment", "headcount_limits",
                            "grade_rates", "productivity_loss", "staging_capacity", "staging_movements", "indirect_headcount", "weekly_availability",
                            "day_rates", "award_rules", "award_eligibility_restrictions"),
                 "forecast": (None,), "transactions": (None,), "bulk": (None,)}


def contract_for(data_class: str, entity: str | None) -> Contract:
    c = CONTRACTS.get((data_class, entity if data_class == "master" else None))
    if c is None:
        raise KeyError(f"unknown data class '{data_class}'" + (f" / '{entity}'" if entity else ""))
    return c


def describe(c: Contract) -> dict:
    f = lambda x: {"name": x.name, "type": x.kind, "required": x.required, "description": x.description, "example": x.example, **({"choices": list(x.choices)} if x.choices else {})}  # noqa: E731
    return {"data_class": c.data_class, "entity": c.entity, "title": c.title, "purpose": c.purpose, "contract_version": CONTRACT_VERSION, "key": list(c.key),
            "fields": [f(x) for x in c.fields], "batch_options": [f(x) for x in c.batch_options], "notes": list(c.notes), "limits": {"max_rows_per_batch": MAX_ROWS, "max_file_bytes": MAX_BYTES}}


def template_csv(c: Contract) -> str:
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\r\n")
    w.writerow(c.names)
    w.writerow([x.example for x in c.fields])
    return buf.getvalue()
