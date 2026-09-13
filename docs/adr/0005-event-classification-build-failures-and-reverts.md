# Event classification for build failures and reverts

The GitHub App scaffolding (ADR 0001, `docs/plan/0001-github-app-scaffolding.md`) can already receive and acknowledge `push` and `check_run` webhooks, but it just logs them and returns 200 — see `_handle_installation_event`'s sibling branch in `src/mergency/api/webhooks.py`. The next roadmap item is turning those raw webhooks into the classified domain events that `ARQUITECTURE.md`'s "Event classifier" stage describes: `build_failure` and `revert`, the two error types README's "What counts as an error (v1)" section defines. This ADR decides what counts, how it is detected, and where it is stored. Resolving *who* owns an event (ADR 0006) and turning events into a budget (ADR 0007) are separate roadmap items, out of scope here.

## Status

📋 proposed

## Considered Options

**What qualifies as each event type**, matching README's v1 definition exactly:
- `build_failure`: a `check_run` webhook, `action: completed`, whose `check_run.conclusion` is `failure` or `timed_out`, and whose check ran against the repository's default branch (not a feature-branch PR check — those aren't "the build is broken" yet, they're normal PR review feedback).
- `revert`: a `push` webhook to the default branch where a new commit's message matches the standard git revert pattern (`Revert "<original subject>"`) or explicitly names the PR/commit it reverts. This is a heuristic, not a guarantee — a commit message that happens to start with "Revert" without being a real revert is a known false-positive risk, accepted for v1 and revisited only if it proves noisy in practice.

**Where classification runs.** The webhook receiver already routes activity events to the data-plane queue (per `CLAUDE.md`'s one-logical-queue-with-job-types rule). This ADR adds a new job type, e.g. `classify_activity_event`, so `push` and `check_run` events stop being no-ops and instead reach a new `EventClassifier` domain service — still one Celery queue, just a new routed job type, no new infrastructure.

**Persistence: stay in-memory for now (chosen).** `ARQUITECTURE.md`'s `events` table (`installation_id`, `repo`, `sha`, `type`, `owner`, `ts`) is the eventual home for classified events, but this ADR does not introduce Postgres/SQLAlchemy yet. Classified events are modeled as a domain `Event` behind a new `EventRepository` port, backed by an in-memory adapter — the same incremental pattern `docs/plan/0001-github-app-scaffolding.md` used for `TenantRepository`. Introducing real Postgres persistence is deferred to whichever milestone first needs data to survive a restart for real (most likely ADR 0007's budget calculation, since a rolling 28-day window is meaningless if events vanish on redeploy) — flagged there, not decided here.

**Ownership is explicitly out of scope here.** The `owner` column exists in the target schema, but this milestone's `Event` model leaves it unresolved (`None`/pending). ADR 0006 owns filling it in.

**Idempotency.** GitHub redelivers webhooks on timeout/retry. Classification dedupes on `(installation_id, repo, sha, event_type)` so a redelivered `check_run` or `push` doesn't produce a second event for the same failure.

## Consequences

- New `EventType` enum (`domain/models/event_type.py`): `BUILD_FAILURE`, `REVERT` for now — ADR 0010 and ADR 0011 (v2 items) will each add one more value later, see the forward-compatibility note in ADR 0007.
- New `Event` model (`domain/models/event.py`, one class per file per `CLAUDE.md` convention): `installation_id`, `repo`, `sha`, `event_type`, `owner: str | None`, `ts`.
- New `EventRepository` port (`domain/ports/event_repository.py`) and in-memory adapter (`adapters/memory/event_repository.py`).
- New `EventClassifier` domain service (`domain/event_classifier.py`), pure Python, no FastAPI/Celery/PyGithub imports per the hexagonal boundary rule.
- `src/mergency/api/webhooks.py`'s `push`/`check_run` branches stop being log-only no-ops and instead enqueue the new job type.
- This ADR does not implement anything yet — it unblocks a future `docs/plan/000X-event-classification.md` that will break this down task-by-task, TDD-first, the same way `docs/plan/0001-github-app-scaffolding.md` did.
