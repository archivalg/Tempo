"""CSV parsing, header → field mapping, and the site-local time rules shared by every data class."""
from __future__ import annotations

import csv
import io
import re
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from app.imports.contracts import MAX_BYTES, MAX_ROWS, Contract


class ImportProblem(ValueError):
    """A problem with the whole file or request (not a single row)."""


def read_csv(data: bytes) -> tuple[list[str], list[dict[str, str]]]:
    if len(data) > MAX_BYTES:
        raise ImportProblem(f"the file is larger than {MAX_BYTES // (1024 * 1024)} MB — split it into smaller files")
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise ImportProblem("the file is not UTF-8 text — save it as 'CSV UTF-8' and try again") from None
    if not text.strip():
        raise ImportProblem("the file is empty")
    sample = text[:4096]
    delim = ","
    first = sample.splitlines()[0] if sample.splitlines() else ""
    if first.count(";") > first.count(",") and first.count(";") >= 1:
        delim = ";"
    elif first.count("\t") > first.count(","):
        delim = "\t"
    rdr = csv.reader(io.StringIO(text), delimiter=delim)
    try:
        headers = [h.strip() for h in next(rdr)]
    except StopIteration:
        raise ImportProblem("the file has no header row") from None
    if len(set(h.lower() for h in headers if h)) != len([h for h in headers if h]):
        raise ImportProblem("two columns have the same name — rename one of them")
    rows: list[dict[str, str]] = []
    for r in rdr:
        if not any(c.strip() for c in r):
            continue
        rows.append({h: (r[i].strip() if i < len(r) else "") for i, h in enumerate(headers) if h})
        if len(rows) > MAX_ROWS:
            raise ImportProblem(f"more than {MAX_ROWS:,} rows — split the file (larger files need a background worker that is not built yet)")
    if not rows:
        raise ImportProblem("the file has a header but no data rows")
    return headers, rows


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", s.strip().lower()).strip("_")


def suggest_mapping(contract: Contract, headers: list[str], saved: dict[str, str] | None = None) -> dict[str, str | None]:
    """canonical field → header. Saved mapping first (if its header is still there), then exact name, then known synonyms. Never guesses between two."""
    present = {_norm(h): h for h in headers}
    out: dict[str, str | None] = {}
    taken: set[str] = set()
    for f in contract.fields:
        pick = None
        if saved and saved.get(f.name) in headers:
            pick = saved[f.name]
        else:
            for cand in (f.name, *f.synonyms):
                h = present.get(_norm(cand))
                if h and h not in taken:
                    pick = h
                    break
        out[f.name] = pick
        if pick:
            taken.add(pick)
    return out


def apply_mapping(contract: Contract, mapping: dict[str, str | None], rows: list[dict[str, str]]) -> list[dict[str, str]]:
    return [{f.name: (r.get(mapping[f.name], "") if mapping.get(f.name) else "") for f in contract.fields} for r in rows]


# ---- time rules -------------------------------------------------------------------------------------------------------------------

_ISO_LOCAL = re.compile(r"^(\d{4})-(\d{2})-(\d{2})(?:[T ](\d{2}):(\d{2})(?::(\d{2}))?)?$")


def parse_moment(value: str, tz: ZoneInfo) -> datetime:
    """An instant in UTC. Offsets/Z are taken as given; local times are read in the site's timezone. A local time that does not exist
    (spring-forward gap) or happens twice (autumn overlap) is refused with instructions rather than guessed."""
    v = value.strip()
    if not v:
        raise ImportProblem("a time is required")
    try:
        if re.search(r"(Z|[+-]\d{2}:?\d{2})$", v) and "T" in v.replace(" ", "T"):
            d = datetime.fromisoformat(v.replace("Z", "+00:00").replace(" ", "T"))
            if d.tzinfo is None:
                raise ValueError
            return d.astimezone(timezone.utc)
    except ValueError:
        raise ImportProblem(f"'{value}' is not a valid date and time") from None
    m = _ISO_LOCAL.match(v)
    if not m:
        raise ImportProblem(f"'{value}' is not a recognised date/time — use 2026-10-05 14:30 (site time) or 2026-10-05T14:30:00+11:00")
    y, mo, d, hh, mi, ss = (int(x) if x else 0 for x in m.groups())
    try:
        naive = datetime(y, mo, d, hh, mi, ss)
    except ValueError:
        raise ImportProblem(f"'{value}' is not a real date") from None
    a, b = naive.replace(tzinfo=tz, fold=0), naive.replace(tzinfo=tz, fold=1)
    rt = lambda x: x.astimezone(timezone.utc).astimezone(tz).replace(tzinfo=None)  # noqa: E731
    if a.utcoffset() != b.utcoffset():
        if rt(a) == naive and rt(b) == naive:
            raise ImportProblem(f"'{value}' happens twice in {tz.key} (clocks go back) — add the UTC offset, for example +11:00 or +10:00")
        raise ImportProblem(f"'{value}' does not exist in {tz.key} (clocks go forward) — use a time outside the gap")
    return a.astimezone(timezone.utc)


def parse_local_date(value: str) -> date:
    try:
        return date.fromisoformat(value.strip())
    except ValueError:
        raise ImportProblem(f"'{value}' is not a date — use YYYY-MM-DD") from None


def local_day_bounds(day: date, tz: ZoneInfo) -> tuple[datetime, datetime]:
    s = datetime(day.year, day.month, day.day, tzinfo=tz)
    n = day + timedelta(days=1)
    return s.astimezone(timezone.utc), datetime(n.year, n.month, n.day, tzinfo=tz).astimezone(timezone.utc)


def aligned_bucket(value: str, grain: str, tz: ZoneInfo) -> tuple[datetime, int]:
    """(bucket start in UTC, bucket minutes). Hours start on the local hour (a local hour that is not on the hour in UTC is fine);
    days start at local midnight and last 23/24/25 hours across DST — the minutes value stays 1440 as the label for a *day*."""
    if grain not in ("hour", "day"):
        raise ImportProblem("grain must be hour or day")
    v = value.strip()
    if grain == "day" and re.fullmatch(r"\d{4}-\d{2}-\d{2}", v):
        return local_day_bounds(parse_local_date(v), tz)[0], 1440
    start = parse_moment(v, tz)
    loc = start.astimezone(tz)
    if grain == "hour":
        if loc.minute or loc.second:
            raise ImportProblem(f"'{value}' is not on the hour — hourly periods start at :00")
        return start, 60
    if loc.hour or loc.minute or loc.second:
        raise ImportProblem(f"'{value}' is not local midnight — daily periods start at 00:00 site time (or give just the date)")
    return start, 1440
