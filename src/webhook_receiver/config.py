from __future__ import annotations

import os
import re
from dataclasses import dataclass

# GitHub webhook payloads are capped at 25 MB.
_DEFAULT_MAX_BODY_BYTES = 25 * 1024 * 1024

# Host-side autonomy (plan §5 Decision 3): unclassified permission requests
# default to one of these actions. "reject" is the headless-safe default —
# escalate-to-human is not available, so opencode's workspace `permission`
# config (acp_denied_tools) is the pre-prompt belt-and-braces layer.
_ACP_DEFAULT_PERMISSIONS = ("reject", "allow_once")


def _env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


def _env_list(name: str) -> tuple[str, ...]:
    raw = os.environ.get(name, "")
    return tuple(item.strip() for item in raw.split(",") if item.strip())


@dataclass(frozen=True)
class Settings:
    """Listener settings (trimmed port of the old orchestrator-service config).

    The webhook-listener surface (Phase 0.0) plus the ACP-host knobs
    (Phase 2). No model/agent settings exist here on purpose (plan §5
    Decision 10): model routing comes entirely from the driven client's own
    config (e.g. ``opencode.json``), never from the host.
    """

    host: str
    port: int
    github_webhook_secret: str
    max_body_bytes: int
    log_level: str
    # --- ACP host (Phase 2) ---
    acp_enabled: bool = True
    # Empty → resolve via PATH, then ~/.opencode/bin/opencode.
    acp_opencode_bin: str = ""
    # Empty → <system tmpdir>/swarm-acp-workspaces/<envelope id>. The repo
    # itself is never used as the agent cwd (spike convention).
    acp_workspace_root: str = ""
    acp_step_timeout: float = 30.0  # per protocol step (initialize, new_session)
    acp_prompt_timeout: float = 600.0  # per prompt (one cold session per envelope)
    # Unclassified permission requests: "reject" (default, headless-safe) or
    # "allow_once". Read-only tool kinds are always allowed; the deny patterns
    # below always reject.
    acp_default_permission: str = "reject"
    # Regex patterns (case-insensitive) matched against the requested tool's
    # title + raw input; a match rejects the request regardless of tool kind.
    # Invalid patterns are rejected at boot (from_env).
    acp_deny_patterns: tuple[str, ...] = ()
    # Tool names hard-denied pre-prompt via the workspace ``opencode.json``
    # ``permission`` config (belt-and-braces; opencode removes the tool
    # entirely — spikes/acp/README.md deny-config finding).
    acp_denied_tools: tuple[str, ...] = ()

    @classmethod
    def from_env(cls) -> Settings:
        secret = os.environ.get("OS_WEBHOOK_SECRET", "").strip()
        if not secret:
            raise ValueError(
                "OS_WEBHOOK_SECRET is required (GitHub App webhook secret)."
            )

        default_permission = os.environ.get("ACP_DEFAULT_PERMISSION", "reject")
        default_permission = default_permission.strip().lower()
        if default_permission not in _ACP_DEFAULT_PERMISSIONS:
            raise ValueError(
                "ACP_DEFAULT_PERMISSION must be one of: "
                + ", ".join(_ACP_DEFAULT_PERMISSIONS)
            )
        deny_patterns = _env_list("ACP_DENY_PATTERNS")
        for pattern in deny_patterns:
            try:
                re.compile(pattern)
            except re.error as exc:
                raise ValueError(
                    f"ACP_DENY_PATTERNS entry {pattern!r} is not a valid regex: {exc}"
                ) from exc

        return cls(
            host=os.environ.get("WEBHOOK_HOST", "0.0.0.0"),
            port=int(os.environ.get("WEBHOOK_PORT", "8080")),
            github_webhook_secret=secret,
            max_body_bytes=int(
                os.environ.get("WEBHOOK_MAX_BODY_BYTES", str(_DEFAULT_MAX_BODY_BYTES))
            ),
            log_level=os.environ.get("WEBHOOK_LOG_LEVEL", "info").lower(),
            acp_enabled=_env_bool("ACP_ENABLED", True),
            acp_opencode_bin=os.environ.get("ACP_OPENCODE_BIN", "").strip(),
            acp_workspace_root=os.environ.get("ACP_WORKSPACE_ROOT", "").strip(),
            acp_step_timeout=float(os.environ.get("ACP_STEP_TIMEOUT", "30")),
            acp_prompt_timeout=float(os.environ.get("ACP_PROMPT_TIMEOUT", "600")),
            acp_default_permission=default_permission,
            acp_deny_patterns=deny_patterns,
            acp_denied_tools=_env_list("ACP_DENIED_TOOLS"),
        )
