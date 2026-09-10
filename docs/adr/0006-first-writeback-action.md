# ADR-0006: First writeback action and reversal method

**Status**: Proposed — awaiting approval
**Decision owner**: Product owner and pilot operations owner (Appendix D: "before Phase 5 build")

## Context

Every controlled action against a vendor target honestly returns
`unknown` today (`app/maestro/writeback.py`'s `NotImplementedWritebackClient`)
— no real vendor writeback connector exists. `app/maestro/native_writeback.py`
proves the *pipeline* works end to end (validate → execute → reconcile)
for a Tempo-native target; ACT-01–ACT-11 require the same for one real
vendor. §1.2 restricts the first release to "one reversible roster-
publication pathway."

## Options considered

1. **`publish_roster` against Deputy** — the action type this codebase's
   own action pipeline already fully models (`ACTION_TYPE_RUN_TYPE` maps it
   to `named_roster`), and Deputy already has a read client to build a
   write path alongside.
2. **`approve_leave`** — also modelled end-to-end natively
   (`TempoNativeWritebackClient.approve_leave`), but a less visible,
   lower-stakes pilot proof point than publishing an actual roster; weaker
   demonstration of the platform's core value proposition for a first
   pilot.
3. **`update_assignment` (intraday reallocation)** — has no defined native
   write target even today (disclosed gap); building its vendor writeback
   from nothing, with no working reference implementation to pattern-match
   against, is materially higher risk for a first pilot.

## Recommendation

**`publish_roster` against Deputy** (pending ADR-0005's connector choice
being confirmed as Deputy). For reversal (ACT-08): **republish the prior
committed roster version** as the compensating action, rather than assume
Deputy exposes a true "undo" — ACT-01's entry criteria already require
confirming the vendor sandbox "supports reversible staging or test
publication" before this is locked in; if Deputy's sandbox cannot
guarantee a clean revert, this recommendation must be revisited before
Phase 5 build, not discovered during it.

## Trade-offs

- Republish-prior-version as "reversal" is a real but coarser guarantee
  than a true compensating transaction — it corrects the *end state* but
  does not undo any side effects the vendor's own system produced from the
  interim state (e.g., a notification already sent to a worker). Acceptable
  for a pilot; worth flagging to the pilot operations owner explicitly.
- Choosing roster publication over leave approval means the first pilot's
  writeback proof point is also its highest-visibility one — appropriate
  ambition for a controlled pilot, but raises the bar on ACT-04's
  stale-version detection and ACT-07's reconciliation working correctly
  the first time.

## Cost

Bounded by Phase 5's own requirements (ACT-01–ACT-11); this ADR doesn't
change that scope, only which action and vendor absorb it. Confirming
Deputy's sandbox actually supports reversible staging (this ADR's own
stated precondition) should happen early in Phase 3, not deferred to
Phase 5, to avoid discovering a blocking gap late.

## Exact work this decision blocks

All of Phase 5 (ACT-01 through ACT-11) and the writeback half of Phase 9's
pilot activation (PIL-06/PIL-07). Nothing in this sprint depended on this
decision — the existing action pipeline (`app/api/v1/actions.py`) already
supports any `action_type`/`target.system` combination without change.

## Built to be swappable

Not applicable — no writeback code was touched this sprint.
