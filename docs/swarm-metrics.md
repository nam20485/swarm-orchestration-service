# Swarm Metrics

Persistent telemetry for swarm runs in THIS repo. Appended by the `swarm-analyst` worker after each wave: one row per subagent session, anomalies per run with proposed fixes. Token columns come from `metadata.json` `usage`; note that `inputTokens` is dominated by `cacheReadTokens` (cached context re-reads, ~90-97% observed) — judge real generation cost by `outputTokens` and judge focus by tool calls + duration.

The historical baseline (run-20260906-225248, which proved the task-input patterns cited in `.zcode/agents/swarm-orchestrator.md` and `.agents/rules/swarm.md`) lives upstream in `nam20485/swarm-context` → `docs/swarm-metrics.md`.
