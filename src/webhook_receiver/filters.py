from __future__ import annotations

import os

# ── Transport-level webhook dispatch gate ─────────────────────────────────
# Ported from orchestrator-service @2bd6d06 (webhook_receiver/filters.py,
# dispatch-gate section). The old repo's opencode-stderr trace blacklist that
# shared this module is deliberately NOT ported — it is deleted by the
# simplification plan (docs/plans/orchestrator-service-simplification.md §4).
#
# Hardcoded replica of the GitHub Actions orchestrator-agent.yml
# orchestrate-job ``if:`` guard. The webhook-receiver must only dispatch for
# events the orchestration workflows can actually handle; otherwise the
# default handling would post a comment, which generates a fresh webhook and
# cascades into an echo-loop. This is the single source of truth for which
# webhook deliveries may dispatch the agent.

_EVENT_ALLOW: set[str] = {"issues"}
_ACTION_ALLOW: set[str] = {"labeled"}
# Both colon-prefixed namespaces are dispatch-trigger label spaces: every
# ``orchestration:*`` and ``gh-issue-tracking:*`` label maps to a workflow
# step in the external agent-instructions repo. The gh-issue-tracking
# hierarchy taxonomy uses BARE names (plan/epic/story/task — see skill
# labels.json), so these prefixes never collide with organizational labels.
_LABEL_PREFIXES: tuple[str, ...] = ("orchestration:", "gh-issue-tracking:")
_LABEL_EXACT: set[str] = {"implementation:ready", "implementation:complete"}

# The ``gh-issue-tracking:direct-body`` label dispatches the ENTIRE issue body
# VERBATIM as the agent prompt (no workflow-name parsing or argument
# boundary). The resulting run inherits the orchestration GitHub token, so
# unrestricted access would let anyone with label rights escalate to
# arbitrary privileged-agent execution (a confused-deputy risk). It is
# therefore gated to an explicit allowlist of trusted sender logins (env
# ``DIRECT_BODY_ALLOWED_SENDERS``, comma-separated). When the allowlist is
# unset/empty, direct-body dispatch is fail-closed (rejected).
_DIRECT_BODY_LABEL = "gh-issue-tracking:direct-body"


def _direct_body_allowed_senders() -> set[str]:
    """Lowercased set of trusted senders permitted to use direct-body dispatch.

    Read live from the environment on each call so test/runtime overrides take
    effect without a module reload.
    """
    raw = os.environ.get("DIRECT_BODY_ALLOWED_SENDERS", "")
    return {s.strip().lower() for s in raw.split(",") if s.strip()}


def _is_workflow_label(name: str) -> bool:
    n = (name or "").strip().lower()
    return any(n.startswith(p) for p in _LABEL_PREFIXES) or n in _LABEL_EXACT


def _is_bot_actor(login: str) -> bool:
    """Return True for GitHub App / automation actors (``*[bot]``, ``*-bot``)."""
    n = (login or "").strip().lower()
    return n.endswith("[bot]") or n.endswith("-bot")


def should_dispatch(event: str, payload: dict) -> tuple[bool, str]:
    """Decide whether a webhook delivery may dispatch the orchestrator agent.

    Returns ``(True, "allowed")`` for the exact set the workflows expect:
    ``issues.labeled`` by a non-bot actor with a workflow-relevant label.
    Anything else returns ``(False, "<reason>")`` so the caller can log and
    return ``202 ignored`` without dispatching.
    """
    event = (event or "").lower()
    action = str((payload or {}).get("action") or "").lower()
    if event not in _EVENT_ALLOW:
        return False, f"event {event!r} not dispatched (only issues)"
    if action not in _ACTION_ALLOW:
        return False, f"{event}.{action!r} not dispatched (only labeled)"

    sender = str((payload.get("sender") or {}).get("login") or "")
    if _is_bot_actor(sender):
        return False, f"bot actor {sender!r} skipped (anti-loop)"

    label_name = str((payload.get("label") or {}).get("name") or "")
    if not _is_workflow_label(label_name):
        return False, f"label {label_name!r} not workflow-relevant"

    # direct-body executes the issue body VERBATIM as the agent prompt with
    # the orchestration token. The prompt's direct-body clause matches on the
    # issue's FULL label set, not the triggering label — and a denied
    # direct-body dispatch leaves the label on the issue. A later labeled
    # event with any other workflow label would re-select that clause, so the
    # allowlist must gate on the issue's current labels as well as the
    # trigger: every dispatch that can run the body verbatim requires an
    # explicitly trusted sender. When the allowlist is unset/empty,
    # direct-body dispatch is fail-closed (rejected).
    issue_labels = {
        str(lbl.get("name") or "").strip().lower()
        for lbl in (payload.get("issue") or {}).get("labels") or []
        if isinstance(lbl, dict)
    }
    if _DIRECT_BODY_LABEL in issue_labels or label_name.lower() == _DIRECT_BODY_LABEL:
        allowed_senders = _direct_body_allowed_senders()
        if not allowed_senders:
            return (
                False,
                "direct-body dispatch disabled "
                "(set DIRECT_BODY_ALLOWED_SENDERS to enable)",
            )
        if sender.lower() not in allowed_senders:
            return (
                False,
                f"direct-body dispatch not permitted for sender {sender!r}",
            )
    return True, "allowed"
