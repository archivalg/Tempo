# Time and attendance: how Tempo calculates hours

This describes the built-in (native) time and attendance used by customers who have no external system. It is the behaviour the code implements, not a promise about pay.

## What is recorded

Every tap on the kiosk is stored once, as received, in an append-only list of punches: `clock_in`, `break_start`, `break_end`, `clock_out`. Tempo's application cannot delete or change a punch. A person who corrects a timesheet never edits a punch; the correction is a separate record that needs a second person's approval, and approved hours are calculated from the punches **plus** that correction.

A punch is only shown to the worker as done after the server has stored it, using the server's clock. If the kiosk cannot reach the server it says so; it does not store punches for later (offline capture is not built).

A repeat tap of the same action within the site's *repeat-tap window* (default 30 s) returns the first result and records nothing new. A different action out of order (for example "start break" while already on a break) is refused with a plain message.

## The three hour figures

| Figure | Meaning |
|---|---|
| Worked | Time from the first to the last punch (or the approved corrected times). |
| Break | Recorded break time. Clocking out during a break ends the break at that moment and says so in the history. |
| Payable | Worked less **unpaid** break time, then rounded as the site rules say. Shown only once the timesheet is approved. |

Rounding applies to the payable total only, never to the stored punches. Choices: none, or 1/5/6/10/15/30 minutes, nearest, always up or always down. If a site has never saved its rules, Tempo's defaults apply (unpaid breaks, no rounding, 30 s repeat window, late after 5 min, missing clock-out after 14 h, long day from 12 h) and the screen says they are defaults.

## Matching to rosters

A clock-in is matched to the closest committed rostered shift that started up to 4 hours earlier or is still running (so overnight shifts match). A clock-in with no such shift is kept and labelled **not rostered**; it is never discarded.

## Supervisor's day list

Computed on read for one site-local day: **no-show** (rostered, nobody clocked in after the grace period), **late** (clocked in after the grace period), **clocked in** (still open), **missing clock-out** (open longer than the site's limit; Tempo does not close it for you), **not rostered**, **long day**, and **correction pending**.

## Corrections, approval, reopening

* A supervisor (or tenant administrator or operations manager) can request a correction to a session's times and break, or request a whole missing session. A different person with approval rights decides it; the requester cannot.
* Approving a correction of a session that is still open closes it without inventing a clock-out punch.
* Approving a missing-session request creates the session with two punches whose source is `correction`, so it can always be told apart from real taps.
* An approved timesheet changes only by being **reopened** with a written reason. Reopening records a revision (who, when, why, and the figures that had been approved), removes the timesheet from payroll exports until it is approved again, and raises its revision number.

## Location and the site fence

Each site can have a **geofence** (a circle: latitude, longitude, radius 25 m to 5 km) and a **location rule**: *off* (default), *record* or *require*. When it is on, the kiosk's browser is asked for its position at every tap (clock in, break start, break end, clock out) and sends it with the punch.

* *Record*: the punch always stands. Its status is stored with it: `passed`, `outside` (with distance in metres), `unavailable`/`denied` (the browser gave no position) or `no_fence`. Supervisors see **Outside site** / **No location** on the day list, and the punch history shows each position's distance and accuracy.
* *Require*: a tap from outside the fence, or with no position, is refused with a plain message and **nothing is recorded**; the worker is told to see a supervisor, who can add the time as a correction.
* Turning either on needs a geofence first. Setting the fence and the rule needs the configure permission and is audited.

What this is and is not: it is the **kiosk device's position at the moment of the tap**. A kiosk is shared, so it says nothing about where an individual worker is. It is not continuous tracking, it cannot prove a position (browser location can be wrong or spoofed), and accuracy is stored beside every fix. The kiosk tells workers when the site checks location. Mandatory continuous or per-worker GPS tracking remains out of scope in the roadmap.

## Payroll file

`GET /v1/sites/{site}/exports/payroll-timesheets.csv?start=YYYY-MM-DD&days=7` (also the *Payroll CSV (approved)* button on the Timesheets tab). Requires both the export and attendance-approval permissions and is recorded in the audit log with its row count.

Columns: `employee_no, worker_id, name, work_date, start, end, worked_hours, unpaid_break_hours, payable_hours, revision, corrected, rostered, approved_by, approved_at, session_id`. Times are site-local; hours are decimal. Only approved timesheets are included; the file's header comment says how many in the period are not approved yet and what the break and rounding rules were. `name` is blank unless the caller may see names. **This is hours, not pay**: Tempo does not interpret awards, loadings, overtime or leave. The column layout is Tempo's own; matching a specific payroll system's import format needs that system's specification.
