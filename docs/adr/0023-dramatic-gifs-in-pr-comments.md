# Dramatic GIFs in the PR comment bot 🎭

ADR 0008 shipped the PR comment bot with a plain markdown table (team, window, consumed/limit, remaining %, status emoji), explicitly flagged as "a first cut ... expected to be tuned after real usage." This ADR is that tuning: make the comment harder to ignore when a team's budget is shrinking, by adding a GIF and a more dramatic headline for warn/breach states.

## Status

📋 proposed

## Considered Options

**When it fires: only on warn/breach, not on recovery.** The GIF and dramatic headline only appear when at least one touched owner is at `warn_threshold_pct` or below (the same condition ADR 0008 already uses to decide whether to comment at all). The "budget recovered" comment (ADR 0008's recovery case) stays sober — no GIF, calm wording — so recovery reads as relief, not another attention grab.

**GIF source: Giphy API, searched live by severity keyword.** Each severity maps to a search term (e.g. `warn` → `"alarm"`, `breach` → `"disaster"`), and the bot calls Giphy's search endpoint at comment time to pick a result — favoring variety over a small fixed set. This is an external adapter (`adapters/giphy/giphy_client.py`), same pattern as the existing GitHub adapters: domain code only asks for "a GIF URL for this severity," never touches HTTP or the Giphy API shape directly.

**Giphy failure fallback: a hardcoded GIF per severity, not a silent drop.** If the Giphy call fails or is rate-limited, the bot falls back to one fixed GIF URL per severity level (configured alongside the rest of the bot's settings) rather than posting the comment without an image. This keeps the "dramatic" framing intact even when the external call fails, at the cost of a small, curated fallback asset list to maintain. The comment itself is never blocked or delayed waiting on Giphy — a short timeout applies, and a failure (or timeout) goes straight to the fallback.

**Headline tone: gif + more dramatic wording, scaled by severity.** Beyond the image, the comment's headline changes with severity — e.g. a warn state gets something like "⚠️ Budget getting tight for `<owner>`", a breach state gets "🚨 Budget blown for `<owner>`". This is a wording change only: the existing markdown table (team, window, consumed/limit, remaining %) stays as-is underneath the headline and GIF. Exact copy is expected to be iterated on in code, same spirit as ADR 0008's "wording is a first cut."

**Severity mapping reused, not reinvented.** "Severity" here is derived from the same `BudgetStatus` (ADR 0007) the bot already computes per owner — this ADR does not introduce a new severity concept, just a GIF keyword and a headline string per existing status value.

## Consequences

- New adapter `adapters/giphy/giphy_client.py`: wraps Giphy's search endpoint, takes a severity keyword, returns a GIF URL or raises/times out to let the caller fall back.
- New config: a Giphy API key (env var, following the same pattern as other secrets — never hardcoded) and a small fallback-GIF-URL-per-severity table, alongside the bot's existing settings.
- `domain/pr_budget_evaluator.py` (ADR 0008) or the comment-formatting step gains a severity → (headline, GIF keyword) mapping; the domain layer still must not import the Giphy adapter directly — it asks a port for "a GIF for this severity," per the hexagonal architecture rule in `CLAUDE.md`.
- Comment body format changes (headline wording, image embed) — no schema/API contract is broken, since ADR 0008 already treated the comment body as unversioned and tunable.
- Out of scope: a UI/config knob for teams to opt out of GIFs, and any Giphy content moderation beyond Giphy's own API defaults — both left as future follow-ups if they turn out to matter.
- Not implemented yet — unblocks a future implementation plan.
