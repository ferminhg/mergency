# Dogfood verification: build failure + revert event recording

`docs/plan/0018-aws-terraform-dogfood-deployment.md`'s end-to-end verification (point 3) asks for a live check that the deployed instance correctly ingests a real build failure and a real revert, and that both show up through the historical query API (ADR 0009) against the right owner. This hasn't been exercised yet against the live dogfood installation — only synthetic events have been tested via the existing pytest suite.

## Status

📋 proposed

## Considered Options

**Manual, one-off exercise (chosen).** Push a commit to `main` that intentionally fails CI (e.g. a `ruff` violation), let the `check_run` webhook fire with `conclusion: failure`, then revert it and let the revert-detection heuristic (ADR 0005) pick it up. Confirm both events land in Postgres with the correct owner (via `CODEOWNERS`, ADR 0006) and that `GET /api/v1/installations/{id}/owners/{owner}/budget` reflects them. This is deliberately manual and non-repeatable — it validates the live deployment once, it doesn't replace the automated test suite.

**Considered and rejected: a scripted smoke test.** Automating this (a script that pushes/reverts and polls the API) would be more repeatable, but building it is disproportionate to a one-time dogfood validation — revisit only if this loop needs to be re-verified regularly (e.g. after infra changes).

**Risk to manage:** pushing directly to `main` on a real (if low-traffic) repo. Use a trivial, easily-revertible change (e.g. a broken lint rule in a throwaway file) so the failure window on `main` is short and unambiguous to clean up.

## Consequences

- No code changes — this ADR just records the intent and shape of a manual verification pass against already-implemented behavior (ADR 0005, 0006, 0007, 0009).
- Tracked as [issue #42](https://github.com/ferminhg/mergency/issues/42) rather than an implementation step, since there's no new code to write.
- If this surfaces a real bug (e.g. an owner misattribution, a missed event), that becomes its own issue/ADR at that point.
