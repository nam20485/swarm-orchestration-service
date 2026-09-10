"""ACP permission policy (Phase 2, plan §5 Decision 3 — acpx shape, fail-closed).

The host is the permission authority over ACP: every
``session/request_permission`` is answered automatically here, because a
headless host cannot escalate to a human. The policy:

1. **Deny-list first**: a case-insensitive regex match of any configured
   ``Settings.acp_deny_patterns`` against the requested tool's title or raw
   input rejects the request, regardless of tool kind. An invalid pattern
   never matches (and is rejected at boot by ``Settings.from_env``).
2. **Read-only tool kinds** (``read``, ``search``, ``think``, ``fetch`` per
   the ACP ``ToolKind`` enum) are auto-allowed with ``allow_always`` — the
   acpx ``approve-reads`` default.
3. **Everything else** falls back to ``Settings.acp_default_permission``
   (``reject`` by default, or ``allow_once`` when an operator explicitly
   opts in).

Option selection maps the chosen action onto the best offered option kind
and fails closed: if the agent offers no option of the wanted family, the
request is dismissed (``DeniedOutcome(cancelled)``), which opencode treats
as a denial (spike: tool → ``failed``, no hang). Belt-and-braces layer:
``Settings.acp_denied_tools`` is written into the workspace ``opencode.json``
so opencode removes those tools pre-prompt entirely (see
``webhook_receiver.acp_host``).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from acp.schema import AllowedOutcome, DeniedOutcome, RequestPermissionResponse

if TYPE_CHECKING:
    from webhook_receiver.config import Settings

# Tool kinds that only inspect state; safe to auto-approve headless.
READ_TOOL_KINDS = frozenset({"read", "search", "think", "fetch"})

_REJECT_KINDS = ("reject_once", "reject_always")


@dataclass(frozen=True)
class PermissionDecision:
    """What the host will answer for one permission request, and why."""

    action: str  # "allow_always" | "allow_once" | "reject"
    reason: str


def decide(tool_call: Any, settings: Settings) -> PermissionDecision:
    """Classify one permission request (fail-closed on any surprise).

    ``tool_call`` is the ACP ``ToolCallUpdate`` carried by the request; all
    fields are optional per protocol, so missing/malformed input falls back
    to the configured default rather than guessing.
    """
    kind = getattr(tool_call, "kind", None) or "other"
    title = getattr(tool_call, "title", None) or ""
    raw_input = str(getattr(tool_call, "raw_input", None) or "")
    haystack = f"{title}\n{raw_input}"

    for pattern in settings.acp_deny_patterns:
        try:
            matched = re.search(pattern, haystack, re.IGNORECASE) is not None
        except re.error:
            matched = False  # invalid pattern: skip (from_env rejects these)
        if matched:
            return PermissionDecision("reject", f"deny pattern {pattern!r} matched")

    if kind in READ_TOOL_KINDS:
        return PermissionDecision("allow_always", f"read-only tool kind {kind!r}")

    if settings.acp_default_permission == "allow_once":
        return PermissionDecision(
            "allow_once", "unclassified tool; configured default allow_once"
        )
    return PermissionDecision(
        "reject", f"unclassified tool kind {kind!r}; headless default is reject"
    )


def respond(request_options: list[Any], decision: PermissionDecision) -> Any:
    """Answer a permission request per *decision*, failing closed.

    Picks the best offered option for the decision's action; if none of the
    wanted kinds is offered, dismisses the request (``cancelled``), which
    agents treat as a denial.
    """
    if decision.action == "reject":
        wanted: tuple[str, ...] = _REJECT_KINDS
    elif decision.action == "allow_always":
        wanted = ("allow_always", "allow_once")
    else:  # allow_once
        wanted = ("allow_once", "allow_always")

    for kind in wanted:
        option = next((o for o in request_options if o.kind == kind), None)
        if option is not None:
            return RequestPermissionResponse(
                outcome=AllowedOutcome(outcome="selected", option_id=option.option_id)
            )
    return RequestPermissionResponse(outcome=DeniedOutcome(outcome="cancelled"))
