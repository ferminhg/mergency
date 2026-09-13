# Rolling-window budget calculation

With events classified (ADR 0005) and attributed to a team owner (ADR 0006), the next roadmap item is `ARQUITECTURE.md`'s "Budget calculator" stage: turning a stream of owned events into the per-owner rolling-window budget status that README's "How it works" step 3 describes, using the `rolling_window_days`/`max_events_per_window` settings ADR 0006 already introduced on `TenantConfig`.

## Status

📋 proposed

## Considered Options

**Compute on demand, not precomputed.** A `BudgetCalculator` service queries `EventRepository` for `COUNT(*) WHERE installation_id = X AND owner = Y AND ts >= now - window_days` at the moment a caller needs a status (a PR comment, a historical query), rather than maintaining a separately-updated aggregate. Chosen because it avoids a second data structure that can drift from the source-of-truth `events` table, and because the actual call pattern (once per relevant PR event, not once per raw event) doesn't need pre-aggregation to stay fast. Revisit only if this query becomes a measured bottleneck once real Postgres persistence exists.

**Durable persistence becomes necessary here.** ADR 0005 deferred introducing Postgres, keeping events in-memory. A rolling 28-day window is meaningless if the event history doesn't survive a process restart or redeploy, so this is the milestone that should introduce the real `EventRepository` adapter backed by PostgreSQL/SQLAlchemy (async), matching `ARQUITECTURE.md`'s `events` table and `ADR 0001`'s chosen stack. The in-memory adapter from ADR 0005/0006 is replaced here, not kept alongside it.

**Defining "shrinking".** README says Mergency comments "when a PR touches an owner with a shrinking budget" without pinning down a threshold. Chosen: extend the proposed `mergency.yml` shape with a `budget.warn_threshold_pct` setting (default e.g. 50), and treat a budget as shrinking whenever `remaining_pct <= warn_threshold_pct`. A flat "any consumption at all triggers a comment" was considered and rejected — it would make the very first failure in a fresh window noisy immediately, working against the "signal, not noise nobody acts on" framing from README's intro.

**Which event types count.** Chosen: `BudgetCalculator` filters by an explicit allow-list of counted `EventType` values (`BUILD_FAILURE`, `REVERT` today), not "every row in the table". This is a deliberate forward-compatibility choice: ADR 0010 (flaky test signal, v2) and ADR 0011 (deploy-to-incident traceability, v2) both add new `EventType` values later, and at least one of them (`FLAKY_TEST`) is explicitly designed to be visible but **not** counted against budget. An allow-list means adding a new event type never silently changes what a budget consumes; a deny-list or "count everything" default would.

**Output shape.** `BudgetStatus(owner, window_days, limit, consumed, remaining_pct)`, returned by a single `BudgetCalculator.status_for(installation_id, owner) -> BudgetStatus` method. ADR 0008 (PR comment bot) and ADR 0009 (historical query) both consume this same type instead of each recomputing it.

## Consequences

- New `BudgetStatus` model (`domain/models/budget_status.py`) and `BudgetCalculator` domain service (`domain/budget_calculator.py`), depending only on the `EventRepository` and `TenantConfigRepository` ports — no FastAPI/Celery/SQLAlchemy/PyGithub imports, per the hexagonal boundary rule.
- `EventRepository`'s port interface gains a windowed counting/listing method (e.g. `count_since(installation_id, owner, event_types, since) -> int`); the real Postgres-backed adapter introduced here implements it as a single indexed query (`installation_id`, `owner`, `ts` should be indexed together).
- README's proposed `mergency.yml` format gains `budget.warn_threshold_pct` — still "proposed, subject to change" per README's own caveat, not yet a committed schema.
- This is the milestone where Postgres/SQLAlchemy stop being "chosen in ADR 0001 but unused" and become real: a `docs/plan/000X-postgres-persistence.md` (or folded into the budget-calculation plan) needs a migration for the `events` and `tenant_config` tables.
- Not implemented yet — unblocks a future implementation plan, TDD-first per this repo's convention.
