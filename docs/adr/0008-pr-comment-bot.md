# PR comment bot

With `BudgetStatus` computable per owner (ADR 0007) and ownership resolvable from a set of changed files (ADR 0006, already built for events — reused here for PRs), this ADR covers closing README's core loop: step 4, "When a PR touches an owner with a shrinking budget, Mergency comments on the PR with the current status." This is the first user-visible output the whole system produces.

## Status

📋 proposed

## Considered Options

**Trigger.** `pull_request` webhooks, `action` in `opened`/`synchronize`/`reopened`. Routed through the existing data-plane queue as a new job type (e.g. `evaluate_pr_budget`), same one-queue-with-job-types pattern as every other activity event.

**Resolving which owners a PR touches.** Reuses ADR 0006's `OwnershipResolver`, but against the PR's full changed-file list (via the Pull Request Files API) rather than a single commit's diff — a PR can span many commits.

**Only comment when there's something to say.** For each touched owner, look up `BudgetStatus` (ADR 0007). If **no** touched owner is at or below `warn_threshold_pct`, post no comment at all — matches README's "visibility where the team already looks" framing; an all-green PR shouldn't get bot noise. If at least one touched owner is shrinking, post a single comment listing only the shrinking owners (healthy touched owners are omitted from the comment body, not just from the trigger condition).

**Idempotent updates, not duplicate comments.** Every bot comment carries a hidden marker (`<!-- mergency:budget-status -->`). On each trigger, the bot searches existing PR comments for that marker via the Issue Comments API and edits it in place instead of posting a new one — a PR can receive many `synchronize` events over its life, and one bot comment per PR is the expected UX.

**Recovery case.** If a PR previously got a warning comment and a later `synchronize` shows all touched owners now healthy, the existing marked comment is **updated** to a short "budget recovered" note rather than deleted — deleting would remove the audit trail of what happened on that PR; leaving a stale warning untouched would be actively misleading.

## Consequences

- New domain service `domain/pr_budget_evaluator.py`, composing `OwnershipResolver` (ADR 0006) and `BudgetCalculator` (ADR 0007) — no new domain concepts of its own beyond that composition.
- New adapter `adapters/github/pr_comment_client.py` wrapping the cached installation token to search/create/update issue comments.
- `src/mergency/api/webhooks.py`'s currently-generic `pull_request` handling (today just logged, per Task 5 of `docs/plan/0001-github-app-scaffolding.md`) gets a real dispatch branch.
- Comment body format (markdown table: team, window, consumed/limit, remaining %, status emoji) is a first cut; wording/format is expected to be tuned after real usage, not treated as a frozen contract by this ADR.
- Not implemented yet — unblocks a future implementation plan.
