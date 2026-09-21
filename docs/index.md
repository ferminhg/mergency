---
layout: default
title: Mergency
description: Your team's error budget, applied to pull requests.
---

<section class="hero">
  <h1>Your team's error budget, applied to pull requests.</h1>
  <p>Mergency turns your build-failure and revert rate into a budget your team can track, the same way an SRE error budget turns a reliability target into a policy instead of a metric nobody acts on.</p>
</section>

<section class="section">
  <h2>Why</h2>
  <p>AI-assisted coding has multiplied pull request volume 3x-4x on a lot of teams. More PRs without more review capacity or more local checks means more noise in CI, more broken builds on <code>main</code>, more reverts, and no objective signal to say "let's slow down for a bit" when things get shaky.</p>
  <p>Mergency tracks that noise as a budget that regenerates over time. When the budget runs low, the team sees it right where the work happens: on the pull request.</p>
</section>

<section class="section">
  <h2>How it works</h2>
  <ol>
    <li>Mergency watches your default branch for merges, build failures, and reverts.</li>
    <li>Every event is attributed to an owner, resolved from your <code>CODEOWNERS</code> file (falling back to a configured default team).</li>
    <li>For each owner, Mergency computes how much budget has been consumed in a rolling 28-day window.</li>
    <li>When a PR touches an owner with a shrinking budget, Mergency comments on the PR with the current status.</li>
  </ol>
  <p>No blocking, no required checks, no gating &mdash; just visibility where the team already looks.</p>
</section>

<section class="section">
  <h2>Demo</h2>
  <img src="{{ '/assets/demo.gif' | relative_url }}" alt="Demo of Mergency: a build fails on main, the team's budget bar shrinks, and Mergency comments on a pull request with the current status.">
  <p class="mono" style="color: var(--text-secondary); font-size: 0.9rem;">Build fails on main &rarr; budget shrinks &rarr; Mergency comments on the PR.</p>
</section>

<section class="section">
  <h2>Guardrails</h2>
  <p>What it deliberately doesn't do:</p>
  <ul>
    <li>No merge blocking or required checks based on budget status.</li>
    <li>No individual author-level metrics, ever. Budgets are scoped to teams/CODEOWNERS &mdash; this is a team health signal, not a surveillance tool.</li>
    <li>No automatic policy engine. That's planned, but it will be opt-in and configurable, never a default.</li>
  </ul>
</section>

<section class="section" style="text-align: center;">
  <a href="https://github.com/ferminhg/mergency">View the project on GitHub</a>
</section>
