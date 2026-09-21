# GitHub Pages Landing Page Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. This plan is static-content-only (no Python/tests) — each step is a content/config file plus a manual verification command, following the shape of `docs/plan/0020-grafana-error-budget-dashboard.md` rather than the TDD shape used for application code.

**Goal:** Publish a single-page, dark-mode, technical/minimalist showcase site on GitHub Pages explaining what Mergency does — problem first, then how it works, then a demo GIF, then guardrails.

**Architecture:** A Jekyll site living directly under `/docs` (GitHub Pages' native source folder), excluding the existing `docs/adr/`, `docs/plan/`, and `docs/devops/` directories from the build via `_config.yml`. No new application code, no CI changes — GitHub Pages builds and serves the site automatically once repo settings point Pages at `main` / `/docs`.

**Tech Stack:** Jekyll (GitHub Pages' built-in engine), plain CSS (no framework), one illustrative demo GIF built as an HTML/CSS mockup and recorded via the Claude Browser tool.

---

## Status

proposed

## Context

`docs/adr/0024-github-pages-landing-page.md` decided the shape of this work: showcase page (not a conversion funnel), problem-before-product content order, a stylized illustrative demo GIF (no real dogfooding capture exists yet), dark-mode technical visual style, Jekyll as the engine, and `/docs` as the Pages source with `adr`/`plan`/`devops` excluded from the Jekyll build. This plan implements that decision.

The visual style (colors, layout) was validated during brainstorming against a mockup — see the ADR's "Visual style" section for the exact palette (`#0d1117` background, `#3fb950`/`#d29922`/`#f85149` budget-health accents).

## Directory structure (additions only)

```
docs/
├── _config.yml            # NEW — Jekyll config, exclude: [adr, plan, devops]
├── index.md                # NEW — the single page: hero, why, how it works, demo, guardrails, footer
├── _layouts/
│   └── default.html        # NEW — page shell (head, nav, footer), dark theme
├── assets/
│   ├── style.css            # NEW — dark-mode styles, budget-health color tokens
│   └── demo.gif             # NEW — recorded illustrative demo (build failure → budget shrinks → PR comment)
└── adr/, plan/, devops/     # UNCHANGED — excluded from Jekyll build
```

## Implementation steps

### Step 1: Jekyll config with exclusions

**Files:** Create `docs/_config.yml`

```yaml
title: Mergency
description: Your team's error budget, applied to pull requests.
theme: null
exclude:
  - adr
  - plan
  - devops
  - README.md
```

`README.md` here refers to any stray root-level readme Jekyll might otherwise try to render inside `/docs` — there is none today, but excluding it preempts future collisions since `docs/adr`/`docs/plan` files sometimes reference a `README.md` pattern in other projects.

**Verification:**
```bash
docker run --rm -v "$PWD/docs:/site" -w /site jekyll/jekyll:4 jekyll build --destination /tmp/_site_check
ls /tmp/_site_check | grep -v -E '^(adr|plan|devops)$'
```
Confirms Jekyll builds successfully and the output does not include rendered `adr`/`plan`/`devops` content.

### Step 2: Page shell and dark-mode styles

**Files:** Create `docs/_layouts/default.html`, `docs/assets/style.css`

`_layouts/default.html` — minimal HTML shell (`<head>` with title/description from front matter, a `<nav>` with the Mergency name + a link to the GitHub repo, `{{ content }}`, a `<footer>` with a repo link). Loads `assets/style.css`.

`assets/style.css` — dark theme tokens matching the ADR's palette:
```css
:root {
  --bg: #0d1117;
  --text: #c9d1d9;
  --text-secondary: #8b949e;
  --budget-healthy: #3fb950;
  --budget-shrinking: #d29922;
  --budget-critical: #f85149;
  --border: #30363d;
}
body { background: var(--bg); color: var(--text); font-family: -apple-system, sans-serif; }
code, .mono { font-family: ui-monospace, monospace; }
```
Plus layout rules for the sections defined in Step 3 (hero spacing, section max-width, budget-bar component).

**Verification:** `docker run --rm -v "$PWD/docs:/site" -p 4000:4000 jekyll/jekyll:4 jekyll serve --host 0.0.0.0`, open `http://localhost:4000`, confirm dark background renders (page will be mostly empty until Step 3).

### Step 3: Page content — hero, why, how it works, guardrails, footer

**Files:** Create `docs/index.md`

Front matter sets `layout: default`. Body content, in order:
1. **Hero** — H1 ("Your team's error budget, applied to pull requests.") + one-line subtitle, pulled/adapted from `README.md`'s framing.
2. **Why** — the problem: AI-assisted coding multiplying PR volume, more CI noise, more broken `main`, no objective signal to slow down. Adapted from `README.md`'s "Why" section.
3. **How it works** — 4 numbered steps (watch default branch → attribute via CODEOWNERS → compute rolling 28-day budget → comment on PR), adapted from `README.md`'s "How it works" section.
4. **Demo** — a placeholder `<img>` pointing at `assets/demo.gif` (added in Step 4), with a one-line caption.
5. **Guardrails** — "What it deliberately doesn't do" bullet list, adapted from `README.md`.
6. **Footer link** — link to `https://github.com/ferminhg/mergency`.

**Verification:** Reload `http://localhost:4000` (Jekyll serve from Step 2), read through all 6 sections, confirm no broken internal links and all copy matches the ADR's approved structure.

### Step 4: Demo GIF mockup and recording

**Files:** Create `docs/assets/demo.gif` (binary, recorded — no source file checked in for the mockup HTML itself, since it's a one-off recording aid, not part of the published site)

Build a temporary local HTML mockup (in the session scratchpad, not committed) matching the style validated in brainstorming: a stylized budget bar (green → amber → red) and a bot PR comment, styled with the same CSS tokens as `assets/style.css`. Sequence: (1) build passes, budget healthy/green, (2) build fails on `main`, (3) budget bar shrinks and turns amber, (4) bot comment appears on a PR. Record the sequence via the Claude Browser tool (screenshots at each step) and assemble into `docs/assets/demo.gif`.

**Verification:** Reload `http://localhost:4000`, confirm the GIF plays inline in the Demo section and file size is reasonable (target well under 5 MB so the page loads fast).

### Step 5: Enable GitHub Pages and verify live

**Files:** None (repo settings change, not version-controlled) — this step is a manual action, documented here so it isn't forgotten.

In the repo's GitHub settings → Pages, set source to branch `main`, folder `/docs`. This is a one-time manual setting; nothing to commit.

**Verification:** After GitHub finishes its build (check the Pages deployment status in the repo's Actions/Environments tab), visit the published URL (`https://ferminhg.github.io/mergency/`) and confirm the page matches the local `jekyll serve` preview, including the demo GIF.

## Verification (end-to-end)

1. `docker run --rm -v "$PWD/docs:/site" -p 4000:4000 jekyll/jekyll:4 jekyll serve --host 0.0.0.0` — full local preview, all 6 sections present, GIF plays, dark theme renders correctly.
2. `docker run --rm -v "$PWD/docs:/site" -w /site jekyll/jekyll:4 jekyll build --destination /tmp/_site_check && ls /tmp/_site_check` — confirm `adr/`, `plan/`, `devops/` are absent from the build output.
3. Live check at the published GitHub Pages URL once Step 5's settings change propagates.
