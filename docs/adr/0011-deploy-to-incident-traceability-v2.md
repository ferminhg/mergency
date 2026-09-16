# Deploy-to-incident traceability (v2)

README lists deploy-to-incident traceability as a v2 signal. v1's error definitions (ADR 0005) only see CI-visible signals — a build failing or a commit being reverted on the default branch — and say nothing about whether a merge that *did* pass CI went on to cause a real production incident. This ADR sketches the direction early, alongside ADR 0010, so v1's `EventType` design leaves room for it.

## Status

✅ accepted (generic incident-reporting endpoint only — see `docs/plan/0016-deploy-to-incident-traceability.md`; the GitHub `deployment_status` webhook path this ADR also sketches remains unimplemented)

## Considered Options

**What counts as a "deploy" here.** No hosting/CD integration is chosen for this project yet (`CLAUDE.md`: "no hosting target chosen yet"), so Mergency can't assume every installed org's deploy pipeline looks the same. Two complementary sources considered: (a) GitHub's native `deployment`/`deployment_status` webhooks, for orgs that use GitHub Deployments, and (b) a generic authenticated `POST /api/v1/installations/{id}/incidents` endpoint (alongside ADR 0009's query API) that an org's own CD pipeline, PagerDuty, or Opsgenie can call directly. Chosen direction: support both rather than picking one, since GitHub Deployments adoption varies a lot across teams and a webhook-only approach would leave many installs with no way to report incidents at all.

**Attribution.** An incident report needs to resolve back to a commit range (the deploy that's suspected of causing it), then to owners via the same CODEOWNERS resolution ADR 0006 already builds — no new ownership logic, just a new input (a commit range instead of a single commit/PR diff).

**New event type, counted (not excluded).** Unlike ADR 0010's flaky-test signal, a confirmed production incident is a real, non-noisy signal — it should count against budget like `BUILD_FAILURE`/`REVERT`, not be excluded like `FLAKY_TEST`. This is exactly why ADR 0007 designed the allow-list as "explicitly list counted types," rather than assuming new types default to either counted or excluded — each new `EventType` states its own budget treatment when it's added.

**Left open, deliberately.** The precise commit-range-to-deploy correlation logic, whether "time to detect" or incident severity (P1 vs P4) should weight budget consumption differently, and what authentication the generic incident-reporting endpoint needs (likely the same per-installation token from ADR 0009, but not decided here). All deferred to the real implementation plan, once this becomes an active priority rather than a v2 placeholder.

## Consequences

- No code changes from this ADR. It reserves the name `EventType.INCIDENT` and records that it is budget-counted by default (contrast with ADR 0010's `FLAKY_TEST`, which is explicitly excluded).
- Actual implementation is deferred until after v1 (ADR 0005-0009) ships and there's a concrete need driving the design of the generic incident-reporting endpoint.

**Update:** `docs/plan/0016-deploy-to-incident-traceability.md` implements the generic `POST /api/v1/installations/{id}/incidents` endpoint, resolving the "left open, deliberately" points above as: attribution covers every commit in the reported range (not just the head), incidents count against budget with no severity weighting (severity is accepted and stored on the request but not yet used in any calculation), and auth reuses ADR 0009's installation-scoped bearer token. The GitHub-native `deployment_status` webhook path is still not implemented.
