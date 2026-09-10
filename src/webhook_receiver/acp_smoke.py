"""Manual real-opencode smoke for the ACP host (NOT run by validation/CI).

Drives one envelope through the real ``AcpHost`` → ``opencode acp`` path
against a scratch workspace and prints the EventStore stream plus the final
outcome. Since Phase 3 the envelope carries the BUILT orchestration prompt
(``prompt_builder.build_orchestration_prompt``) by default, so the smoke
shows the real session receiving the open-ended orchestration direction.
Exit code 0 on ``end_turn``, 1 otherwise.

Usage (from the repo root):

    OS_WEBHOOK_SECRET=unused-by-smoke .venv/bin/python -m webhook_receiver.acp_smoke \\
        [--repo owner/repo] [--event issues] [--action labeled]
        [--label orchestration:plan-approved] [--delivery-id smoke-1]
        [--prompt TEXT]

ACP host knobs come from the environment like the service (``ACP_ENABLED`` is
ignored — the smoke always runs the host; set ``ACP_OPENCODE_BIN``,
``ACP_WORKSPACE_ROOT``, ``ACP_DENY_PATTERNS``, ``ACP_DENIED_TOOLS``,
``ACP_DEFAULT_PERMISSION``, timeouts as needed). A transcript of the emitted
events prints to stdout; no secrets are involved (the webhook secret is
never used by the smoke).
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from typing import Any

from webhook_receiver.acp_host import AcpHost, AcpHostError
from webhook_receiver.config import Settings
from webhook_receiver.event_store import EventStore
from webhook_receiver.prompt_builder import build_orchestration_prompt
from webhook_receiver.prompt_queue import PromptInfo


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="python -m webhook_receiver.acp_smoke",
        description=__doc__.splitlines()[0],
    )
    parser.add_argument("--repo", default="owner/repo")
    parser.add_argument("--event", default="issues")
    parser.add_argument("--action", default="labeled")
    parser.add_argument("--label", default="orchestration:plan-approved")
    parser.add_argument("--delivery-id", default="smoke-1")
    parser.add_argument(
        "--prompt",
        default=None,
        help="override the built orchestration prompt (prompt-shape experiments)",
    )
    return parser.parse_args(argv)


def build_settings() -> Settings:
    """Service env parsing without the webhook secret requirement.

    The smoke never serves webhooks, so a placeholder secret stands in when
    ``OS_WEBHOOK_SECRET`` is unset; every ACP_* env var still applies.
    """
    os.environ.setdefault("OS_WEBHOOK_SECRET", "smoke-unused")
    return Settings.from_env()


def build_envelope(args: argparse.Namespace) -> PromptInfo:
    info = PromptInfo(
        delivery_id=args.delivery_id,
        repo=args.repo,
        event=args.event,
        action=args.action,
        label=args.label,
        payload={"smoke": True},
    )
    # Phase 3 default: the envelope carries the built orchestration prompt;
    # --prompt overrides it (mirrors what the listener now enqueues).
    return info.model_copy(
        update={"prompt": args.prompt or build_orchestration_prompt(info)}
    )


class PrintingStore(EventStore):
    """EventStore that echoes every emit to stdout as it lands."""

    def emit(self, event_type: str, **data: Any) -> None:
        print(f"[event] {event_type}: {data}", flush=True)
        super().emit(event_type, **data)


async def run(args: argparse.Namespace) -> int:
    store = PrintingStore()
    info = build_envelope(args)
    host = AcpHost(build_settings(), store)
    print(f"[smoke] envelope id={info.id} delivery_id={info.delivery_id}", flush=True)
    result = await host.run(info)
    print(
        f"[smoke] outcome session_id={result.session_id} "
        f"stop_reason={result.stop_reason} workspace={result.workspace}",
        flush=True,
    )
    return 0 if result.stop_reason == "end_turn" else 1


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        return asyncio.run(run(args))
    except AcpHostError as exc:
        print(f"[smoke] FAILED: {exc}", file=sys.stderr, flush=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
