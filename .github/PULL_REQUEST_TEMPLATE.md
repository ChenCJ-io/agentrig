## Why / 动机

<!-- What user or engineering problem does this solve? Link the issue when available. -->

## What changed / 改动

<!-- Summarize the behavior, API, data, UI, documentation, or workflow changes. -->

## Boundaries and risk / 边界与风险

<!-- What is intentionally out of scope? Note compatibility, migration, permissions, evidence integrity, and rollback. -->

## Verification / 验证

<!-- Replace or extend this list with the commands actually run. -->

- [ ] `uv run ruff check src tests scripts examples`
- [ ] `uv run mypy src/agentrig`
- [ ] `uv run pytest`
- [ ] If `web/` changed: typecheck, coverage, E2E, and build pass
- [ ] If execution/evidence changed: Reference Demo and evidence validation pass
- [ ] User-visible behavior includes a screenshot or evidence reference
- [ ] Documentation and changelog are updated when needed
- [ ] No secrets, private data, generated caches, or local paths are included

## Evidence / 证据

<!-- Add redacted logs, screenshots, Run IDs, or before/after output. -->

## Related issue

<!-- Closes #123 -->
