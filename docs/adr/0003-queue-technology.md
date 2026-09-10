# ADR-0003: Queue and event technology

**Status**: Proposed — awaiting approval
**Decision owner**: Technical lead (Appendix D: "before Phase 4 build")

## Context

Every solver run currently executes synchronously inside the API request
(`app/api/v1/runs.py`), and the idempotency store and event bus are
in-process Python dictionaries (`app/core/idempotency.py`,
`app/core/events.py`) — both explicitly disclosed as "fine for one API
replica, not for Phase F scale." JOB-01 through JOB-08 require durable
run queuing, a scheduler, and a transactional outbox.

## Options considered

1. **OCI Queue** (commands: "run this solver," "sync this connector") +
   **OCI Streaming** (events: "run completed," "action confirmed") — native
   OCI managed services, consistent with the ADB/OCI-compute choices in
   ADR-0002/0004, minimal new operational surface.
2. **A general message broker (RabbitMQ/Kafka) self-hosted on OCI Compute**
   — more portable, but adds an entire operational discipline (cluster
   management, partition/queue design, monitoring) this team's staffing
   doesn't budget for, and duplicates what OCI Queue/Streaming already give
   for free operationally.
3. **Database-backed queue only (no separate broker)** — Postgres/Oracle
   "SELECT ... FOR UPDATE SKIP LOCKED"-style polling. Simpler to operate,
   no new infrastructure, and works as a *fallback* if OCI Streaming turns
   out to be unavailable or unjustified in the target region — but weaker
   delivery/ordering guarantees and higher latency than a real broker at
   any real concurrency.

## Recommendation

**OCI Queue for commands** (run submission, connector sync requests,
writeback execution) and **OCI Streaming for events** (run completed,
action confirmed, connector health changed) — falling back to a
transactional-outbox-plus-polling implementation against the production
database *only* if OCI Streaming proves unavailable or cost-unjustified in
the pilot's region, since JOB-07 requires a transactional outbox regardless
of the underlying transport.

## Trade-offs

- Two managed services instead of one general broker means two things to
  configure and monitor, but each is purpose-built (command vs. event) and
  neither requires the team to run broker infrastructure itself.
- OCI Streaming (Kafka-compatible) has a per-partition cost model that
  needs sizing against expected event volume once the pilot's connector
  sync frequency and run cadence are known — deferred to Phase 4 build
  time, not decidable now.
- Choosing OCI-native services over Kafka/RabbitMQ directly narrows future
  portability to another cloud — consistent with, and no worse than, the
  Oracle ADB and OCI-compute choices already implied elsewhere.

## Cost

OCI Queue and Streaming are both consumption-priced; at pilot scale (one
site, one WMS, one workforce connector, synchronous-equivalent run volume)
the cost is small relative to engineer-hours saved versus self-hosting a
broker. The real cost driver is JOB-01–JOB-08's engineering effort
(worker service, durable idempotency store, scheduler, outbox), not the
transport choice.

## Exact work this decision blocks

All of Phase 4: JOB-01 (durable run acceptance), JOB-02 (worker pool),
JOB-06 (idempotency store migration off process memory), JOB-07
(transactional outbox), JOB-08 (scheduler for drift checks,
recommendation-expiry warnings, connector syncs). This sprint's Phase 1
work does not depend on this decision.

## Built to be swappable

Not applicable — no queue/eventing code was touched this sprint.
`app/core/idempotency.py` and `app/core/events.py` remain exactly the
disclosed in-process stand-ins they were; replacing them is Phase 4's job,
gated on this ADR, not something this sprint worked around.
