# Agent instructions for Tempo

- Treat `docs/roadmap.md` as the current scope authority. `docs/build-progress.md` is historical unless a statement is reconciled there.
- Preserve the React/TypeScript console and Python/FastAPI/PostgreSQL stack. Do not rebuild Tempo as a separate website.
- Follow `docs/ui-design-system.md` for all UI work. Use shared tokens and components in `services/tempo-console/src/design/` and `services/tempo-console/src/components/`.
- Keep UI claims honest: shells, simulated data, pending credentials, unknown writeback outcomes and indicative prices must be labelled as such.
- Kiosk work must keep the device surface separate from the customer administration shell.
- Do not mark roadmap milestones accepted unless the acceptance evidence in `docs/roadmap.md` has actually been demonstrated.
