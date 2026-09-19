# Dogfood verification: PR budget-status comment

`docs/plan/0018-aws-terraform-dogfood-deployment.md`'s end-to-end verification (point 4) asks for a live check that Mergency posts a budget-status comment on a real PR touching an owner with a shrinking budget. During initial dogfood testing, a plain PR was opened against `ferminhg/mergency` and the `pull_request` webhook was delivered and answered `200`, but **no comment appeared on the PR**. This ADR frames the investigation, not the fix — the root cause isn't known yet.

## Status

📋 proposed

## Considered Options

**Likely explanation: no budget event exists yet for the touched owner.** The PR comment bot (ADR 0008) only comments when the owner resolved for the PR's touched files has a shrinking budget — a fresh installation with zero recorded events has nothing to report, so silence could be entirely correct behavior, not a bug. This needs to be checked *before* assuming anything is broken: query the historical API (ADR 0009) for the relevant owner and confirm there's no budget signal yet.

**Sequencing with ADR 0016.** This verification is easiest to do *after* ADR 0016's manual build-failure + revert exercise creates a real event for some owner — then opening a PR that touches a file under that owner's `CODEOWNERS` entry gives the bot something to react to. Doing this check first, before any event exists, risks a false negative.

**If a budget event does exist and still no comment appears**, the investigation moves to the actual PR comment bot code path (`ADR 0008`) and its webhook dispatch registration (ADR 0014) — checked via `docker compose logs app` on the instance during a real delivery.

## Consequences

- No code changes from this ADR alone — it documents the investigation plan and defers root-causing until ADR 0016's verification produces an owner with a real budget signal.
- Tracked as [issue #41](https://github.com/ferminhg/mergency/issues/41) (the no-comment observation) and [issue #43](https://github.com/ferminhg/mergency/issues/43) (the plan's verification point 4); if a real bug is found in the PR comment bot itself, that becomes a separate, code-changing issue/ADR.
