# CODEOWNERS-based ownership resolution

ADR 0005 classifies raw webhooks into `Event` records, but leaves `owner` unresolved. This ADR covers the next roadmap item: `ARQUITECTURE.md`'s "Ownership resolver" stage, which turns a classified event into a team owner using the repository's `CODEOWNERS` file, falling back to a tenant-configured default team. This is the roadmap item where README's most important product constraint is load-bearing: **budgets are team/CODEOWNERS-scoped, never individual — non-negotiable, not a v1 limitation.** Every design choice below is shaped by that constraint.

## Status

📋 proposed

## Considered Options

**Introducing tenant configuration.** Nothing before this point has needed a per-tenant `default_team` or rolling-window/budget settings, so `ARQUITECTURE.md`'s `tenant_config` table and "Config resolver" component don't exist in code yet. This ADR is the first to need `default_team`, so it introduces both here: a `TenantConfig` domain model (`installation_id`, `rolling_window_days`, `default_team`, `max_events_per_window`) behind a `TenantConfigRepository` port, populated by a `ConfigResolver` that reads `mergency.yml` from the repo (per README's proposed format) via the GitHub Contents API, falling back to hardcoded defaults when the file is absent or invalid. In-memory adapter for now, consistent with ADR 0005's persistence decision. ADR 0007 (budget calculation) reuses this same config instead of re-deciding it.

**Fetching CODEOWNERS.** Use the cached installation token (already built in `adapters/github/token_manager.py`) to fetch the file via the Contents API, checking GitHub's own three standard locations in order: `CODEOWNERS`, `.github/CODEOWNERS`, `docs/CODEOWNERS`.

**Parsing and matching semantics.** GitHub's CODEOWNERS format is gitignore-style path globbing with **last-matching-pattern-wins** semantics — subtle enough to get wrong by hand-rolling it. Chosen: depend on a small existing library (e.g. the `codeowners` PyPI package) for pattern matching, rather than reimplementing gitignore-glob edge cases ourselves. Considered and rejected: hand-rolling a minimal parser — faster to add zero dependencies, but risks silently wrong ownership on patterns like negation or nested wildcards, which is worse than an extra dependency for a component whose whole job is correctness of attribution.

**Individual owners are never allowed to surface (non-negotiable).** A `CODEOWNERS` line can name an individual (`@someuser`) instead of a team (`@org/team-name`). Per README's constraint, the resolver must never let an individual's handle become an event's stored `owner`. Chosen: when the matched entry is not a team handle, the resolver discards it and falls back to `tenant_config.default_team`, logging that the fallback happened (for operator visibility, not for surfacing anywhere per-author). This check happens in one place — the resolver — so no downstream component (budget calculator, comment bot, historical query) needs to re-implement or even be aware of this rule.

**Which files determine ownership.** An event is tied to a commit SHA. For a `revert` event, ownership is resolved from the files that commit itself changes. For a `build_failure` event (a `check_run` on the default branch), the check run payload doesn't carry a file list, so the resolver looks up the commit's changed files via the Commits API (`GET /repos/{owner}/{repo}/commits/{sha}`).

**One event can resolve to more than one owner.** If the changed files span multiple CODEOWNERS-owned teams, all of them share responsibility for that break — attributing it to only one arbitrarily picked team would understate the signal for the others. Chosen: keep `ARQUITECTURE.md`'s `events` table shape exactly as documented (`owner` stays a single plain column, not an array) by having the resolver **fan out** one classified `Event` into N stored rows, one per distinct resolved owner, all sharing the same `(installation_id, repo, sha, event_type)`. This keeps storage simple and lets ADR 0007's budget query stay a plain `WHERE owner = X` filter.

**Caching parsed CODEOWNERS.** Refetching and reparsing the file on every single event is wasteful. Chosen: cache the parsed rule set per installation with a short TTL (a few minutes), living in Redis next to the installation-token cache. Staleness within that TTL window is accepted for v1 — nobody expects an ownership change to take effect within seconds of a `CODEOWNERS` edit.

## Consequences

- New `TenantConfig` model (`domain/models/tenant_config.py`), `TenantConfigRepository` port, in-memory adapter, and `ConfigResolver` domain service (parses `mergency.yml`, no framework imports beyond what's needed to read repo content through the existing GitHub adapter boundary).
- New `CodeownersProvider` port (`domain/ports/codeowners_provider.py`) and a GitHub-backed adapter (`adapters/github/codeowners_provider.py`) using the `codeowners` library and the cached installation token.
- New `OwnershipResolver` domain service (`domain/ownership_resolver.py`) implementing the individual-vs-team guardrail and the fan-out-to-multiple-rows behavior described above.
- `codeowners` (or the chosen equivalent) is added to `pyproject.toml` as a new runtime dependency.
- `EventRepository` (ADR 0005) gains a way to persist multiple rows per classified event; the in-memory adapter needs no schema change since one row was always the unit of storage.
- Not implemented yet — this ADR unblocks a future `docs/plan/000X-codeowners-ownership-resolution.md`.
