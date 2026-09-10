# Environment and Access Matrix (draft, P0-07)

Status: **draft** — ownership names are placeholders (same caveat as
`.github/CODEOWNERS`); this repo currently has one collaborator
(`archivalg`, admin) and no dev/test/UAT/production environments exist yet
(Phase 8 creates them). This matrix is the target shape to fill in as
those environments and real team members exist, not a record of something
already provisioned.

## Environments

| Environment | Purpose | Data | Access |
|---|---|---|---|
| Local dev | Individual engineer work | Synthetic seed data only (`tests/factories.py`, `scripts/seed_e2e.py`) | All engineers |
| CI (ephemeral) | Automated test runs on every PR | Synthetic fixtures only, destroyed after each run | CI system only; no human access |
| Test / integration | Vendor sandbox certification (INT-05/06), Oracle validation (DAT-01) | Vendor sandbox data, synthetic canonical data | Backend/integration engineers, QA |
| UAT | Stakeholder acceptance, pilot UAT (PIL) | Masked production-like data (§16.1) — **never** unmasked worker PII | Product owner, pilot stakeholders, QA, technical lead |
| Production | Live pilot | Real pilot tenant data | Named support operators only, under ADR-0008's grant workflow once approved; no standing engineer access |

## Access principle

Per SEC-24/§6.2's "Support operator" principal type: **no engineer holds
standing production access.** Production troubleshooting goes through the
privileged-support-grant workflow (ADR-0008) once built — this is a target
state, not true today (there is no production environment yet to have
standing access to).

## Role ownership (to be named, not placeholders, before Phase 1 exit)

| Area | Owner role | Fills SEC-14's "Tempo-owned authoritative data" requirement for |
|---|---|---|
| Identity/tenant/membership data | Technical lead + security | Who tenant admins are, who can be one |
| Oracle production access | Platform owner + DBA | DAT-09 backup/restore, SEC-19 VPD administration |
| Vault/secrets | Platform owner | SEC-08 |
| Vendor sandbox credentials | Integration engineers, tenant-scoped | INT-03 |
| Release approval | Technical lead + product owner | §18.1 phase gates |

## Data classification (feeds DAT-08's encryption/masking requirement)

| Class | Examples | Lower-environment handling |
|---|---|---|
| Worker PII | Names, PINs (post-Argon2id), NFC identifiers | Masked/synthetic only outside production |
| Operational | Demand, roster, attendance, cost | Synthetic or masked outside production |
| Credentials | Vendor API secrets, service-client secrets | Never present outside Vault; not copied to lower environments at all |
| Audit | Security events, action history | Retained per DAT-07's retention policy (not yet defined) |

## Open items

- Real environment provisioning is Phase 8's job (OPS-02); this matrix
  describes the target, not current infrastructure.
- Named individuals for each ownership row are a P0-07 exit criterion this
  document cannot fill in on its own — needs the environment/access review
  Phase 0's acceptance criteria call for.
