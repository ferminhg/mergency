# Replace the webhook event if/elif chain with a handler registry

`src/mergency/api/webhooks.py`'s `receive_webhook` dispatches on `x_github_event` with a growing `if`/`elif`/`else` chain:

```python
    if x_github_event == "installation":
        await _handle_installation_event(payload, installation_service)
    elif x_github_event == "installation_repositories":
        logger.info("installation_repositories event acknowledged, no-op for now")
    elif x_github_event in ("push", "check_run"):
        classify_activity_event.delay(x_github_event, payload)
    else:
        logger.info(
            "event acknowledged, processing not yet implemented",
            extra={"event": x_github_event},
        )
```

Four branches already, and the roadmap keeps adding webhook-driven work: ADR 0006 (ownership) reads more of `push`, ADR 0010/0011 (flaky test / deploy-to-incident, v2) each imply new GitHub event types feeding the same classifier, and any future event type means editing this function's body again — an open/closed violation that will make this chain longer and harder to scan with every new roadmap item. This ADR decides how to restructure the dispatch so adding an event type is a registration, not an edit to a shared conditional.

## Status

✅ accepted

## Considered Options

- **Handler registry: a `dict[str, Handler]` dispatch table (chosen).** Build a plain `dict` mapping each `x_github_event` string to an async handler callable, and replace the chain with a single `handlers.get(x_github_event, _handle_unimplemented_event)` lookup plus one `await`. This mirrors a pattern already established in this same codebase — `worker/classify_activity_event.py`'s `_PARSERS` dict, which maps `"check_run"`/`"push"` to their parser functions the exact same way — so it's not a new idiom, just applying the existing one consistently at the layer above. Handlers that need a dependency (`_handle_installation_event` needs `installation_service`) are bound via a closure built once per request, after FastAPI resolves `installation_service` through `Depends`; handlers that don't need it (the `installation_repositories` no-op, the `push`/`check_run` activity dispatch, the catch-all) stay plain single-argument functions. This is a Strategy-pattern application via first-class functions rather than a class hierarchy — consistent with this repo's existing preference for plain functions over classes for stateless behavior (the payload parsers, `installation_command_parser.py`).
- **Strategy pattern with a `WebhookEventHandler` Protocol and one class per event type (rejected).** A `Protocol` with a `handle(payload) -> None` method, and one small class per branch (`InstallationEventHandler`, `NoOpEventHandler`, `ActivityEventHandler`), registered in a dict of instances. Rejected: this repo's one-class-per-file convention (`CLAUDE.md`) would multiply into several near-empty classes for what are, in three of four cases, a single log call or a single `.delay()` call — real ceremony for no behavior the plain-function registry doesn't already give. Worth reconsidering only if handlers grow enough shared state or lifecycle to justify instances over functions, which none of the four current branches do.
- **Command pattern mirroring the existing `InstallationCommand` translator (rejected).** Parse every webhook into a typed top-level command (à la `docs/plan/0008-installation-webhook-command-translator.md`'s `InstallationCommand`), then `match`/`case` or dispatch on the command type. Rejected for this layer: the existing `InstallationCommand` translator already operates one level deeper, translating a specific event's *action* into a typed command — duplicating that structure one level up, to translate *event type* into another command layer, adds an extra type hierarchy to route four cases that a dict lookup already routes for free. If a future event type needs meaningfully richer parsing at the top level (not just "call this handler"), revisit this option then.
- **Chain of Responsibility (rejected).** A linked chain of handler objects, each deciding whether to handle or pass along. Rejected: this fits *ordered, overlapping* matching (each handler asks "can I handle this?"), but `x_github_event` dispatch is a flat, mutually-exclusive key lookup — there's no ordering or fallthrough semantics to model, so a chain adds indirection a dict already resolves in O(1) with less code.
- **Leave the if/elif chain as-is (rejected).** Doing nothing keeps a function that already needed a comment-free read-through to verify branch order doesn't matter (it doesn't today, since each `elif` condition is mutually exclusive by construction, but nothing enforces that as more branches are added) and that will keep growing linearly with the roadmap's event types. Rejected because the registry is a small, low-risk, mechanical refactor available now, before ADR 0006/0010/0011's roadmap items each want to add one more branch.

## Consequences

- `src/mergency/api/webhooks.py` gains a small, private, module-level handler registry (or one built inside `receive_webhook` for handlers needing request-scoped dependencies) and loses the `if`/`elif`/`else` chain; `receive_webhook` itself shrinks to signature verification, JSON parsing, one dict lookup, and one `await`.
- Adding a new webhook-driven event type (e.g. whatever ADR 0010/0011 need) becomes: write a handler function, add one entry to the registry — no edit to `receive_webhook`'s existing branches, and no risk of an `elif` chain silently growing unreadable.
- `_handle_installation_event` and `_handle_activity_event`-equivalent behavior for `push`/`check_run` are unchanged in substance — this is a dispatch-shape refactor, not a behavior change. The existing black-box tests in `tests/api/test_webhooks.py` (HTTP-level, asserting status codes and side effects, not the dispatch mechanism itself) should pass unmodified, which also serves as the regression guard for this refactor.
- This ADR does not implement the refactor — it unblocks a follow-up `docs/plan/00XX-*.md` (TDD-first, a single reviewable step: extract handlers, introduce the registry, verify `tests/api/test_webhooks.py` is byte-for-byte unchanged and still green).
