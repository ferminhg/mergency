# Flaky test signal (v2)

README lists flaky-test detection as a v2 signal, explicitly separate from the v1 error definitions ADR 0005 implements. Right now, every `check_run` failure/timeout counts as a `build_failure`, with no distinction between "the code is actually broken" and "CI infrastructure is noisy." This ADR sketches the direction early — before any v1 pieces are built — purely so ADR 0005's `EventType` enum and ADR 0007's budget-counting logic are designed to leave room for it, not because this is being implemented now.

## Status

📋 proposed (v2 — direction only, not scheduled against v1 work)

## Considered Options

**Detection heuristic.** The same commit SHA producing multiple `check_run` deliveries for the same check name with a differing `conclusion` (e.g. `failure` then `success` on a re-run, with no new commit in between) is the simplest signal that the failure was flaky rather than a real break. This needs correlating multiple webhook deliveries for the same `(sha, check_name)` pair, which ADR 0005's classifier doesn't currently do (it classifies each delivery independently).

**Effect on budget: exclude, don't just weight down.** A flaky-test event should stay **visible** (teams should still be able to see how much CI noise they're dealing with — matches README's "turn noise into a budget you can act on" framing) but should **not** consume budget, since the whole point is not to penalize a team for infrastructure flakiness the way a real break is penalized. This is why ADR 0007 designed `BudgetCalculator` around an explicit allow-list of counted event types rather than "count everything" — adding `EventType.FLAKY_TEST` later must not silently start draining budgets.

**Left open, deliberately.** The exact re-run correlation window (how long after the first failure does a differing-conclusion re-run still count as "the same incident"?), how many re-runs are needed before something is confidently "flaky" versus "fixed on retry," and whether non-GitHub-native CI systems reporting through `check_run` need different handling. None of this is decided here — it depends on real v1 data (from ADR 0005-0007) that doesn't exist yet.

## Consequences

- No code changes from this ADR. It exists to reserve the name `EventType.FLAKY_TEST` and to record the "allow-list, not deny-list" requirement it places on ADR 0007's `BudgetCalculator`, so that ADR isn't implemented in a way that has to be revisited later.
- Actual implementation is deferred until v1 (ADR 0005-0009) is live and the team has real failure data to validate the re-run-correlation heuristic against.
