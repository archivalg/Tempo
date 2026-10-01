"""Writes docs/data-contracts.md from the same definitions the validators and CSV templates use (so the document cannot drift).
Run: PYTHONPATH=services/tempo-api python scripts/gen_contracts_doc.py"""
from pathlib import Path

from app.imports.contracts import CONTRACT_VERSION, CONTRACTS, MAX_ROWS, describe

out = [f"# Tempo data contracts — version {CONTRACT_VERSION}", "",
       "Generated from the validators' own definitions. Four data classes can be loaded by CSV upload (Data → Load data) or by API (`POST /v1/imports/batches`).",
       f"Limits: {MAX_ROWS:,} rows per batch. Times are ISO 8601 with an offset, or site-local `YYYY-MM-DD HH:MM` (a local time that does not exist or happens twice is refused with instructions).", "",
       "Rules that apply to every class: nothing changes until a batch is applied; the same content or the same `Idempotency-Key` is never applied twice; rejected rows are reported with reasons and can be downloaded; accepted rows can be applied on their own only by choice; workload is counted from one kind (events or totals) per site and activity.", ""]
for c in CONTRACTS.values():
    d = describe(c)
    out += [f"## {d['title']}", "", d["purpose"], "", f"`data_class`: `{d['data_class']}`" + (f" · `entity`: `{d['entity']}`" if d["entity"] else "") + f" · key: {', '.join('`' + k + '`' for k in d['key'])}", "",
            "| Field | Type | Required | Meaning | Example |", "|---|---|---|---|---|"]
    for f in d["fields"]:
        out.append(f"| `{f['name']}` | {f['type']}{' (' + '/'.join(f['choices']) + ')' if f.get('choices') else ''} | {'yes' if f['required'] else 'no'} | {f['description']} | `{f['example']}` |")
    if d["batch_options"]:
        out += ["", "Batch options (sent once, not per row):", "", "| Option | Type | Required | Meaning |", "|---|---|---|---|"]
        for f in d["batch_options"]:
            out.append(f"| `{f['name']}` | {f['type']}{' (' + '/'.join(f['choices']) + ')' if f.get('choices') else ''} | {'yes' if f['required'] else 'no'} | {f['description']} |")
    out += [""] + [f"- {n}" for n in d["notes"]] + [""]
Path("docs/data-contracts.md").write_text("\n".join(out))
print("wrote docs/data-contracts.md")
