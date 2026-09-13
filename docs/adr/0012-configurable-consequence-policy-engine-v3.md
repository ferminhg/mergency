# Configurable consequence policy engine (v3, opt-in)

README is explicit that Mergency v1/v2 is "deliberately visibility-only" — see its "What it deliberately doesn't do (yet)" section: no merge blocking, no required checks, and "no automatic policy engine... it will be opt-in and configurable, never a default." v3's roadmap item is where a team could eventually opt into automated consequences once their budget shrinks past a threshold. This is the most speculative, furthest-out roadmap item. This ADR exists mainly to fix the non-negotiable guardrails now, in writing, so that no later implementation plan can accidentally ship this as a default behavior.

## Status

📋 proposed (v3 — direction and guardrails only, far from scheduled)

## Considered Options

**Opt-in mechanism.** Policy rules live under a new `policies:` key in `mergency.yml`, absent or empty by default. Chosen: a config-driven allow-list — a policy only ever runs because a team's own committed config explicitly lists it, reviewed the same way any other config change is (a normal PR against `mergency.yml`). No code-level default policy is ever shipped, and no in-app toggle exists that could turn one on outside of that config file.

**Scope of the first cut: reversible, GitHub-native actions only.** Considered actions: posting a Slack/Teams notification, adding a label, requesting a specific reviewer. Explicitly **excluded** from the first cut: anything that blocks a merge or manipulates required status checks. README frames blocking as a deliberate non-goal "for now," not something this ADR should quietly reinterpret as "for v3" — turning budget-based merge blocking on, even opt-in, is a big enough product decision that it needs its own future ADR and explicit product sign-off, not a default bundled into "the policy engine."

**Auditability.** Every action a policy takes is itself logged as a new `EventType.POLICY_ACTION_TAKEN` row, visible through ADR 0009's historical query API — so an opt-in consequence is never a silent side effect; a team can always see what the engine did and when.

**Left open, deliberately.** The rule DSL's exact grammar (threshold comparisons, per-owner vs. tenant-global overrides), rate-limiting of repeated actions, and whether a future ADR ever revisits merge-blocking as an explicit, separately-consented-to opt-in. None of this is decided here.

## Consequences

- No code changes from this ADR. It binds two guardrails on whatever future plan eventually implements this: **(1)** opt-in only, empty/off by default, never a shipped default policy; **(2)** the first cut excludes any merge-blocking or required-status-check action — that would need its own ADR.
- Actual implementation is deferred well past v1/v2 (ADR 0005-0011); this ADR is written now purely to constrain the design space early.
