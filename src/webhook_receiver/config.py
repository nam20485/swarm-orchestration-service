from __future__ import annotations

import os
from dataclasses import dataclass

# GitHub webhook payloads are capped at 25 MB.
_DEFAULT_MAX_BODY_BYTES = 25 * 1024 * 1024


@dataclass(frozen=True)
class Settings:
    """Listener settings (trimmed port of the old orchestrator-service config).

    Only the webhook-listener surface survives Phase 0.0; the dispatch,
    watchdog, beads, and dashboard fields are dropped — they are replaced by
    the PromptInfo queue (Phase 1) and the ACP host (Phase 2).
    """

    host: str
    port: int
    github_webhook_secret: str
    max_body_bytes: int
    log_level: str

    @classmethod
    def from_env(cls) -> Settings:
        secret = os.environ.get("OS_WEBHOOK_SECRET", "").strip()
        if not secret:
            raise ValueError(
                "OS_WEBHOOK_SECRET is required (GitHub App webhook secret)."
            )

        return cls(
            host=os.environ.get("WEBHOOK_HOST", "0.0.0.0"),
            port=int(os.environ.get("WEBHOOK_PORT", "8080")),
            github_webhook_secret=secret,
            max_body_bytes=int(
                os.environ.get("WEBHOOK_MAX_BODY_BYTES", str(_DEFAULT_MAX_BODY_BYTES))
            ),
            log_level=os.environ.get("WEBHOOK_LOG_LEVEL", "info").lower(),
        )
