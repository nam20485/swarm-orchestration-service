# Issues plan — root causes, options, recommendations

Status: IMPLEMENTED — PR #64 merged as `7b8603b` (live feed, I1a/I1b), PR #65 merged as
`1786e40` (console, I2a/I2b), 2026-11-20/21. Review rounds complete: 2 findings fixed on
PR #64; 10 on PR #65 (3 fixed, 7 chat-subsystem deferred per decision 4 — follow-up list
on the PR). Merge-readiness protocol (owner 2026-11-20, MUST ALWAYS BE FOLLOWED) recorded
in [`.agents/rules/source-control.md`](../.agents/rules/source-control.md).
Date: 2026-11-20 (analysis + owner decisions folded same day).
Source issues: [`docs/issues.md`](issues.md) (I1a, I1b, I2a, I2b).
Analysis performed in worktree `.qwen/worktrees/bold-ray-a5093f` @ `0895afd`; the main
checkout was only read, never modified. `site/` is gitignored (`.gitignore:85`) and exists
only in the main checkout — decision 3 below checks it in after a clean security audit.

Evidence labels used below: **reading** = verified against current source; **execution** =
verified by running a probe (recipes in the [appendix](#appendix-probe-recipes));
**memory** = point-in-time project memory, re-verify before relying on it.

## Decisions (owner, 2026-11-20)

| # | Question | Owner answer | Effect on plan |
|---|---|---|---|
| 1 | I1a buffer retention | "yes A" | Full-text buffer, render-time truncation (I1a Option A) |
| 2 | Checkbox scope | "take reco" | All `COALESCED` chunk kinds, not just `agent_message_chunk` |
| 3 | `site/` tracking | "check it in after making sure it has no sensitive or unsecure data or PII" | Audit performed — **clean** (see [audit](#security--pii-audit-decision-3-gate)); un-ignore `site/`, keep the Qoder dot-manifest ignored |
| 4 | Console home | "don't care about chat — I just want the rest of the site to show real data" | **Service-mount + real-data wiring** (was I2a Option C). Chat out of scope. Qoder-publish option dropped |
| 5 | Probe harness | "yes take reco, commit" | Commit as `scripts/webui-sse-probe.mjs` (rides PR 1) |

Labeling clarification (owner asked "I thought service-mount was A?"): in the original
options table, I2a **A = dev-server**, **C = service-mount**. The owner's intent —
service-mount with real data — is unambiguous and is recorded as the chosen direction;
the option letters below are kept for traceability with the original analysis.

Account question answered: the entitlement flagged in the original I2a Option D was the
owner's **Qoder account** backend-sites quota (`prepare_site` → `sites_quota_exceeded`,
`backend_sites` 0/0 — memory 2026-10-24). With chat out of scope, that gate is moot and
the Qoder-publish path is dropped; no entitlement re-check is needed.

## Verdict summary

| Issue | Root cause | Evidence | Decided fix |
|---|---|---|---|
| I1a — chunk rows truncated, unreadable | Live tab coalesces chunk fragments into one row, keeps only the **last 1500 chars**, renders it as plain wrapped text with **no expand toggle**; newlines collapse | reading + execution | Full-text buffer + per-row `details` toggle + "expand agent_message_chunks" checkbox (all chunk kinds) |
| I1b — no back-to-top control | Only a scroll-to-bottom pill exists (`live-latest`); no top control anywhere | reading | Fixed floating top button, visible when scrolled down |
| I2a — Qoder site opens as an empty shell | `file://` blocks ES-module loading (CORS, origin `null`); `app.mjs` never executes. **Not** a jsonl format change — the site reads bundled static fixtures, no live jsonl at all | execution (both directions) | Service-mount at `/console` + real-data adapter (runs, traces, webhook tail); chat untouched (offline chip); dev server stays the fixture-demo path |
| I2b — port into ZCode "sites" | Premise does not hold: no Sites feature found in the installed ZCode bundle or its docs index | reading | Nothing to port into; the service-mounted console **is** the home (owner decision 4) |

## I1a — live tab `agent_message_chunk` rows collapse and truncate

File: `src/webhook_receiver/static/index.html` (486 lines, served at `GET /` by
`app.py:196-201`). All line numbers below refer to it.

### Root cause

Four mechanisms compose into the reported symptom; two details in the issue text are
misreadings of the UI, corrected here so the fix targets the real behavior.

| # | Mechanism | Where | Effect |
|---|---|---|---|
| 1 | Coalescing: consecutive same-stream chunks (`type\|run_id` key) merge into one growing row; `count` increments per fragment | `COALESCED` :131, merge logic :296-305 | The `×N` tag (:204) is the **number of coalesced fragment events**, not a line count. The issue's `×6` example = 6 SSE chunks |
| 2 | Tail truncation: `head.merged = (old + new).slice(-1500)` | :299-300 | Only the **last 1500 characters** of the stream survive in the live buffer. The head of a long message is gone from the live tab (full fragments remain in the durable `events.jsonl` and the runs tab) |
| 3 | No toggle on merged rows: the merged branch appends a bare text node; the `details`/`summary` "json" toggle is only built by `appendData` for structured or text-less payloads | :201-209 vs :234-256 | Chunk rows have **no expand/collapse control**. Even non-merged text-only rows are sliced to 300 chars (:242) with no toggle |
| 4 | Newline collapse: the data cell is `td.wrap` (`white-space: normal`), so `\n` in chunk text renders as spaces | CSS :44, merged text node :206 | Line structure is visually lost. **There is no 7-line clamp anywhere** — the perceived "7 lines" is just the wrapped tail-1500 text |

Server side is exonerated: `acp_host.py:271-279` emits chunk text verbatim, no truncation
(webui plan Decision 4: "No server-side truncation"). The defect is entirely client-side.

### Evidence (execution)

Synthetic SSE probe: one `agent_tool_call` (structured payload) + 10 `agent_message_chunk`
fragments of ~300 chars each (~3000 total), served to the real page in headless Chrome.

| Assertion | Expected from root cause | Observed |
|---|---|---|
| Coalesced row count tag | `×10` | `×10` present |
| Head of stream discarded | `LINE-0-START` absent | absent (0 matches) |
| Tail of stream kept | `LINE-9-END` present | present |
| Truncation boundary ~1500 chars | `LINE-5-START` absent | absent |
| Toggle asymmetry | exactly 1 `details` (the json row only) | 1 |
| Buffer accounting | 11 events → 2 rows | "2 shown · 2 buffered" |

### Options (record — decision 1 took A)

| Option | Shape | Pros | Cons |
|---|---|---|---|
| **A — full buffer, render-time truncation (chosen)** | Drop `.slice(-1500)`; buffer keeps the whole stream. Merged row becomes a `details` toggle: summary = `×N` + short preview, body = full text in `pre` (pre-wrap, newlines preserved). Checkbox "expand agent_message_chunks" (default off) forces chunk rows open | One code path; checkbox semantics exactly match the requirement ("checked = don't truncate"); head of message recoverable in the live tab; export becomes complete automatically (merged field is exported, :344-353) | Live buffer memory grows with stream length (bounded by the 2000-item cap :310 and finite run output); a very long run holds its full message text in RAM |
| B — checkbox-gated retention | Keep the 1500 cap when unchecked; accumulate full text only while checked | Default memory posture unchanged | Toggling mid-stream cannot recover head text already dropped — confusing UX; two retention paths; export completeness depends on toggle state at arrival time |
| C — expand fetches the durable log | On expand, fetch `/runs/{run_id}/events` and reconstruct the full stream | Zero buffer growth; full fidelity beyond the ring | Requires `WEBHOOK_EVENTS_LOG_ENABLED` and the run dir to exist; live-only streams (compose mode, log off) have no durable copy; async expand UX; most code of the three |

Rationale for A: smallest change that fully satisfies both stated requirements; B's split
retention creates state-dependent data loss that contradicts the checkbox's promise; C adds
a backend dependency for a rendering defect. Memory cost is acceptable for an internal
observability page (2000-row cap, finite run output); the durable `events.jsonl` remains
the archival record. B is the fallback if memory ever becomes a real constraint.

### Implementation sketch (decided shape)

1. Merge path (:299-300): remove `.slice(-1500)`; keep concatenation and `count`.
2. `rowFor` merged branch (:201-209): build `details` + `summary` (`×N` tag + first ~120
   chars, single line) + `pre` with the full merged text. Reuse the existing `pre` style
   (pre-wrap). Add `title="N coalesced fragments"` on the tag to correct the line-count
   misreading.
3. Expansion state: key by **stream key** (`live:merged:${type}|${run_id}`), not `item.id` —
   the merged row's id changes with every fragment (:303), so id-keyed state would be lost
   on each hot-path rebuild. `wireExpansion` (:227-233) already survives rebuilds via
   `expandedIds`.
4. Checkbox `#live-expand-chunks` in the live bar, label "expand agent_message_chunks"
   (issue text has a typo, "agenbt"), default unchecked. When checked, chunk rows render
   open (full text, newlines preserved); on change, `renderLive()`. **Applies to all
   `COALESCED` kinds** (`user_message_chunk`, `agent_thought_chunk` share the mechanism) —
   decision 2.
5. Hot path (:322-334) already replaces the row per fragment; `wireExpansion` re-applies
   open state from `expandedIds` + checkbox on every rebuild. No new render path needed.
6. Export (:344-353) needs no change — it exports `merged`, which is now the full text.

Out of scope: the runs tab already has the requested toggle pattern (`COLLAPSED` kinds get
`details` with a 120-char summary + full JSON, :427-438); the 300-char slice in `appendData`
for non-merged text rows stays as-is unless the owner wants it swept too.

### Validation

- Extend the served-page assertions in `test_event_log.py:295-303` (existing pattern:
  status/content-type/marker checks, `innerHTML` absence guard) to pin the new control ids
  (`live-expand-chunks`) and the merged-row `details` construction.
- Full `validation.ps1` gate (build → scan → test; python branch coverage floor > 85%).
- Browser execution check with the committed SSE probe (`scripts/webui-sse-probe.mjs`,
  decision 5): after the fix, the same probe must show `LINE-0-START` present when
  expanded, `details` on the chunk row, and checkbox default off.

## I1b — no back-to-top button

### Root cause (reading)

The page renders oldest-first and auto-scrolls to the bottom on new events (:223, :329).
The only scroll control is the `live-latest` pill (:88, :186, :341-343) which scrolls
**down**. Nothing scrolls up; after reading history the user must scroll manually. The
control simply does not exist — no defect beyond the missing feature.

### Options (record — decided A)

| Option | Shape | Pros | Cons |
|---|---|---|---|
| **A — fixed floating top button (chosen)** | Fixed-position button at the viewport bottom-right, hidden while at the top, smooth-scrolls to top; global across all three tabs | Matches the issue's "on the bottom of the page"; always reachable exactly when needed (long page, scrolled down); mirrors the existing latest-pill visibility pattern | Overlays a small corner of content |
| B — static button in each tab's bar | Add a "top" button next to pause/export | No overlay; trivial | The bar scrolls out of view on long pages — unavailable precisely when needed, which is the complaint |

### Implementation sketch

- Button `#back-top`, fixed bottom-right, `hidden` while `window.scrollY < threshold`
  (mirror `syncLatestPill`); label "top" (name the control; no glyph art needed).
- Click: `window.scrollTo({ top: 0, behavior: "smooth" })`.
- Works on every tab (runs detail traces are long too). Reuses the existing passive scroll
  listener (:340).

### Validation

Served-page assertion for `back-top`; browser check: scroll down, button visible, click
returns to top (the committed probe harness extends trivially).

## I2a — Qoder site opens as an empty shell; make it show real data

Files live in the **main checkout only** today (`site/` is gitignored, `.gitignore:85`):
`site/web/index.html`, `app.mjs` (1044 lines), `data.mjs` (337 lines, 7 fixture runs),
`styles.css`, `helpers/` (2 files), `site/dev/` (dev server + fixture chat service),
`site/functions/` (7 Qoder Function files). Manifest:
`site/.Swarm Ops Console.qoder.site` (static bootstrap draft, action `ecf1c945`, prepared
and unpublished — matches memory 2026-10-24).

### Root cause (execution, both directions)

1. `index.html` loads the app as an ES module: `<script type="module" src="./app.mjs">`.
   Chrome blocks module scripts on `file://` (origin `null`). Captured console error:

   ```text
   Access to script at 'file:///.../site/web/app.mjs' from origin 'null' has been blocked
   by CORS policy: Cross origin requests are only supported for protocol schemes:
   chrome, chrome-experimental-site-token-provider, chrome-extension, chrome-untrusted,
   data, http, https, isolated-app.
   ```

   DOM after load: `run-count` = 0, zero run cards — the empty shell the issue reports.
2. Served over HTTP via the bundled dev server (`node site/dev/server.mjs`,
   `127.0.0.1:4173`): `run-count` = 7, seven run cards rendered, no console errors. The
   site works as designed when served.
3. The issue's format-drift hypothesis is ruled out: `app.mjs:1` imports
   `RUNS, WEBHOOK_TAIL` from `./data.mjs` — **bundled synthetic fixtures**. The site never
   reads live traces/jsonl, so no format change can break it.
4. The analyst chat needs the server too: `app.mjs:402` targets
   `/functions/v1/app/api/chat`, which the dev server mounts with the production chat
   handler backed by in-memory fixture replies. A bare static server renders the console
   but leaves chat offline; `file://` cannot work at all (module CORS plus CSP
   `connect-src 'self'`).

The real limitation is the one the owner's decision 4 targets: even served, the console
shows **fixtures, not live service data**. The decided work is the real-data wiring below.

### Security & PII audit (decision 3 gate)

Performed 2026-11-20 over the whole `site/` tree, read-only. **Result: clean — cleared
for check-in.**

| Check | Method | Result |
|---|---|---|
| Secret scan | `gitleaks detect --no-git --source site/ --config .gitleaks.toml` | **no leaks found** |
| Hardcoded credentials | reading `functions/cloud-agents.mjs`, `live-service.mjs`, `chat-handler.mjs`, `index.ts` | none — `QODER_PAT` is read at runtime from `Deno.env` (`cloud-agents.mjs:21`); `index.ts` documents it as platform-managed. The 600 file modes were precautionary, not secret-bearing |
| PII (emails, names, local paths) | regex sweep over `web/`, `dev/`, `functions/` | no emails, no local absolute paths; the only identity is `nam20485` — the owner's **public** GitHub handle, already public throughout this repo |
| Fixture provenance | reading `data.mjs`, `functions/sample-runs.mjs` | explicitly synthetic (`data.mjs` header: "Nothing here is read from a live deployment"); issue numbers, session ids, delivery ids are invented |
| Qoder dot-manifest | reading `.Swarm Ops Console.qoder.site` | holds Qoder resource UUIDs (project/site/deployment/action ids) + base64 HTML — account-scoped identifiers, **not credentials**; tool-local state → **keep ignored**, do not check in |

Check-in scope: `site/web/`, `site/dev/`, `site/functions/` (all audited clean). The chat
Function code is checked in as-is for posterity and the fixture demo, but is **out of
scope** for service mode (decision 4: chat not wanted). `.gitignore` change: un-ignore
`site/`, add an explicit ignore for `site/.*.qoder.site`.

### Options (record — decision 4 took service-mount + real data)

| Option | Shape | Pros | Cons |
|---|---|---|---|
| A — dev server only | Document + launcher wrapping `node site/dev/server.mjs` | Zero asset changes; verified working; fixture chat works | Fixtures only — does not meet the owner's real-data requirement; needs Node |
| B — single-file bundle for `file://` | Inline all assets into one HTML, no modules | Double-click works | Build step (against the W2 no-build posture); chat still dead; diverges from the Qoder artifact; two copies to maintain |
| **C — service-mount + real-data adapter (chosen)** | FastAPI route `/console` serving `site/web`; adapter replaces fixtures with `/runs`, `/runs/{id}/events`, `/events/history` | One origin with the service; up whenever the service is up; **real data**; same-origin CSP already satisfied; harness-agnostic (answers I2b) | New route + Dockerfile COPY; shape gaps need an adapter (below); chat degrades to offline |
| D — publish via Qoder Sites | Enable backend entitlement, publish the complete draft | Hosted URL; real analyst chat | **Dropped** — chat out of scope; entitlement gate moot |

### Real-data wiring spec (the decided work)

Shape gaps between the console's fixture expectations and the real API, all verified by
reading (`app.mjs`, `data.mjs`, `app.py`, `trace_log.py`, `acp_host.py`):

| Console expects | Real source | Adapter rule |
|---|---|---|
| `RUNS` with embedded `events` (module import) | `GET /runs` → `[{run_id, manifest, modified_at}]`, **no events** (`app.py:213-221`) | Rail renders from `/runs`; **lazy-fetch** `/runs/{id}/events` on selection, cache per run |
| `manifest.title` | absent — real manifest carries `run_id, delivery_id, repo, event, action, label, workspace, started_at` (`trace_log.py:181-189`) + `ended_at, ok, stop_reason, session_id, error` via `finish()` (`acp_host.py:626`) | title fallback = `label` (or `repo · label`) |
| `manifest.issue` | absent; `webhook_accepted` carries no issue field either (`app.py:336-343`) | omit the issue chip; optional follow-up: enrich the manifest (contract change, owner-gated) |
| `manifest.branch`, `sandbox`, `queue_wait_s` | absent | omit those chips/stat cells |
| `manifest.sender` | absent in manifest; present in `webhook_received`/`webhook_accepted` event data | derive from the run's first webhook event, else omit |
| `manifest.duration_s` | absent; `started_at`/`ended_at` are ISO-8601 UTC seconds (`trace_log.py:102-104`) | compute `ended − started`; running run = `now − started` |
| `manifest.ok`, `stop_reason` | present (`finish()`) | direct |
| `event.at` (offset seconds, `app.mjs:310,330,336`) | `event.ts` epoch seconds | `at = ts − started_at_epoch` |
| numeric `event.id` | `"<boot-epoch>-<token>-<seq>"` string | pass through (display-only) |
| `WEBHOOK_TAIL` with ISO `ts`, `data.delivery` (`app.mjs:351`) | `GET /events/history` → epoch `ts`, `data.delivery_id` | `fmtClock(ts * 1000)`; render `delivery_id` |
| chat at `/functions/v1/app/api/chat` | not served by the receiver | **no work** — existing offline-chip degradation (verify during implementation) |

Mode switch (explicit, never silent): `app.mjs` defaults to **live** mode (fetch `/runs`;
on failure show a "service unreachable" error state with retry — never fall back to
fixtures, which would mask an outage as fake data). Fixture mode only via `?fixtures=1`;
the dev server redirects `/` → `/?fixtures=1` (one-line change) so the demo path keeps
working unchanged.

Refresh: add a rail refresh control re-fetching `/runs` + tail. SSE-driven live updates
(`/events`) are an optional phase 2 — out of v1 scope.

### Mount mechanics

- Route: `app.mount("/console", StaticFiles(directory=<repo_root>/site/web, html=True))`
  in `create_app`; repo root resolves as `Path(__file__).resolve().parents[2]`
  (`src/webhook_receiver/app.py` → repo root; in the container `/app/webhook_receiver/app.py`
  → `/app`). Same-origin, so the page's CSP `connect-src 'self'` is satisfied unchanged.
- **Dockerfile.webhook must gain `COPY site/web/ ./site/web/`** — the image today copies
  only `src/webhook_receiver/` (verified by reading); without this the mount 500s in
  compose mode.
- MIME gotcha to verify at implementation: `StaticFiles` guesses `.mjs` via `mimetypes`;
  if the platform maps it to anything but `text/javascript`, module loading fails — add an
  explicit media-type mapping if needed. Pin it with a route test.
- Exposure posture unchanged: listener-local, no auth (webui plan W3 stays owner-gated).
  `/console` inherits the same posture as `/`, `/runs`, `/events`.

Asset home (refinement of decisions 3+4, recommended): **in-place `site/web`** + the
Dockerfile COPY — honors "check it in" literally, preserves the Qoder draft layout and the
dev-server demo, smallest diff. Alternative considered: relocate assets to
`src/webhook_receiver/static/console/` (auto-packaged, one static home) — rejected for v1
because it moves the Qoder artifact and breaks the dev server's relative imports unless
they are rewritten too. Owner may override.

### Implementation sketch (decided shape)

1. `.gitignore`: un-ignore `site/`; keep `site/.*.qoder.site` ignored. Check in the audited
   `site/web`, `site/dev`, `site/functions` trees.
2. `app.py`: `/console` mount (above) + route tests (HTML served, `.mjs` MIME, listener-local
   posture).
3. `site/web/data-live.mjs` (new): the adapter — fetch + shape mapping per the table;
   `app.mjs` init branches on mode (live default, `?fixtures=1` demo), lazy per-run event
   loads, rail refresh control, error state with retry.
4. `site/dev/server.mjs`: `/` → `/?fixtures=1` redirect (demo path unchanged otherwise).
5. `Dockerfile.webhook`: `COPY site/web/ ./site/web/`.
6. Docs: `docs/usage.md` console section (serve via the service at `/console`; dev-server
   fixture demo; chat offline in service mode; `file://` limitation with the captured
   error).
7. Chat: zero changes.

### Validation

- `validation.ps1` full gate; new pytest route tests for `/console` (serving contract +
  MIME), adapter shape-mapping unit-testable via a pure mapping function if extracted.
- Browser execution check against a receiver with a populated trace root (real runs or
  synthetic run dirs): rail shows real runs, selection loads real events with correct
  offsets, tail shows real deliveries, chat chip offline, `?fixtures=1` still renders the
  7 demo runs.
- The `file://` failure and dev-server success probes (appendix) remain the regression
  evidence for the original symptom.

## I2b — port the site into ZCode's "sites" feature

### Premise check (reading): no such feature found in ZCode

| Probe | Result |
|---|---|
| ZCode docs index (`https://zcode.z.ai/en/docs`, fetched 2026-11-20) | 26 page slugs enumerated (agents, automations, browser-use, configuration, edit-history, hooks, mcp-services, plugin, skill, subagents, …); **no sites page**; `/en/docs/sites` returns 404 |
| Installed bundle `/opt/ZCode/resources/app.asar` string search | `prepare_site`, `publish_site`, `sites_quota`, `backend_sites`, `create_site`, `deploy_site`: **0 matches**. The 361 `siteId` hits belong to an edit-history timeline schema (`phases`, `holes`, `phaseEdges`) — unrelated to web hosting |
| `~/.zcode/skills/`, shipped config templates | No sites skill or sites config surface |

Qoder Sites is Qoder-specific: the `.qoder.site` manifest, the `prepare_site`/`get_site`
MCP tools, and the QCA Function backend have no ZCode counterpart in the installed app or
its docs. Conclusion: **there is nothing to port into** — the issue's "if possible"
resolves to "not possible as stated". (Absence evidence is from the installed version and
the live docs index on 2026-11-20; a future ZCode release could change this.)

### Options (record — resolved by decision 4)

| Option | Shape | Pros | Cons |
|---|---|---|---|
| **A — service-mounted console (chosen, = I2a Option C)** | Console served by the receiver at `/console`; open from any browser, including ZCode's browser-use | Harness-agnostic; no external entitlement; real data; one deployment artifact (the service) | Chat offline (owner: not wanted) |
| B — stay on Qoder Sites | Publish when entitlement allows | Hosted analyst chat as designed | **Dropped** — chat out of scope; entitlement gate moot |
| C — other static hosting (GitHub Pages, Cloudflare Pages) | Publish `site/web` as static assets | Public URL | Chat dead without a port; fixtures-only unless wired; publishing internal run data externally needs an auth review |
| D — ZCode plugin/skill wrapper | A ZCode skill opening the served console via browser-use | Cheap convenience | Not a hosting feature; cosmetic; can ride later if wanted |

Resolution: the service-mounted console **is** the home. No ZCode-specific port exists or
is needed; the console becomes a plain same-origin web surface of the service.

## Execution order

| PR | Scope | Deliverables | Gate |
|---|---|---|---|
| 1 | I1a + I1b + decision 5 | `static/index.html` (full buffer, toggles, checkbox, top button) + pytest served-page assertions + `scripts/webui-sse-probe.mjs` | `validation.ps1` full gate + probe execution (pre/post-fix expectations in the appendix) |
| 2 | I2a + I2b (decisions 3+4) | `.gitignore` un-ignore + audited `site/` check-in + `/console` mount + `data-live.mjs` adapter + `app.mjs` mode switch + dev-server redirect + `Dockerfile.webhook` COPY + `docs/usage.md` section | `validation.ps1` full gate + new route tests + browser check against a populated trace root |

PR 1 and PR 2 are independent and can land in parallel. Commits follow the source-control
rules (`/safe-commit` + `validation.ps1` before each commit; new branches off
`development`, never onto a branch with an open PR). Optional follow-ups, not committed
scope: SSE-driven live refresh; manifest enrichment (`issue`/`title`) — a contract change,
owner-gated.

## Appendix: probe recipes

All probes ran 2026-11-20 on this host (google-chrome headless, Node v20.19.2). Scratch
harness lives at `.qwen/tmp/probe/sse-probe.mjs` in the worktree; decision 5 commits it as
`scripts/webui-sse-probe.mjs` in PR 1.

### I2a — `file://` failure and HTTP success

```bash
# failure direction: empty shell + CORS error on stderr
google-chrome --headless=new --disable-gpu --no-first-run \
  --user-data-dir=/tmp/probe-profile --enable-logging=stderr \
  --virtual-time-budget=8000 --dump-dom \
  "file:///home/nam20485/src/github/nam20485/swarm-orchestration-service/site/web/index.html" \
  > dom-file.html 2> stderr-file.log
grep -o 'id="run-count">[^<]*' dom-file.html   # observed: id="run-count">0
grep -c 'run-card"' dom-file.html              # observed: 0
grep "blocked by CORS" stderr-file.log         # observed: the module-CORS error quoted above

# success direction: bundled dev server (fixture demo)
node site/dev/server.mjs &                     # 127.0.0.1:4173, mounts fixture chat
google-chrome --headless=new --disable-gpu --no-first-run \
  --user-data-dir=/tmp/probe-profile2 --enable-logging=stderr \
  --virtual-time-budget=8000 --dump-dom "http://127.0.0.1:4173/" \
  > dom-http.html 2> stderr-http.log
grep -o 'id="run-count">[^<]*' dom-http.html   # observed: id="run-count">7
grep -c 'run-card"' dom-http.html              # observed: 7
```

### I1a — synthetic SSE probe

Harness: a Node server that serves the real `static/index.html` at `/` and emits at
`/events` one `agent_tool_call` (with `payload`, so it renders a json toggle) followed by
10 `agent_message_chunk` fragments `LINE-i-START xxx… LINE-i-END\n` (~300 chars each).
Ids are deterministic (`1795000000-probe-N`) so reconnect replays dedupe; the stream ends
with `retry: 60000` + close so headless Chrome's virtual-time budget can expire (an
open-ended SSE stream stalls `--dump-dom` — first probe attempt timed out for this reason).

```bash
node .qwen/tmp/probe/sse-probe.mjs &           # 127.0.0.1:4179
google-chrome --headless=new --disable-gpu --no-first-run \
  --user-data-dir=/tmp/probe-profile3 --virtual-time-budget=6000 \
  --dump-dom "http://127.0.0.1:4179/" > dom-sse.html
grep -o '×10' dom-sse.html                     # observed: ×10 (fragment count, not lines)
grep -c 'LINE-0-START' dom-sse.html            # observed: 0 (head dropped by slice(-1500))
grep -c 'LINE-9-END' dom-sse.html              # observed: 1 (tail kept)
grep -c '<details' dom-sse.html                # observed: 1 (json row only; chunk row has none)
```

Post-fix expectations (PR 1): `LINE-0-START` present when the row is expanded (or checkbox
on), `<details>` count 2, checkbox `#live-expand-chunks` present and unchecked by default,
`#back-top` present.

Post-mount expectations (PR 2): `/console` renders real runs from `/runs` (count matches
the trace root), selecting a run loads its real events with correct `at` offsets, the tail
shows real `delivery_id`s, the chat chip reads offline, and `/console/?fixtures=1` still
renders the 7 demo runs.
