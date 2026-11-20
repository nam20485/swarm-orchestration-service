// Generated from ../web/data.mjs for the deployed Function. Keep both in sync.
export const SERVICE = {
  "name": "swarm-orchestration-service",
  "version": "0.2.0",
  "repo": "nam20485/swarm-orchestration-service"
};

export const RUNS = [
  {
    "run_id": "9f3c1a2e-71b4-4c8d-9a02-5e6f7a8b9c01",
    "manifest": {
      "repo": "nam20485/swarm-orchestration-service",
      "label": "orchestration:implement",
      "issue": 482,
      "title": "Add retry budget to sandbox provisioning",
      "sender": "nam20485",
      "delivery": "8f3a61d0-2c4e-4b8a-9d71-6e5f4a3b2c01",
      "branch": "feat/482-retry-budget",
      "started_at": "2026-10-24T14:02:11Z",
      "duration_s": 402,
      "queue_wait_s": 0.3,
      "sandbox": "ws-7f3a",
      "session_id": "ses_01J9F3K7Q2",
      "ok": true,
      "stop_reason": "end_turn"
    },
    "events": [
      {
        "id": 1,
        "at": 0,
        "type": "webhook_received",
        "data": {
          "delivery": "8f3a…",
          "event": "issues",
          "action": "labeled",
          "sender": "nam20485"
        }
      },
      {
        "id": 2,
        "at": 0.18,
        "type": "webhook_accepted",
        "data": {
          "delivery": "8f3a…",
          "label": "orchestration:implement",
          "issue": 482
        }
      },
      {
        "id": 3,
        "at": 0.26,
        "type": "prompt_queued",
        "data": {
          "delivery": "8f3a…",
          "queue_depth": 1
        }
      },
      {
        "id": 4,
        "at": 2.61,
        "type": "sandbox_provisioned",
        "data": {
          "workspace": "ws-7f3a",
          "image": "swarm-sandbox:2.4",
          "base": "development"
        }
      },
      {
        "id": 5,
        "at": 3.04,
        "type": "agent_session_started",
        "data": {
          "session_id": "ses_01J9F3K7Q2",
          "agent": "opencode",
          "cwd": "/workspace"
        }
      },
      {
        "id": 6,
        "at": 3.1,
        "type": "user_message_chunk",
        "data": {
          "text": "Implement the retry budget for SwarmSandbox provisioning. Cover exhaustion, backoff jitter, and the release path. Leave the branch ready for review; do not push."
        }
      },
      {
        "id": 7,
        "at": 5.4,
        "type": "agent_thought_chunk",
        "data": {
          "text": "Reading sandbox_bridge.py and its tests before touching the retry loop."
        }
      },
      {
        "id": 8,
        "at": 8.2,
        "type": "agent_tool_call",
        "data": {
          "tool": "read",
          "title": "src/webhook_receiver/sandbox_bridge.py"
        }
      },
      {
        "id": 9,
        "at": 14.7,
        "type": "agent_tool_call",
        "data": {
          "tool": "search",
          "title": "provision( in tests/"
        }
      },
      {
        "id": 10,
        "at": 21.3,
        "type": "agent_plan",
        "data": {
          "entries": [
            {
              "content": "Add bounded exponential backoff",
              "status": "pending"
            },
            {
              "content": "Cover exhaustion in tests",
              "status": "pending"
            },
            {
              "content": "Run the Python gate",
              "status": "pending"
            }
          ]
        }
      },
      {
        "id": 11,
        "at": 44.9,
        "type": "agent_tool_call",
        "data": {
          "tool": "edit",
          "title": "src/webhook_receiver/sandbox_bridge.py",
          "additions": 38,
          "deletions": 6
        }
      },
      {
        "id": 12,
        "at": 96.2,
        "type": "agent_tool_call",
        "data": {
          "tool": "edit",
          "title": "tests/test_sandbox_bridge.py",
          "additions": 61,
          "deletions": 2
        }
      },
      {
        "id": 13,
        "at": 214.8,
        "type": "agent_tool_call",
        "data": {
          "tool": "bash",
          "title": "pytest tests/test_sandbox_bridge.py -q"
        }
      },
      {
        "id": 14,
        "at": 228.6,
        "type": "agent_permission",
        "data": {
          "tool": "bash",
          "title": "git push origin feat/482-retry-budget",
          "decision": "reject",
          "policy": "deny-regex:^git push"
        }
      },
      {
        "id": 15,
        "at": 233.1,
        "type": "agent_plan_update",
        "data": {
          "entries": [
            {
              "content": "Add bounded exponential backoff",
              "status": "completed"
            },
            {
              "content": "Cover exhaustion in tests",
              "status": "completed"
            },
            {
              "content": "Run the Python gate",
              "status": "in_progress"
            }
          ]
        }
      },
      {
        "id": 16,
        "at": 286.4,
        "type": "agent_tool_call",
        "data": {
          "tool": "bash",
          "title": "pwsh ./validation.ps1 -Step python"
        }
      },
      {
        "id": 17,
        "at": 372.2,
        "type": "agent_usage",
        "data": {
          "input_tokens": 184220,
          "output_tokens": 9124,
          "context_window": 200000
        }
      },
      {
        "id": 18,
        "at": 396.7,
        "type": "agent_message_chunk",
        "data": {
          "text": "Implemented a bounded retry budget (3 attempts, 250 ms base, jittered exponential backoff) in sandbox_bridge.py. Added exhaustion coverage and a regression test for release-after-failure. Validation is green; the branch is left locally for review."
        }
      },
      {
        "id": 19,
        "at": 400.4,
        "type": "agent_finished",
        "data": {
          "stop_reason": "end_turn"
        }
      },
      {
        "id": 20,
        "at": 401,
        "type": "sandbox_released",
        "data": {
          "workspace": "ws-7f3a",
          "reason": "session_complete"
        }
      },
      {
        "id": 21,
        "at": 402.1,
        "type": "prompt_consumed",
        "data": {
          "ok": true,
          "stop_reason": "end_turn"
        }
      }
    ]
  },
  {
    "run_id": "7b2e041c-2d51-4c8b-9f6e-2b3c4d5e6f02",
    "manifest": {
      "repo": "nam20485/swarm-orchestration-service",
      "label": "orchestration:investigate",
      "issue": 479,
      "title": "Triage: flaky pytest in event_store fan-out",
      "sender": "nam20485",
      "delivery": "c2d49e13-8a7f-4e0b-b1d6-3f2a5c4e6b02",
      "branch": "triage/479-event-store-flake",
      "started_at": "2026-10-24T13:41:06Z",
      "duration_s": 188,
      "queue_wait_s": 0.2,
      "sandbox": null,
      "session_id": "ses_01J9F3H8R4",
      "ok": true,
      "stop_reason": "end_turn"
    },
    "events": [
      {
        "id": 1,
        "at": 0,
        "type": "webhook_received",
        "data": {
          "delivery": "c2d4…",
          "event": "issues",
          "action": "labeled",
          "sender": "nam20485"
        }
      },
      {
        "id": 2,
        "at": 0.14,
        "type": "webhook_accepted",
        "data": {
          "delivery": "c2d4…",
          "label": "orchestration:investigate",
          "issue": 479
        }
      },
      {
        "id": 3,
        "at": 0.19,
        "type": "prompt_queued",
        "data": {
          "delivery": "c2d4…",
          "queue_depth": 0
        }
      },
      {
        "id": 4,
        "at": 1.24,
        "type": "agent_session_started",
        "data": {
          "session_id": "ses_01J9F3H8R4",
          "agent": "opencode",
          "cwd": "/tmp/opencode/run-7b2e041c"
        }
      },
      {
        "id": 5,
        "at": 1.3,
        "type": "user_message_chunk",
        "data": {
          "text": "Triage the flaky test in tests/test_event_store.py. Do not change production code yet; report the root cause and a minimal fix."
        }
      },
      {
        "id": 6,
        "at": 2,
        "type": "agent_thought_chunk",
        "data": {
          "text": "No sandbox for this label, so I am working against the scratch checkout."
        }
      },
      {
        "id": 7,
        "at": 3.2,
        "type": "agent_tool_call",
        "data": {
          "tool": "read",
          "title": "tests/test_event_store.py"
        }
      },
      {
        "id": 8,
        "at": 11.4,
        "type": "agent_tool_call",
        "data": {
          "tool": "search",
          "title": "fan_out|subscribe"
        }
      },
      {
        "id": 9,
        "at": 19.8,
        "type": "agent_tool_call",
        "data": {
          "tool": "read",
          "title": "src/webhook_receiver/event_store.py"
        }
      },
      {
        "id": 10,
        "at": 47.2,
        "type": "agent_thought_chunk",
        "data": {
          "text": "The ring wraps at 1000 entries while a subscriber queue can still hold 1000. The test publishes 1001 events and assumes both survive, so the first is evicted roughly half the time."
        }
      },
      {
        "id": 11,
        "at": 96.5,
        "type": "agent_thought_chunk",
        "data": {
          "text": "It is not a race in fan-out; the assertion depends on a bounded buffer boundary. Slow CI changes the interleaving and makes it surface."
        }
      },
      {
        "id": 12,
        "at": 154.2,
        "type": "agent_message_chunk",
        "data": {
          "text": "Root cause: the test asserts on event 1 after publishing 1001 events into a 1000-entry ring, so eviction is expected. Minimal fix: assert on the last 1000 events, or shrink the burst to 999. No production change needed."
        }
      },
      {
        "id": 13,
        "at": 180.1,
        "type": "agent_usage",
        "data": {
          "input_tokens": 96412,
          "output_tokens": 3108,
          "context_window": 200000
        }
      },
      {
        "id": 14,
        "at": 187.3,
        "type": "agent_finished",
        "data": {
          "stop_reason": "end_turn"
        }
      },
      {
        "id": 15,
        "at": 188,
        "type": "prompt_consumed",
        "data": {
          "ok": true,
          "stop_reason": "end_turn"
        }
      }
    ]
  },
  {
    "run_id": "4d81f7aa-9c63-4e2a-b7d1-8e9f0a1b2c03",
    "manifest": {
      "repo": "nam20485/swarm-orchestration-service",
      "label": "orchestration:epic",
      "issue": 476,
      "title": "Epic: webhook ingest hardening",
      "sender": "nam20485",
      "delivery": "e91b7c04-5d2a-4f6e-8c13-7a9d2b1e4c03",
      "branch": "epic/476-ingest-hardening",
      "started_at": "2026-10-24T12:58:44Z",
      "duration_s": 271,
      "queue_wait_s": 0.4,
      "sandbox": "ws-2c9d",
      "session_id": "ses_01J9F3G2P8",
      "ok": false,
      "stop_reason": "error",
      "error": "opencode exited with code 137"
    },
    "events": [
      {
        "id": 1,
        "at": 0,
        "type": "webhook_received",
        "data": {
          "delivery": "e91b…",
          "event": "issues",
          "action": "labeled",
          "sender": "nam20485"
        }
      },
      {
        "id": 2,
        "at": 0.22,
        "type": "webhook_accepted",
        "data": {
          "delivery": "e91b…",
          "label": "orchestration:epic",
          "issue": 476
        }
      },
      {
        "id": 3,
        "at": 0.31,
        "type": "prompt_queued",
        "data": {
          "delivery": "e91b…",
          "queue_depth": 1
        }
      },
      {
        "id": 4,
        "at": 2.21,
        "type": "sandbox_provisioned",
        "data": {
          "workspace": "ws-2c9d",
          "image": "swarm-sandbox:2.4",
          "base": "development"
        }
      },
      {
        "id": 5,
        "at": 2.83,
        "type": "agent_session_started",
        "data": {
          "session_id": "ses_01J9F3G2P8",
          "agent": "opencode",
          "cwd": "/workspace"
        }
      },
      {
        "id": 6,
        "at": 2.9,
        "type": "user_message_chunk",
        "data": {
          "text": "Split the ingest hardening epic into ordered sub-issues and start the first slice. Keep the webhook contract unchanged."
        }
      },
      {
        "id": 7,
        "at": 4.1,
        "type": "agent_thought_chunk",
        "data": {
          "text": "Mapping the current gate ordering before proposing slices."
        }
      },
      {
        "id": 8,
        "at": 6.8,
        "type": "agent_tool_call",
        "data": {
          "tool": "read",
          "title": "src/webhook_receiver/app.py"
        }
      },
      {
        "id": 9,
        "at": 9.4,
        "type": "agent_tool_call",
        "data": {
          "tool": "read",
          "title": "src/webhook_receiver/filters.py"
        }
      },
      {
        "id": 10,
        "at": 14.2,
        "type": "agent_tool_call",
        "data": {
          "tool": "search",
          "title": "webhook_"
        }
      },
      {
        "id": 11,
        "at": 30.1,
        "type": "agent_thought_chunk",
        "data": {
          "text": "The signature check and the size guard are already ordered correctly; the epic should focus on replay and delivery-id retention."
        }
      },
      {
        "id": 12,
        "at": 38.4,
        "type": "agent_plan",
        "data": {
          "entries": [
            {
              "content": "Map gate ordering",
              "status": "completed"
            },
            {
              "content": "Draft sub-issue slices",
              "status": "in_progress"
            },
            {
              "content": "Start the replay slice",
              "status": "pending"
            }
          ]
        }
      },
      {
        "id": 13,
        "at": 55.2,
        "type": "agent_tool_call",
        "data": {
          "tool": "read",
          "title": "tests/test_app.py"
        }
      },
      {
        "id": 14,
        "at": 71.8,
        "type": "agent_tool_call",
        "data": {
          "tool": "bash",
          "title": "pytest tests/test_app.py -q"
        }
      },
      {
        "id": 15,
        "at": 72,
        "type": "agent_permission",
        "data": {
          "tool": "bash",
          "title": "git push origin epic/476-ingest-hardening",
          "decision": "reject",
          "policy": "deny-regex:^git push"
        }
      },
      {
        "id": 16,
        "at": 112.6,
        "type": "agent_thought_chunk",
        "data": {
          "text": "The suite passes. Writing the slice breakdown with the replay window caveat called out."
        }
      },
      {
        "id": 17,
        "at": 270,
        "type": "agent_finished",
        "data": {
          "stop_reason": "error"
        }
      },
      {
        "id": 18,
        "at": 270.6,
        "type": "sandbox_released",
        "data": {
          "workspace": "ws-2c9d",
          "reason": "session_error"
        }
      },
      {
        "id": 19,
        "at": 271.2,
        "type": "prompt_consumed",
        "data": {
          "ok": false,
          "stop_reason": "error",
          "error": "opencode exited with code 137"
        }
      }
    ]
  },
  {
    "run_id": "2a6c9e5d-3f84-4b1a-8c2d-9e0f1a2b3c04",
    "manifest": {
      "repo": "nam20485/swarm-orchestration-service",
      "label": "implementation:ready",
      "issue": 471,
      "title": "Implementation: SSE reconnect cursor",
      "sender": "nam20485",
      "delivery": "a73e2f19-6b1d-4c8a-9e52-4d3c2b1a0f04",
      "branch": "feat/471-sse-reconnect-cursor",
      "started_at": "2026-10-24T11:30:19Z",
      "duration_s": 680,
      "queue_wait_s": 0.6,
      "sandbox": "ws-8b1e",
      "session_id": "ses_01J9F3D9M2",
      "ok": true,
      "stop_reason": "end_turn"
    },
    "events": [
      {
        "id": 1,
        "at": 0,
        "type": "webhook_received",
        "data": {
          "delivery": "a73e…",
          "event": "issues",
          "action": "labeled",
          "sender": "nam20485"
        }
      },
      {
        "id": 2,
        "at": 0.2,
        "type": "webhook_accepted",
        "data": {
          "delivery": "a73e…",
          "label": "implementation:ready",
          "issue": 471
        }
      },
      {
        "id": 3,
        "at": 0.28,
        "type": "prompt_queued",
        "data": {
          "delivery": "a73e…",
          "queue_depth": 0
        }
      },
      {
        "id": 4,
        "at": 3.1,
        "type": "sandbox_provisioned",
        "data": {
          "workspace": "ws-8b1e",
          "image": "swarm-sandbox:2.4",
          "base": "development"
        }
      },
      {
        "id": 5,
        "at": 3.6,
        "type": "agent_session_started",
        "data": {
          "session_id": "ses_01J9F3D9M2",
          "agent": "opencode",
          "cwd": "/workspace"
        }
      },
      {
        "id": 6,
        "at": 3.7,
        "type": "user_message_chunk",
        "data": {
          "text": "Implement the approved plan for the SSE reconnect cursor. Keep `Last-Event-ID` handling and cover replay after a missed frame."
        }
      },
      {
        "id": 7,
        "at": 6.2,
        "type": "agent_thought_chunk",
        "data": {
          "text": "Starting with the existing /events tests, then the ring buffer cursor."
        }
      },
      {
        "id": 8,
        "at": 12.8,
        "type": "agent_plan",
        "data": {
          "entries": [
            {
              "content": "Audit SSE id formatting",
              "status": "pending"
            },
            {
              "content": "Add cursor-wide replay",
              "status": "pending"
            },
            {
              "content": "Exercise reconnect in tests",
              "status": "pending"
            },
            {
              "content": "Update the event contract",
              "status": "pending"
            }
          ]
        }
      },
      {
        "id": 9,
        "at": 18.6,
        "type": "agent_tool_call",
        "data": {
          "tool": "read",
          "title": "src/webhook_receiver/app.py"
        }
      },
      {
        "id": 10,
        "at": 31.9,
        "type": "agent_tool_call",
        "data": {
          "tool": "read",
          "title": "tests/test_events.py"
        }
      },
      {
        "id": 11,
        "at": 49.3,
        "type": "agent_tool_call",
        "data": {
          "tool": "search",
          "title": "Last-Event-ID"
        }
      },
      {
        "id": 12,
        "at": 88.4,
        "type": "agent_tool_call",
        "data": {
          "tool": "edit",
          "title": "src/webhook_receiver/event_store.py",
          "additions": 54,
          "deletions": 11
        }
      },
      {
        "id": 13,
        "at": 120.7,
        "type": "agent_plan_update",
        "data": {
          "entries": [
            {
              "content": "Audit SSE id formatting",
              "status": "completed"
            },
            {
              "content": "Add cursor-wide replay",
              "status": "completed"
            },
            {
              "content": "Exercise reconnect in tests",
              "status": "in_progress"
            },
            {
              "content": "Update the event contract",
              "status": "pending"
            }
          ]
        }
      },
      {
        "id": 14,
        "at": 150.2,
        "type": "agent_commands_update",
        "data": {
          "available_commands": [
            {
              "name": "pytest",
              "description": "Run the Python suite"
            },
            {
              "name": "ruff",
              "description": "Lint the receiver package"
            }
          ]
        }
      },
      {
        "id": 15,
        "at": 152.9,
        "type": "agent_mode_update",
        "data": {
          "mode": "code"
        }
      },
      {
        "id": 16,
        "at": 160.4,
        "type": "agent_config_update",
        "data": {
          "options": {
            "model": "agent-default",
            "thought_level": "high"
          }
        }
      },
      {
        "id": 17,
        "at": 240.1,
        "type": "agent_tool_call",
        "data": {
          "tool": "bash",
          "title": "pytest tests/test_events.py -q"
        }
      },
      {
        "id": 18,
        "at": 300.2,
        "type": "agent_plan_removed",
        "data": {
          "reason": "replaced by the approved slice list"
        }
      },
      {
        "id": 19,
        "at": 360.8,
        "type": "agent_tool_call",
        "data": {
          "tool": "edit",
          "title": "tests/test_events.py",
          "additions": 72,
          "deletions": 4
        }
      },
      {
        "id": 20,
        "at": 470.5,
        "type": "agent_plan_update",
        "data": {
          "entries": [
            {
              "content": "Audit SSE id formatting",
              "status": "completed"
            },
            {
              "content": "Add cursor-wide replay",
              "status": "completed"
            },
            {
              "content": "Exercise reconnect in tests",
              "status": "completed"
            },
            {
              "content": "Update the event contract",
              "status": "in_progress"
            }
          ]
        }
      },
      {
        "id": 21,
        "at": 540,
        "type": "agent_tool_call",
        "data": {
          "tool": "edit",
          "title": "src/webhook_receiver/README.md",
          "additions": 9,
          "deletions": 3
        }
      },
      {
        "id": 22,
        "at": 640.2,
        "type": "agent_usage",
        "data": {
          "input_tokens": 412880,
          "output_tokens": 18442,
          "context_window": 200000
        }
      },
      {
        "id": 23,
        "at": 672.4,
        "type": "agent_message_chunk",
        "data": {
          "text": "Reconnect now resumes from the last delivered id: the store replays retained events after the cursor, then resumes live fan-out. Added a test that drops a frame mid-stream and asserts the replay. Contract docs updated."
        }
      },
      {
        "id": 24,
        "at": 679.2,
        "type": "agent_finished",
        "data": {
          "stop_reason": "end_turn"
        }
      },
      {
        "id": 25,
        "at": 679.8,
        "type": "sandbox_released",
        "data": {
          "workspace": "ws-8b1e",
          "reason": "session_complete"
        }
      },
      {
        "id": 26,
        "at": 680.4,
        "type": "prompt_consumed",
        "data": {
          "ok": true,
          "stop_reason": "end_turn"
        }
      }
    ]
  },
  {
    "run_id": "8e5b13f0-6a27-4d3e-9b4f-0c1d2e3f4a05",
    "manifest": {
      "repo": "nam20485/swarm-orchestration-service",
      "label": "gh-issue-tracking:sync",
      "issue": 468,
      "title": "Label namespace reference",
      "sender": "nam20485",
      "delivery": "f04c8a2d-1e6b-4d7c-9a35-8b7c6d5e4f05",
      "branch": "docs/468-label-reference",
      "started_at": "2026-10-24T10:12:02Z",
      "duration_s": 134,
      "queue_wait_s": 0.1,
      "sandbox": null,
      "session_id": "ses_01J9F3B4H6",
      "ok": true,
      "stop_reason": "end_turn"
    },
    "events": [
      {
        "id": 1,
        "at": 0,
        "type": "webhook_received",
        "data": {
          "delivery": "f04c…",
          "event": "issues",
          "action": "labeled",
          "sender": "nam20485"
        }
      },
      {
        "id": 2,
        "at": 0.1,
        "type": "webhook_accepted",
        "data": {
          "delivery": "f04c…",
          "label": "gh-issue-tracking:sync",
          "issue": 468
        }
      },
      {
        "id": 3,
        "at": 0.2,
        "type": "prompt_queued",
        "data": {
          "delivery": "f04c…",
          "queue_depth": 0
        }
      },
      {
        "id": 4,
        "at": 0.94,
        "type": "agent_session_started",
        "data": {
          "session_id": "ses_01J9F3B4H6",
          "agent": "opencode",
          "cwd": "/tmp/opencode/run-8e5b13f0"
        }
      },
      {
        "id": 5,
        "at": 1,
        "type": "user_message_chunk",
        "data": {
          "text": "Refresh the label namespace reference from the issue-tracking hierarchy. Documentation only."
        }
      },
      {
        "id": 6,
        "at": 2.4,
        "type": "agent_thought_chunk",
        "data": {
          "text": "Checking the current namespaces against the live label table."
        }
      },
      {
        "id": 7,
        "at": 4.8,
        "type": "agent_tool_call",
        "data": {
          "tool": "search",
          "title": "orchestration:"
        }
      },
      {
        "id": 8,
        "at": 9.1,
        "type": "agent_tool_call",
        "data": {
          "tool": "read",
          "title": "docs/labels.md"
        }
      },
      {
        "id": 9,
        "at": 30.6,
        "type": "agent_tool_call",
        "data": {
          "tool": "edit",
          "title": "docs/labels.md",
          "additions": 22,
          "deletions": 4
        }
      },
      {
        "id": 10,
        "at": 96.2,
        "type": "agent_message_chunk",
        "data": {
          "text": "Synced the reference: four namespaces (orchestration, gh-issue-tracking, implementation, documentation), with the dispatch rule noted per namespace. No code touched."
        }
      },
      {
        "id": 11,
        "at": 120.4,
        "type": "agent_usage",
        "data": {
          "input_tokens": 42118,
          "output_tokens": 2044,
          "context_window": 200000
        }
      },
      {
        "id": 12,
        "at": 133.1,
        "type": "agent_finished",
        "data": {
          "stop_reason": "end_turn"
        }
      },
      {
        "id": 13,
        "at": 134,
        "type": "prompt_consumed",
        "data": {
          "ok": true,
          "stop_reason": "end_turn"
        }
      }
    ]
  },
  {
    "run_id": "c1a4d7b9-5e08-4a2f-8d6c-7b8a9c0d1e06",
    "manifest": {
      "repo": "nam20485/swarm-orchestration-service",
      "label": "orchestration:implement",
      "issue": 455,
      "title": "Refactor prompt_builder label table",
      "sender": "nam20485",
      "delivery": "b38f1e70-9c4a-4d2b-a6e8-5f4d3c2b1a06",
      "branch": "feat/455-prompt-builder",
      "started_at": "2026-10-23T18:04:37Z",
      "duration_s": 900,
      "queue_wait_s": 0.8,
      "sandbox": "ws-4d2f",
      "session_id": "ses_01J9F2X1C9",
      "ok": false,
      "stop_reason": "timeout",
      "error": "session timed out after ACP_RUN_TIMEOUT_S=900"
    },
    "events": [
      {
        "id": 1,
        "at": 0,
        "type": "webhook_received",
        "data": {
          "delivery": "b38f…",
          "event": "issues",
          "action": "labeled",
          "sender": "nam20485"
        }
      },
      {
        "id": 2,
        "at": 0.25,
        "type": "webhook_accepted",
        "data": {
          "delivery": "b38f…",
          "label": "orchestration:implement",
          "issue": 455
        }
      },
      {
        "id": 3,
        "at": 0.33,
        "type": "prompt_queued",
        "data": {
          "delivery": "b38f…",
          "queue_depth": 2
        }
      },
      {
        "id": 4,
        "at": 2.94,
        "type": "sandbox_provisioned",
        "data": {
          "workspace": "ws-4d2f",
          "image": "swarm-sandbox:2.4",
          "base": "development"
        }
      },
      {
        "id": 5,
        "at": 3.44,
        "type": "agent_session_started",
        "data": {
          "session_id": "ses_01J9F2X1C9",
          "agent": "opencode",
          "cwd": "/workspace"
        }
      },
      {
        "id": 6,
        "at": 3.5,
        "type": "user_message_chunk",
        "data": {
          "text": "Refactor the prompt_builder label table into declarative prompt classes. Preserve every existing label string exactly."
        }
      },
      {
        "id": 7,
        "at": 5.8,
        "type": "agent_thought_chunk",
        "data": {
          "text": "Reading prompt_builder.py and its prompt snapshots first."
        }
      },
      {
        "id": 8,
        "at": 9.7,
        "type": "agent_tool_call",
        "data": {
          "tool": "read",
          "title": "src/webhook_receiver/prompt_builder.py"
        }
      },
      {
        "id": 9,
        "at": 22.3,
        "type": "agent_tool_call",
        "data": {
          "tool": "read",
          "title": "tests/test_prompt_builder.py"
        }
      },
      {
        "id": 10,
        "at": 41.5,
        "type": "agent_tool_call",
        "data": {
          "tool": "search",
          "title": "build_prompt"
        }
      },
      {
        "id": 11,
        "at": 78.2,
        "type": "agent_thought_chunk",
        "data": {
          "text": "The table is also consumed by the direct-body path; the refactor has to keep the verbatim branch."
        }
      },
      {
        "id": 12,
        "at": 140.6,
        "type": "agent_tool_call",
        "data": {
          "tool": "edit",
          "title": "src/webhook_receiver/prompt_builder.py",
          "additions": 96,
          "deletions": 84
        }
      },
      {
        "id": 13,
        "at": 260.9,
        "type": "agent_tool_call",
        "data": {
          "tool": "edit",
          "title": "tests/test_prompt_builder.py",
          "additions": 41,
          "deletions": 12
        }
      },
      {
        "id": 14,
        "at": 420.8,
        "type": "agent_thought_chunk",
        "data": {
          "text": "Snapshot mismatch on the epic class. Re-reading the table to find the drifted string."
        }
      },
      {
        "id": 15,
        "at": 610.2,
        "type": "agent_tool_call",
        "data": {
          "tool": "read",
          "title": "src/webhook_receiver/prompt_builder.py"
        }
      },
      {
        "id": 16,
        "at": 758.4,
        "type": "agent_tool_call",
        "data": {
          "tool": "search",
          "title": "orchestration:epic"
        }
      },
      {
        "id": 17,
        "at": 890.1,
        "type": "agent_usage",
        "data": {
          "input_tokens": 688210,
          "output_tokens": 12740,
          "context_window": 200000
        }
      },
      {
        "id": 18,
        "at": 899.4,
        "type": "agent_finished",
        "data": {
          "stop_reason": "timeout"
        }
      },
      {
        "id": 19,
        "at": 899.8,
        "type": "sandbox_released",
        "data": {
          "workspace": "ws-4d2f",
          "reason": "session_timeout"
        }
      },
      {
        "id": 20,
        "at": 900.2,
        "type": "prompt_consumed",
        "data": {
          "ok": false,
          "stop_reason": "timeout",
          "error": "session timed out after ACP_RUN_TIMEOUT_S=900"
        }
      }
    ]
  },
  {
    "run_id": "e6f2a8c3-1b95-4c7d-a0e3-2f4a5b6c7d07",
    "manifest": {
      "repo": "nam20485/swarm-orchestration-service",
      "label": "orchestration:implement",
      "issue": 488,
      "title": "Wire agent_usage into run manifest",
      "sender": "nam20485",
      "delivery": "7c19d5e2-4a8b-4f0c-9d3e-1b2a3c4d5e07",
      "branch": "feat/488-usage-manifest",
      "started_at": "2026-10-24T18:07:41.411Z",
      "duration_s": null,
      "queue_wait_s": 0.2,
      "sandbox": "ws-5a9c",
      "session_id": "ses_01J9F4A2W3"
    },
    "events": [
      {
        "id": 1,
        "at": 0,
        "type": "webhook_received",
        "data": {
          "delivery": "7c19…",
          "event": "issues",
          "action": "labeled",
          "sender": "nam20485"
        }
      },
      {
        "id": 2,
        "at": 0.2,
        "type": "webhook_accepted",
        "data": {
          "delivery": "7c19…",
          "label": "orchestration:implement",
          "issue": 488
        }
      },
      {
        "id": 3,
        "at": 0.3,
        "type": "prompt_queued",
        "data": {
          "delivery": "7c19…",
          "queue_depth": 0
        }
      },
      {
        "id": 4,
        "at": 2.4,
        "type": "sandbox_provisioned",
        "data": {
          "workspace": "ws-5a9c",
          "image": "swarm-sandbox:2.4",
          "base": "development"
        }
      },
      {
        "id": 5,
        "at": 2.9,
        "type": "agent_session_started",
        "data": {
          "session_id": "ses_01J9F4A2W3",
          "agent": "opencode",
          "cwd": "/workspace"
        }
      },
      {
        "id": 6,
        "at": 3,
        "type": "user_message_chunk",
        "data": {
          "text": "Record agent_usage totals in the run manifest and expose them through GET /runs. Do not change the event payload shape."
        }
      },
      {
        "id": 7,
        "at": 5.2,
        "type": "agent_thought_chunk",
        "data": {
          "text": "Checking how manifest.json is written before adding fields."
        }
      },
      {
        "id": 8,
        "at": 8.1,
        "type": "agent_tool_call",
        "data": {
          "tool": "read",
          "title": "src/webhook_receiver/acp_host.py"
        }
      },
      {
        "id": 9,
        "at": 19.6,
        "type": "agent_tool_call",
        "data": {
          "tool": "read",
          "title": "src/webhook_receiver/trace_log.py"
        }
      },
      {
        "id": 10,
        "at": 33.4,
        "type": "agent_plan",
        "data": {
          "entries": [
            {
              "content": "Add usage fields to the manifest",
              "status": "pending"
            },
            {
              "content": "Populate them from agent_usage",
              "status": "pending"
            },
            {
              "content": "Cover /runs serialization",
              "status": "pending"
            }
          ]
        }
      },
      {
        "id": 11,
        "at": 96.2,
        "type": "agent_tool_call",
        "data": {
          "tool": "edit",
          "title": "src/webhook_receiver/acp_host.py",
          "additions": 31,
          "deletions": 5
        }
      },
      {
        "id": 12,
        "at": 220.5,
        "type": "agent_usage",
        "data": {
          "input_tokens": 88240,
          "output_tokens": 4310,
          "context_window": 200000
        }
      },
      {
        "id": 13,
        "at": 244.8,
        "type": "agent_thought_chunk",
        "data": {
          "text": "Now adding the usage fields to the manifest writer and the runs index."
        }
      }
    ]
  }
];

export const WEBHOOK_TAIL = [
  {
    "id": "h1",
    "ts": "2026-10-24T14:09:41Z",
    "type": "webhook_filtered",
    "data": {
      "delivery": "b71c…",
      "event": "issues",
      "action": "labeled",
      "reason": "label_not_dispatched",
      "label": "bug"
    }
  },
  {
    "id": "h2",
    "ts": "2026-10-24T14:08:12Z",
    "type": "webhook_duplicate",
    "data": {
      "delivery": "a09d…",
      "event": "issues",
      "action": "labeled"
    }
  },
  {
    "id": "h3",
    "ts": "2026-10-24T14:06:57Z",
    "type": "webhook_filtered",
    "data": {
      "delivery": "e4b2…",
      "event": "issues",
      "action": "opened",
      "reason": "sender_is_bot",
      "sender": "dependabot[bot]"
    }
  },
  {
    "id": "h4",
    "ts": "2026-10-24T14:05:30Z",
    "type": "webhook_accepted",
    "data": {
      "delivery": "c8f1…",
      "event": "issue_comment",
      "action": "created",
      "label": "orchestration:direct",
      "sender": "nam20485"
    }
  },
  {
    "id": "h5",
    "ts": "2026-10-24T13:59:03Z",
    "type": "webhook_received",
    "data": {
      "delivery": "f2a7…",
      "event": "ping",
      "sender": "nam20485"
    }
  },
  {
    "id": "h6",
    "ts": "2026-10-24T13:54:19Z",
    "type": "webhook_filtered",
    "data": {
      "delivery": "9d3e…",
      "event": "issues",
      "action": "labeled",
      "reason": "label_not_in_namespace",
      "label": "documentation"
    }
  },
  {
    "id": "h7",
    "ts": "2026-10-24T13:51:02Z",
    "type": "webhook_filtered",
    "data": {
      "delivery": "77bc…",
      "event": "push",
      "action": null,
      "reason": "event_not_dispatched"
    }
  },
  {
    "id": "h8",
    "ts": "2026-10-24T13:47:38Z",
    "type": "webhook_received",
    "data": {
      "delivery": "3e9f…",
      "event": "issues",
      "action": "labeled",
      "sender": "nam20485"
    }
  }
];
