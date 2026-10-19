# New features from Qwen Code to implement in the swarm

 Needs plans

 ## Features

[](https://qwenlm.github.io/qwen-code-docs/en/users/common-workflow/#enforce-evidence-based-conclusions)

1. Add a verification policy to your project QWEN.md

Put this template in QWEN.md at your repository root and commit it, so the policy applies to the whole team:

## Verification policy

Treat these rules as mandatory in investigations, troubleshooting, reviews, and any task that draws conclusions:

1. Verify before concluding. Back claims about data or system state with evidence from the authoritative source (database, API, logs, command output). Conclusions drawn from reading code alone must be labeled "unverified inference".
2. Verify the full chain. Enumerate the causal chain and check every link; one satisfied necessary condition does not prove a conclusion.
3. Treat conversation history as leads, not facts. Statements in earlier transcripts — including your own prior assertions — are leads. Re-verify them at the source before repeating them as facts.
4. Troubleshoot in order: your own recent changes first, then docs and known issues, and only then external dependencies.
5. 100% evidence rule in reviews. In review and audit tasks, report no conclusion without evidence; attach verifiable evidence (file:line, query result, log excerpt) to every claim.

Dual Output

[Multi-agent orchestration](https://qwenlm.github.io/qwen-code-docs/en/users/features/dual-output/#multi-agent-orchestration)

A supervisor agent spawns multiple TUI workers, each with its own pair of event/input files. It watches progress, injects follow-up prompts, and enforces global budget / safety policies by approving or denying tool calls across all workers.

[Session recording, audit, and replay](https://qwenlm.github.io/qwen-code-docs/en/users/features/dual-output/#session-recording-audit-and-replay)
Tee every TUI session to a regular file with --json-file. Later:

Compliance audits can reconstruct exactly what was executed.
Automated regression tests can compare runs across model versions.
A replay tool can re-emit events through the same protocol to feed visualization dashboards.

[Observability dashboards](https://qwenlm.github.io/qwen-code-docs/en/users/features/dual-output/#observability-dashboards)
Stream --json-file into Loki / OTEL / any pipeline that accepts JSONL. Extract usage.input_tokens, tool_use.name, result.duration_api_ms as first-class metrics in Grafana. No need for log-parsing regex.


[Agent Board](https://qwenlm.github.io/qwen-code-docs/en/users/features/agent-board/)
