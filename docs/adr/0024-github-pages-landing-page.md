# GitHub Pages landing page for Mergency 🌐

Mergency has no public-facing explanation of what it does beyond `README.md`. This ADR decides how to build a small showcase landing page, hosted on GitHub Pages, that explains the problem and the product without requiring anyone to read the README's full technical framing.

## Status

✅ accepted

## Considered Options

**Purpose: showcase/portfolio page, not a conversion funnel.** Mergency has no install base to grow yet; this page's job is to explain the product clearly (e.g. to share with other developers, or as a portfolio piece), not to drive GitHub App installs. This shapes every other decision below — no aggressive CTA, no signup flow, no analytics.

**Content order: problem before product.** Considered leading with a demo GIF in the hero (product-first) versus explaining the "why" (AI-assisted coding tripling PR volume, more CI noise, no objective signal to slow down — from `README.md`) before showing the flow. Chose problem-first: a visitor unfamiliar with the "error budget" concept needs the motivation before the mechanism makes sense. Final structure: Hero → Why → How it works (4 steps) → Demo GIF → Guardrails (what it deliberately doesn't do) → Footer.

**Demo asset: an illustrative mockup, not a captured real case.** No real PR exists yet where Mergency's dogfood instance commented on a shrinking budget. Rather than block the page on that happening, the demo is a stylized HTML/CSS illustration (budget bar + bot comment, not a pixel-accurate GitHub UI clone) recorded into a GIF. Trade-off: it's not a live product screenshot, so it will look slightly different from the real bot comment (ADR 0008) — acceptable for a showcase page, and easy to replace once a real case exists.

**Visual style: dark mode, technical/minimalist.** Background `#0d1117`, text `#c9d1d9`/`#8b949e` secondary, monospace for UI/code fragments, sans-serif for prose. Budget-health accent colors reused across the "how it works" section and the demo GIF: green `#3fb950` (healthy), amber `#d29922` (shrinking), red `#f85149` (critical/build failure). Chosen over the emoji-heavy B2 tone used elsewhere in `docs/` — this page is aimed at other engineers evaluating the tool, not at internal contributors reading a runbook.

**Static site engine: Jekyll**, GitHub Pages' natively supported engine — no separate build step or CI job needed to publish. Considered plain HTML/CSS/JS with no generator: rejected only because Jekyll costs nothing extra (GitHub builds it for free) and gives layout reuse (header/footer partials) if the page grows past one file later; the page itself stays a single rendered route either way.

**Location: directly under `/docs`, GitHub Pages source set to `/docs`.** GitHub Pages only allows the publish source to be the repo root or `/docs` — no arbitrary subfolder (e.g. `/docs/site`) is selectable. `/docs` already holds `docs/adr/`, `docs/plan/`, and `docs/devops/` (this project's plan-as-code records, per `CLAUDE.md`). Considered a dedicated `gh-pages` branch to avoid any overlap: rejected as unnecessary process overhead (an extra branch and deploy step) for a single static page. Instead, the site's own files (`index.md`, `_config.yml`, `assets/`) live at the top of `/docs`, and `_config.yml` sets `exclude: [adr, plan, devops]` so Jekyll's build never touches those directories or mixes them into the site's layout.

## Consequences

- New files directly under `docs/`: `_config.yml`, `index.md`, `assets/style.css`, `assets/demo.gif` (plus any Jekyll layout/include files if the page is split for reuse).
- `docs/adr/`, `docs/plan/`, and `docs/devops/` are unaffected — excluded from the Jekyll build by `_config.yml`, still plain markdown read via GitHub's normal file browser, not part of the published site.
- The demo GIF is a maintained illustration, not a live capture. If a real dogfooding case (a real PR where the bot commented on a shrinking budget) becomes available later, replacing `assets/demo.gif` with a real capture is a follow-up, not required now.
- No new backend/application code — this is a static content addition, same spirit as ADR 0018 and ADR 0022's "infrastructure/content only" scope.
- GitHub repo settings need Pages enabled with source = `main` branch, `/docs` folder (manual one-time setting, not something in version control).
