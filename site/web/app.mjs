import { RUNS, WEBHOOK_TAIL } from "./data.mjs";
import { fetchLiveRuns, fetchLiveRunEvents, fetchLiveTail } from "./data-live.mjs";
import { createConversationStream } from "./helpers/conversation-stream.mjs";

// Live service data by default; `?fixtures=1` renders the synthetic demo.
const FIXTURES = new URLSearchParams(location.search).has("fixtures");

const $ = (id) => document.getElementById(id);
const el = (tag, className, text) => {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
};

const state = {
  runs: [],
  tail: [],
  selectedId: null,
  contextId: null,
  filter: "all",
  query: "",
};

const byNewest = (a, b) => Date.parse(b.manifest.started_at) - Date.parse(a.manifest.started_at);
const outcomeKind = (run) => (run.manifest.ok === undefined ? "run" : run.manifest.ok ? "ok" : "err");
const startedMs = (run) => Date.parse(run.manifest.started_at);
const durationSeconds = (run) =>
  run.manifest.duration_s ?? Math.max(0, (Date.now() - startedMs(run)) / 1000);
const shortId = (id) => (id ? id.slice(0, 8) : "");
// Real manifests carry no issue / branch / sender / sandbox / queue_wait_s; a
// missing field renders an em dash, never the string "undefined".
const field = (value) => (value == null ? "—" : value);

function fmtDuration(seconds) {
  if (seconds == null || Number.isNaN(seconds)) return "—";
  const total = Math.max(0, Math.round(seconds));
  if (total < 60) return `${total}s`;
  const m = Math.floor(total / 60);
  const s = total % 60;
  if (m < 60) return s ? `${m}m ${s}s` : `${m}m`;
  const h = Math.floor(m / 60);
  const rm = m % 60;
  return rm ? `${h}h ${rm}m` : `${h}h`;
}

function fmtOffset(seconds) {
  // null/NaN: a run without a parsable manifest has no anchor for offsets
  if (seconds == null || Number.isNaN(seconds)) return "—";
  if (seconds < 60) {
    const n = seconds < 10 ? Number(seconds.toFixed(1)) : Math.round(seconds);
    return `+${n}s`;
  }
  // round the total before splitting, or 119.9s renders "+1m 60s"
  const total = Math.round(seconds);
  return `+${Math.floor(total / 60)}m ${String(total % 60).padStart(2, "0")}s`;
}

const fmtClock = (iso) => {
  const ms = Date.parse(iso);
  return Number.isNaN(ms) ? "—" : new Date(ms).toLocaleTimeString([], { hour12: false });
};
const fmtTokens = (n) =>
  typeof n === "number" ? (n >= 1000 ? `${(n / 1000).toFixed(1)}k` : String(n)) : "—";
const fmtCount = (n) => (typeof n === "number" ? n.toLocaleString() : "—");

function labelTone(label) {
  if (label?.startsWith("orchestration")) return "tone-orchestration";
  if (label?.startsWith("implementation")) return "tone-implementation";
  if (label?.startsWith("gh-issue-tracking")) return "tone-tracking";
  return "tone-direct";
}
function labelChip(label) {
  return el("span", `label-chip ${labelTone(label)}`, label || "unlabeled");
}

function eventFamily(type, data) {
  if (type === "agent_permission") return data?.decision === "reject" ? "fam-error" : "fam-lifecycle";
  if (type === "agent_finished") return data?.stop_reason === "end_turn" ? "fam-agent" : "fam-error";
  if (type === "prompt_consumed") return data?.ok === false ? "fam-error" : "fam-queue";
  if (type.startsWith("webhook_")) return "fam-webhook";
  if (type.startsWith("prompt_")) return "fam-queue";
  if (type.startsWith("sandbox_")) return "fam-sandbox";
  if (type.startsWith("agent_")) return "fam-agent";
  return "fam-lifecycle";
}

function summarizeEvent(ev) {
  const d = ev.data || {};
  const clip = (value, max = 150) => {
    const text = String(value ?? "").replace(/\s+/g, " ").trim();
    return text.length > max ? `${text.slice(0, max)}…` : text;
  };
  switch (ev.type) {
    case "webhook_received":
      return [d.event, d.action].filter(Boolean).join(".") + (d.sender ? ` · ${d.sender}` : "");
    case "webhook_accepted":
      return [d.label, d.issue ? `#${d.issue}` : ""].filter(Boolean).join(" · ");
    case "webhook_filtered":
      return `${field(d.reason)} · ${d.label || d.sender || d.event || ""}`;
    case "webhook_duplicate":
      return `delivery ${field(d.delivery ?? d.delivery_id)} already seen`;
    case "prompt_queued":
      return `queue depth ${field(d.queue_depth)}`;
    case "prompt_consumed":
      return d.ok ? `ok · ${field(d.stop_reason)}` : `not ok · ${d.stop_reason || d.error || "—"}`;
    case "sandbox_provisioned":
      return `${field(d.workspace)} · ${field(d.image)}`;
    case "sandbox_released":
      return `${field(d.workspace)} · ${field(d.reason)}`;
    case "agent_session_started":
      return `${field(d.agent)} · ${field(d.cwd)}`;
    case "agent_tool_call":
      return [d.tool, d.title].filter(Boolean).join(" · ");
    case "agent_permission":
      return `${field(d.decision)} · ${field(d.tool)} · ${field(d.policy)}`;
    case "agent_plan":
    case "agent_plan_update":
      return `${d.entries?.length || 0} plan entries`;
    case "agent_plan_removed":
      return d.reason || "plan removed";
    case "agent_usage":
      return `in ${fmtTokens(d.input_tokens)} · out ${fmtTokens(d.output_tokens)}`;
    case "agent_finished":
      return `stop_reason ${field(d.stop_reason)}`;
    case "agent_commands_update":
      return `${d.available_commands?.length || 0} commands available`;
    case "agent_mode_update":
      return `mode ${field(d.mode)}`;
    case "agent_config_update":
      return Object.entries(d.options || {}).map(([key, value]) => `${key}=${value}`).join(" · ");
    case "user_message_chunk":
    case "agent_message_chunk":
    case "agent_thought_chunk":
      return clip(d.text);
    default:
      return clip(JSON.stringify(d));
  }
}

/* ── theme ──────────────────────────────────────────────────────────── */
function readTheme() {
  try {
    return localStorage.getItem("swarm-ops-theme");
  } catch {
    return null;
  }
}
function setTheme(theme) {
  document.documentElement.dataset.theme = theme;
  try {
    localStorage.setItem("swarm-ops-theme", theme);
  } catch {}
}
setTheme(readTheme() || (matchMedia("(prefers-color-scheme: light)").matches ? "light" : "dark"));
$("theme-toggle").addEventListener("click", () => {
  setTheme(document.documentElement.dataset.theme === "dark" ? "light" : "dark");
});

/* ── runs rail ──────────────────────────────────────────────────────── */
function matchesFilter(run) {
  const kind = outcomeKind(run);
  if (state.filter === "running") return kind === "run";
  if (state.filter === "failed") return kind === "err";
  if (state.filter === "done") return kind === "ok";
  return true;
}
function matchesQuery(run) {
  if (!state.query) return true;
  const m = run.manifest;
  return [run.run_id, m.title, m.repo, m.label, m.issue, m.branch]
    .filter((value) => value != null)
    .join(" ")
    .toLowerCase()
    .includes(state.query);
}

function renderCounts() {
  const counts = { all: state.runs.length, running: 0, failed: 0, done: 0 };
  for (const run of state.runs) {
    const kind = outcomeKind(run);
    if (kind === "run") counts.running += 1;
    else if (kind === "err") counts.failed += 1;
    else counts.done += 1;
  }
  $("run-count").textContent = String(counts.all);
  for (const button of document.querySelectorAll(".filters button")) {
    button.querySelector("span").textContent = String(counts[button.dataset.filter]);
  }
}

function renderRunList() {
  const list = $("run-list");
  list.replaceChildren();
  const visible = state.runs.filter((run) => matchesFilter(run) && matchesQuery(run));
  $("run-empty").hidden = visible.length > 0;
  const fragment = document.createDocumentFragment();
  for (const run of visible) {
    const m = run.manifest;
    const kind = outcomeKind(run);
    const card = el("button", "run-card");
    card.type = "button";
    card.setAttribute("aria-current", run.run_id === state.selectedId ? "true" : "false");
    card.title = `${run.run_id}\n${m.title}`;

    const top = el("div", "run-card-top");
    top.append(el("span", "run-card-id", shortId(run.run_id)), labelChip(m.label));

    const title = el("div", "run-card-title", m.title);

    const bottom = el("div", "run-card-bottom");
    const elapsed = fmtDuration(durationSeconds(run));
    const left = el("span", null, m.issue == null ? elapsed : `#${m.issue} · ${elapsed}`);
    // no started_at (manifest-less run): skip the live-clock anchor instead
    // of writing the string "undefined" into the data attribute
    if (kind === "run" && m.started_at != null) left.dataset.liveStart = m.started_at;
    const outcome = el("span", `run-card-outcome ${kind}`);
    outcome.append(el("span", `dot ${kind}`), document.createTextNode(kind === "run" ? "running" : kind === "ok" ? "ok" : m.stop_reason || "failed"));
    bottom.append(left, outcome);

    card.append(top, title, bottom);
    card.addEventListener("click", () => void selectRun(run.run_id));
    fragment.append(card);
  }
  list.append(fragment);
}

/* ── run detail ─────────────────────────────────────────────────────── */
function renderRun(run) {
  const view = $("run-view");
  view.replaceChildren();
  const m = run.manifest;
  const kind = outcomeKind(run);

  document.title = `${shortId(run.run_id)} · ${m.title} — Swarm Ops`;

  const head = el("div", "run-head");
  const headRow = el("div", "run-head-row");
  const headMain = el("div", "run-head-main");
  const crumbs = el("div", "crumbs");
  crumbs.append(el("span", null, "runs"), el("span", "sep", "/"), el("span", null, shortId(run.run_id)));
  const title = el("h1", "run-title", m.title);
  const meta = el("div", "meta-row");
  meta.append(
    el("span", "chip ghost", m.repo),
    ...(m.issue == null ? [] : [el("span", "chip ghost", `#${m.issue}`)]),
    labelChip(m.label),
    el("span", "meta-sep", "·"),
    el("span", null, `started ${fmtClock(m.started_at)} · ${fmtDuration(durationSeconds(run))}`),
    ...(m.branch ? [el("span", "meta-sep", "·"), el("span", null, m.branch)] : [])
  );
  headMain.append(crumbs, title, meta);

  const ask = el("button", "ask-btn", "ask analyst ↗");
  ask.type = "button";
  ask.title = "Attach this run and ask the analyst";
  ask.addEventListener("click", () => {
    state.contextId = run.run_id;
    renderContext();
    chatInput.value = kind === "err" ? `Why did run ${shortId(run.run_id)} fail?` : `Walk me through run ${shortId(run.run_id)}.`;
    chatInput.focus();
    updateChatControls();
  });
  headRow.append(headMain, ask);
  head.append(headRow);

  const outcome = el("div", `outcome is-${kind}`);
  outcome.append(el("span", `dot ${kind}`));
  const outcomeText = el("div");
  const detailParts = [];
  if (kind === "err") detailParts.push(m.error || `stop_reason ${field(m.stop_reason)}`);
  if (kind === "ok") detailParts.push(`stop_reason ${m.stop_reason || "end_turn"}`);
  if (kind === "run") detailParts.push(`last event ${run.events.at(-1)?.type || "—"}`);
  detailParts.push(`${run.events.length} events`);
  detailParts.push(m.sandbox ? `sandbox ${m.sandbox}` : m.sandbox === null ? "no sandbox" : "sandbox not reported");
  outcomeText.append(
    el("strong", null, kind === "run" ? "In progress" : kind === "ok" ? "Completed" : "Failed"),
    el("span", "outcome-detail", detailParts.join(" · "))
  );
  outcome.append(outcomeText);

  const usage = [...run.events].reverse().find((ev) => ev.type === "agent_usage")?.data;
  const queueWait = m.queue_wait_s;
  const stats = el("div", "stat-grid");
  stats.append(
    stat(
      "duration",
      fmtDuration(durationSeconds(run)),
      kind === "run" ? m.started_at : null,
      kind === "run" ? "elapsed, live" : m.duration_s == null ? "not reported" : `${m.duration_s}s total`
    ),
    stat(
      "queue wait",
      queueWait == null ? "—" : `${queueWait.toFixed(1)}s`,
      null,
      queueWait == null ? "not in manifest" : "enqueue → consumer"
    ),
    stat("events", String(run.events.length), null, "this run's events.jsonl"),
    stat(
      "tokens",
      usage ? fmtTokens((usage.input_tokens || 0) + (usage.output_tokens || 0)) : "—",
      null,
      usage ? `${fmtCount(usage.input_tokens)} in + ${fmtCount(usage.output_tokens)} out` : "not reported"
    )
  );

  view.append(head, outcome, stats, buildFlow(run), buildTimeline(run));
}

function stat(label, value, liveStart, title) {
  const box = el("div", "stat");
  box.append(el("span", "stat-label", label));
  const valueNode = el("span", "stat-value", value);
  if (liveStart) valueNode.dataset.liveStart = liveStart;
  if (title) box.title = title;
  box.append(valueNode);
  return box;
}

function buildFlow(run) {
  const m = run.manifest;
  const kind = outcomeKind(run);
  const stages = [
    { key: "webhook", label: "webhook", types: ["webhook_received"] },
    { key: "gate", label: "gate", types: ["webhook_accepted", "webhook_filtered"] },
    { key: "queue", label: "queue", types: ["prompt_queued"] },
    {
      key: "workspace",
      label: m.sandbox ? "sandbox" : m.sandbox === null ? "scratch dir" : "workspace",
      types: m.sandbox ? ["sandbox_provisioned"] : ["agent_session_started"],
    },
    { key: "session", label: "acp session", types: ["agent_session_started"] },
    { key: "finish", label: "finished", types: ["prompt_consumed"] },
  ];
  const flow = el("div", "flow");
  flow.setAttribute("aria-label", "Pipeline stages for this run");
  let sawMissing = false;
  for (const stage of stages) {
    const found = run.events.find((ev) => stage.types.includes(ev.type));
    let status = found ? "done" : "pending";
    if (!found && kind === "run" && !sawMissing) {
      status = "live";
      sawMissing = true;
    }
    if (found && stage.key === "finish" && kind === "err") status = "fail";
    const step = el("div", `flow-step ${status}`);
    const name = el("span", "flow-stage");
    name.append(el("span", "dot"), document.createTextNode(stage.label));
    step.append(name, el("span", "flow-time", found ? fmtOffset(found.at) : status === "live" ? "in flight" : "—"));
    flow.append(step);
  }
  return flow;
}

function buildTimeline(run) {
  const wrap = el("div");
  const head = el("div", "section-head");
  const labels = el("div");
  labels.append(el("h2", null, "Event trace"), el("p", null, `${run.events.length} events · click a row for the wire payload`));
  head.append(labels);
  wrap.append(head);

  const timeline = el("div", "timeline");
  for (const ev of run.events) {
    const family = eventFamily(ev.type, ev.data);
    const details = el("details", "tl-row");
    const summary = el("summary");
    summary.append(
      el("span", "tl-time", fmtOffset(ev.at)),
      el("span", `tl-dot ${family}`),
      el("span", `tl-type ${family}`, ev.type),
      el("span", "tl-summary", summarizeEvent(ev)),
      el("span", "tl-chev", "›")
    );
    const payload = el("pre", "tl-json", JSON.stringify({ id: ev.id, at: ev.at, type: ev.type, data: ev.data }, null, 2));
    details.append(summary, payload);
    timeline.append(details);
  }
  wrap.append(timeline);
  return wrap;
}

function renderTail() {
  const body = $("tail-body");
  body.replaceChildren();
  for (const event of state.tail) {
    const family = eventFamily(event.type, event.data);
    const row = el("tr");
    row.append(
      el("td", null, fmtClock(event.ts)),
      el("td", `tail-type ${family}`, event.type),
      el("td", null, event.data.delivery || "—")
    );
    const detail = [];
    if (event.type === "webhook_filtered") {
      detail.push(event.data.reason);
      if (event.data.label) detail.push(event.data.label);
      if (event.data.sender) detail.push(event.data.sender);
      if (event.data.event) detail.push(event.data.event);
    } else if (event.type === "webhook_duplicate") {
      detail.push("dedup window hit · acknowledged, not queued");
    } else if (event.type === "webhook_accepted") {
      detail.push(event.data.label, event.data.event);
    } else {
      detail.push(event.data.event, event.data.action);
    }
    row.append(el("td", null, detail.filter(Boolean).join(" · ")));
    body.append(row);
  }
}

function updateLiveClocks() {
  for (const node of document.querySelectorAll("[data-live-start]")) {
    node.textContent = fmtDuration((Date.now() - Date.parse(node.dataset.liveStart)) / 1000);
  }
}

function parseHash() {
  const match = /^#run=([A-Za-z0-9-]+)$/.exec(location.hash);
  if (!match) return null;
  const value = match[1];
  return state.runs.find((run) => run.run_id === value || run.run_id.startsWith(value))?.run_id || null;
}

function renderTraceUnavailable(run) {
  const view = $("run-view");
  view.replaceChildren();
  const box = el("div", "outcome is-fail");
  box.append(el("span", "dot err"));
  const text = el("div");
  text.append(
    el("strong", null, "Trace unavailable"),
    el("span", "outcome-detail", `GET /runs/${run.run_id}/events failed — the service may be unreachable`)
  );
  const retry = el("button", "ask-btn", "retry");
  retry.type = "button";
  retry.addEventListener("click", () => void selectRun(run.run_id));
  box.append(text, retry);
  view.append(box);
}

async function selectRun(id, { focusChat = false } = {}) {
  const run = state.runs.find((item) => item.run_id === id);
  if (!run) return;
  state.selectedId = id;
  state.contextId = id;
  history.replaceState(null, "", `#run=${id}`);
  renderRunList();
  if (run.events == null) {
    $("run-view").replaceChildren(el("p", "tail-note", "loading event trace…"));
    try {
      run.events = await fetchLiveRunEvents(run);
    } catch {
      if (state.selectedId === id) renderTraceUnavailable(run);
      return;
    }
    if (state.selectedId !== id) return;
  }
  renderRun(run);
  renderContext();
  renderSuggestions();
  const stage = document.querySelector(".stage");
  if (stage) stage.scrollTop = 0;
  if (focusChat) chatInput.focus();
}

/* ── chat ───────────────────────────────────────────────────────────── */
const CHAT_BASE = "/functions/v1/app/api/chat";
const chatInput = $("chat-input");
const chatScroll = $("chat-scroll");
const messageBox = $("chat-messages");
const rendered = new Map();

const terminal = (value) => ["completed", "failed", "interrupted"].includes(value);
const busyState = (value) => ["running", "pending"].includes(value);

const chat = {
  mode: null,
  ready: false,
  conversation: null,
  reader: null,
  view: 0,
  sending: false,
  forceScroll: false,
  intents: new Map(),
  creation: null,
  reconnectTimer: null,
};

const errorText = {
  chat_not_configured: "The analyst Function is not configured on this deployment.",
  login_required: "Sign in to use the analyst.",
  forbidden: "This conversation is not available.",
  not_found: "This conversation has expired. Reload to start a fresh session.",
  invalid_request: "Check the message and try again.",
  payload_too_large: "That message is too long.",
  request_conflict: "Request state conflicted. Reload to recover the session.",
  conversation_busy: "Wait for the current reply or stop it first.",
  dispatch_unknown: "Outcome pending — recovering state without resending.",
  rate_limited: "Too many messages. Try again in a few minutes.",
  service_unavailable: "The analyst service is unavailable. Your draft is kept.",
};

class ApiError extends Error {
  constructor(code, status) {
    super(code);
    this.code = code;
    this.status = status;
  }
}

async function api(path, options = {}) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 20000);
  try {
    const response = await fetch(`${CHAT_BASE}${path}`, {
      credentials: "same-origin",
      ...options,
      signal: controller.signal,
    });
    const contentType = response.headers.get("content-type") || "";
    if (!contentType.includes("application/json")) throw new ApiError("service_unavailable", response.status);
    const body = await response.json();
    if (!response.ok || body?.error) throw new ApiError(body?.error?.code || "service_unavailable", response.status);
    return body;
  } catch (error) {
    if (error instanceof ApiError) throw error;
    throw new ApiError("service_unavailable", 0);
  } finally {
    clearTimeout(timer);
  }
}

const post = (path, value, requestId = crypto.randomUUID()) =>
  api(path, {
    method: "POST",
    headers: { "content-type": "application/json", "idempotency-key": requestId },
    body: JSON.stringify(value),
  });

function setMode(mode) {
  chat.mode = mode;
  const badge = $("chat-mode");
  badge.className = `chip mode ${mode === "live" ? "live" : mode === "local-demo" ? "local" : "offline"}`;
  badge.textContent = mode === "live" ? "cloud agent" : mode === "local-demo" ? "local demo" : "offline";
  badge.title =
    mode === "live"
      ? "Replies come from a Qoder Cloud Agent through this site's Function."
      : mode === "local-demo"
        ? "Controlled fixture replies from the local dev server. No AI service is called."
        : "The analyst service is not reachable in this preview.";
  $("chat-persistence").textContent =
    mode === "live"
      ? "Ephemeral — one conversation per tab session, no account history."
      : mode === "local-demo"
        ? "Local demo — history clears when the dev server stops."
        : "Ephemeral session — no history is stored.";
}

function showNotice(text, kind = "") {
  const node = $("chat-notice");
  node.textContent = text || "";
  node.hidden = !text;
  node.classList.toggle("is-error", kind === "error");
}

function updateChatControls() {
  const conversation = chat.conversation;
  const isBusy = busyState(conversation?.state) || chat.sending;
  $("chat-send").disabled = !(chat.ready && !isBusy && chatInput.value.trim());
  $("chat-stop").hidden = !(busyState(conversation?.state) && conversation?.runId);
  chatInput.disabled = !chat.ready;
  chatInput.placeholder = chat.ready ? "Ask about this run…" : "Assistant unavailable in this preview";
  $("chat-hint").textContent = chat.sending ? "sending…" : "Enter to send · Shift+Enter newline";
  $("chat-activity").textContent = chat.sending
    ? "Sending message"
    : conversation?.state === "running"
      ? "Analyst is replying"
      : conversation?.state === "pending"
        ? "Waiting for the dispatch outcome"
        : conversation?.state === "completed"
          ? "Reply complete"
          : conversation?.state === "interrupted"
            ? "Reply stopped"
            : conversation?.state === "failed"
              ? "Reply failed"
              : "";
}

function renderContext() {
  const box = $("chat-context");
  box.replaceChildren();
  box.append(el("span", "ctx-label", "context"));
  const run = state.contextId ? state.runs.find((item) => item.run_id === state.contextId) : null;
  if (run) {
    const chip = el("span", "ctx-chip");
    chip.title = `${shortId(run.run_id)} · ${field(run.manifest.label)}`;
    if (run.manifest.issue != null) chip.append(el("span", "ctx-id", `#${run.manifest.issue}`));
    chip.append(el("span", "ctx-title", run.manifest.title));
    const detach = el("button", "ctx-x", "×");
    detach.type = "button";
    detach.title = "Detach run context";
    detach.setAttribute("aria-label", "Detach run context");
    detach.addEventListener("click", () => {
      state.contextId = null;
      renderContext();
      chatInput.focus();
    });
    box.append(chip, detach);
  } else {
    box.append(el("span", null, "none — answers use the pipeline contract only"));
    if (state.selectedId) {
      const attach = el("button", "ctx-attach", "attach selected");
      attach.type = "button";
      attach.addEventListener("click", () => {
        state.contextId = state.selectedId;
        renderContext();
      });
      box.append(attach);
    }
  }
}

function renderSuggestions() {
  const box = $("chat-suggestions");
  if (!box) return;
  box.replaceChildren();
  const run = state.runs.find((item) => item.run_id === state.selectedId);
  const prompts = [
    run?.manifest.ok === false
      ? `Why did ${shortId(run.run_id)} fail?`
      : `Walk me through ${shortId(run?.run_id || "this run")}.`,
    "What happens between webhook_accepted and prompt_consumed?",
    "Which run should I investigate next, and why?",
    state.runs.some((item) => !item.manifest.sandbox) ? "How does a run behave without a sandbox?" : "What does sandbox_released tell me?",
  ];
  for (const prompt of prompts) {
    const button = el("button", null, prompt);
    button.type = "button";
    button.addEventListener("click", () => {
      chatInput.value = prompt;
      chatInput.focus();
      updateChatControls();
    });
    box.append(button);
  }
}

function nearBottom() {
  return chatScroll.scrollHeight - chatScroll.scrollTop - chatScroll.clientHeight < 80;
}
function scrollChat() {
  chatScroll.scrollTop = chatScroll.scrollHeight;
}

function renderInline(parent, text) {
  const pattern = /(`[^`]+`|\*\*[^*]+\*\*)/g;
  let last = 0;
  let match;
  while ((match = pattern.exec(text))) {
    if (match.index > last) parent.append(document.createTextNode(text.slice(last, match.index)));
    const token = match[0];
    if (token.startsWith("`")) parent.append(el("code", null, token.slice(1, -1)));
    else parent.append(el("strong", null, token.slice(2, -2)));
    last = match.index + token.length;
  }
  if (last < text.length) parent.append(document.createTextNode(text.slice(last)));
}

function renderBlocks(parent, text) {
  const lines = text.split("\n");
  let paragraph = [];
  let list = null;
  const flushParagraph = () => {
    if (!paragraph.length) return;
    const node = el("p");
    renderInline(node, paragraph.join(" "));
    parent.append(node);
    paragraph = [];
  };
  const flushList = () => {
    if (!list) return;
    parent.append(list);
    list = null;
  };
  for (const raw of lines) {
    const line = raw.trimEnd();
    if (!line.trim()) {
      flushParagraph();
      flushList();
      continue;
    }
    const heading = /^\s*#{2,4}\s+(.*)$/.exec(line);
    const bullet = /^\s*[-*•]\s+(.*)$/.exec(line);
    const numbered = /^\s*\d+[.)]\s+(.*)$/.exec(line);
    if (heading) {
      flushParagraph();
      flushList();
      const node = el("h4", null, heading[1]);
      parent.append(node);
      continue;
    }
    if (bullet || numbered) {
      flushParagraph();
      if (!list) list = el("ul");
      const item = el("li");
      renderInline(item, (bullet || numbered)[1]);
      list.append(item);
      continue;
    }
    flushList();
    paragraph.push(line.trim());
  }
  flushParagraph();
  flushList();
}

function renderRichText(parent, text) {
  const chunks = String(text).split(/```/);
  chunks.forEach((chunk, index) => {
    if (!chunk) return;
    if (index % 2 === 1) {
      let code = chunk;
      const firstBreak = code.indexOf("\n");
      if (firstBreak > -1 && /^[A-Za-z0-9_+-]*$/.test(code.slice(0, firstBreak))) code = code.slice(firstBreak + 1);
      const pre = el("pre");
      pre.append(el("code", null, code.replace(/\n$/, "")));
      parent.append(pre);
    } else {
      renderBlocks(parent, chunk);
    }
  });
}

function stateLine(entry, message) {
  entry.article.querySelector(".msg-state")?.remove();
  if (message.state === "failed" || message.state === "interrupted") {
    const line = el(
      "div",
      `msg-state${message.state === "failed" ? " err" : ""}`,
      message.state === "failed" ? "reply failed — partial text is kept" : "stopped — send a new message to continue"
    );
    entry.article.append(line);
  }
}

function renderMessages() {
  const conversation = chat.conversation;
  const messages = conversation?.messages || [];
  const stick = nearBottom() || chat.forceScroll;
  $("chat-empty").hidden = messages.length > 0 || busyState(conversation?.state);

  for (const node of messageBox.querySelectorAll(".msg.pending")) node.remove();

  const live = new Set(messages.map((message) => message.id));
  for (const [id, entry] of rendered) {
    if (!live.has(id)) {
      entry.article.remove();
      rendered.delete(id);
    }
  }

  messages.forEach((message, index) => {
    let entry = rendered.get(message.id);
    if (!entry) {
      const article = el("article", `msg ${message.role}`);
      const role = el("div", "msg-role");
      role.append(el("span", "role-mark"), document.createTextNode(message.role === "user" ? "you" : "analyst"));
      const body = el("div", "msg-body");
      article.append(role, body);
      entry = { article, body, text: null, state: null };
      rendered.set(message.id, entry);
    }
    const changed = entry.text !== message.text || entry.state !== message.state;
    if (changed) {
      entry.body.replaceChildren();
      if (message.role === "user") {
        entry.body.textContent = message.text;
      } else if (message.text) {
        renderRichText(entry.body, message.text);
        if (message.state === "running") {
          const caret = el("span", "caret");
          const last = entry.body.lastElementChild;
          if (last && (last.tagName === "P" || last.tagName === "LI")) last.append(caret);
          else entry.body.append(caret);
        }
      } else if (busyState(message.state)) {
        entry.body.append(el("span", "typing", "working"));
      }
      stateLine(entry, message);
      entry.text = message.text;
      entry.state = message.state;
    }
    const current = messageBox.children[index];
    if (current !== entry.article) messageBox.insertBefore(entry.article, current || null);
  });

  if (stick) scrollChat();
  chat.forceScroll = false;
  updateChatControls();
}

function applyConversation(value, expectedView) {
  if (!value || chat.view !== expectedView) return false;
  if (chat.conversation && value.id !== chat.conversation.id) return false;
  if (chat.conversation && value.id === chat.conversation.id && value.revision < chat.conversation.revision) return false;
  const conversationChanged = chat.conversation?.id !== value.id;
  chat.conversation = value;
  if (conversationChanged) {
    rendered.clear();
    messageBox.replaceChildren();
    chat.forceScroll = true;
  }
  for (const [id, intent] of chat.intents) {
    if (intent.requestId === value.requestId) {
      chat.intents.delete(id);
      chat.sending = false;
    }
  }
  renderMessages();
  return terminal(value.state);
}

function cancelReader() {
  clearTimeout(chat.reconnectTimer);
  if (chat.reader) {
    chat.reader.stream.cancel();
    chat.reader = null;
  }
}

function scheduleReconnect(id, expectedView, attempt) {
  clearTimeout(chat.reconnectTimer);
  chat.reconnectTimer = setTimeout(async () => {
    if (chat.view !== expectedView) return;
    try {
      const { conversation } = await api(`/conversations/${encodeURIComponent(id)}`);
      if (chat.view !== expectedView) return;
      const done = applyConversation(conversation, expectedView);
      if (done) return;
      if (busyState(conversation.state)) void connect(id, expectedView, attempt);
      else showNotice("Connection closed. The conversation is preserved; reload to resume.", "error");
    } catch {
      if (chat.view === expectedView) showNotice("Connection lost. The reply is preserved; reload to resume without resending.", "error");
    }
  }, 400 * Math.max(1, attempt));
}

function connect(id, expectedView, attempt = 0) {
  cancelReader();
  let resolveReady;
  const ready = new Promise((resolve) => {
    resolveReady = resolve;
  });
  const owned = {
    stream: createConversationStream((frame) => {
      if (chat.view !== expectedView) return true;
      if (frame.event === "stream-error") throw new Error("stream_error");
      let payload;
      try {
        payload = JSON.parse(frame.data);
      } catch {
        throw new Error("bad_frame");
      }
      if (!payload?.conversation) return false;
      const done = applyConversation(payload.conversation, expectedView);
      if (frame.event === "ready") {
        resolveReady(true);
        return done;
      }
      return done;
    }),
  };
  chat.reader = owned;
  owned.stream
    .read((signal) =>
      fetch(`${CHAT_BASE}/conversations/${encodeURIComponent(id)}/events`, {
        credentials: "same-origin",
        signal,
        headers: { accept: "text/event-stream" },
      })
    )
    .then(() => {
      if (chat.reader !== owned) return;
      chat.reader = null;
      if (chat.view === expectedView && !terminal(chat.conversation?.state)) scheduleReconnect(id, expectedView, attempt + 1);
      resolveReady(true);
    })
    .catch(() => {
      if (chat.reader !== owned) return;
      chat.reader = null;
      if (chat.view !== expectedView) return;
      if (attempt < 2 && busyState(chat.conversation?.state)) scheduleReconnect(id, expectedView, attempt + 1);
      else showNotice("Connection interrupted. The reply is preserved; reload to resume without resending.", "error");
      resolveReady(false);
    });
  return ready;
}

async function createConversation() {
  if (chat.creation?.promise) return chat.creation.promise;
  const command = chat.creation || { requestId: crypto.randomUUID() };
  chat.creation = command;
  command.promise = (async () => {
    try {
      const { conversation } = await post("/conversations", {}, command.requestId);
      cancelReader();
      chat.view += 1;
      chat.conversation = null;
      chat.creation = null;
      applyConversation(conversation, chat.view);
      return conversation;
    } catch (error) {
      if (error.status && error.status < 500 && error.code !== "dispatch_unknown") {
        chat.creation = null;
        showNotice(errorText[error.code] || errorText.service_unavailable, "error");
      } else {
        showNotice("New conversation outcome is pending. Reload to recover it; sending will reuse the same request.", "error");
      }
      return null;
    } finally {
      command.promise = null;
    }
  })();
  return command.promise;
}

async function recoverState(id, expectedView) {
  try {
    const { conversation } = await api(`/conversations/${encodeURIComponent(id)}`);
    if (chat.view !== expectedView) return;
    const done = applyConversation(conversation, expectedView);
    if (done) return;
    if (busyState(conversation.state)) {
      void connect(id, expectedView);
      return;
    }
    const intent = [...chat.intents.values()][0];
    if (intent) {
      chat.intents.delete(id);
      chatInput.value = intent.text;
      showNotice("The message was not accepted. Your draft has been restored.", "error");
    }
  } catch (error) {
    showNotice(errorText[error.code] || errorText.service_unavailable, "error");
  } finally {
    chat.sending = false;
    renderMessages();
  }
}

async function submitMessage(event) {
  event?.preventDefault();
  const text = chatInput.value.trim();
  if (!text || !chat.ready || chat.sending || busyState(chat.conversation?.state)) return;
  showNotice("");

  let conversation = chat.conversation;
  if (!conversation) {
    conversation = await createConversation();
    if (!conversation) return;
  }
  const id = conversation.id;
  const expectedView = chat.view;
  const intent = { requestId: crypto.randomUUID(), text };
  chat.intents.set(id, intent);
  chat.sending = true;
  chat.forceScroll = true;
  chatInput.value = "";
  updateChatControls();
  renderMessages();

  const connected = await connect(id, expectedView);
  if (!connected || chat.view !== expectedView) {
    if (chat.intents.get(id) === intent) chat.intents.delete(id);
    chat.sending = false;
    if (chat.view === expectedView) showNotice("Could not open the reply stream. The message was not sent.", "error");
    renderMessages();
    return;
  }

  const runId = state.contextId;
  try {
    const { conversation: updated } = await api(`/conversations/${encodeURIComponent(id)}/messages`, {
      method: "POST",
      headers: { "content-type": "application/json", "idempotency-key": intent.requestId },
      body: JSON.stringify({ text, ...(runId ? { runId } : {}) }),
    });
    if (chat.view === expectedView) {
      applyConversation(updated, expectedView);
      // A terminal ready-frame ends the pre-send reader; watch the accepted run instead.
      if (busyState(updated.state)) void connect(id, expectedView);
    }
  } catch (error) {
    if (!error.status || error.status >= 500 || error.code === "dispatch_unknown") {
      showNotice(errorText.dispatch_unknown);
      await recoverState(id, expectedView);
    } else {
      chat.intents.delete(id);
      chatInput.value = text;
      showNotice(errorText[error.code] || errorText.service_unavailable, "error");
    }
  } finally {
    chat.sending = false;
    if (chat.view === expectedView) renderMessages();
  }
}

async function stopReply() {
  const conversation = chat.conversation;
  if (!conversation?.runId) return;
  $("chat-stop").disabled = true;
  try {
    const result = await post(`/conversations/${encodeURIComponent(conversation.id)}/interrupt`, { runId: conversation.runId });
    if (chat.conversation?.id === conversation.id) applyConversation(result.conversation, chat.view);
  } catch (error) {
    showNotice(errorText[error.code] || errorText.service_unavailable, "error");
  } finally {
    $("chat-stop").disabled = false;
    renderMessages();
  }
}

async function startChat() {
  setMode(null);
  renderContext();
  renderMessages();
  try {
    const config = await api("/config");
    chat.ready = true;
    setMode(config.mode === "local-demo" ? "local-demo" : "live");
  } catch (error) {
    chat.ready = false;
    setMode(null);
    showNotice(
      errorText[error.code] || "The analyst service is not reachable. Run the local dev server or deploy the Function to chat.",
      "error"
    );
    renderMessages();
    return;
  }
  try {
    const { conversations } = await api("/conversations");
    if (!Array.isArray(conversations) || conversations.length === 0) {
      renderMessages();
      return;
    }
    const id = conversations[0].id;
    const view = ++chat.view;
    const { conversation } = await api(`/conversations/${encodeURIComponent(id)}`);
    if (chat.view !== view) return;
    applyConversation(conversation, view);
    if (busyState(conversation.state)) void connect(id, view);
  } catch (error) {
    showNotice(errorText[error.code] || errorText.service_unavailable, "error");
    renderMessages();
  }
}

/* ── data source ────────────────────────────────────────────────────── */
const SOURCE = {
  fixtures: {
    dot: "amber",
    chip: "sample fixtures",
    chipTitle:
      "Every run and event shown here is a synthetic fixture. The assistant is the only live integration.",
    foot: "synthetic fixtures — not service data",
    tail: "fixtures",
  },
  loading: {
    dot: "run",
    chip: "connecting",
    chipTitle: "Loading run history from this service (GET /runs).",
    foot: "loading runs from this service",
    tail: "loading",
  },
  live: {
    dot: "ok",
    chip: "live data",
    chipTitle:
      "Runs, traces and the webhook tail come from this service: GET /runs, GET /runs/{run_id}/events, GET /events/history.",
    foot: "manifests + events.jsonl from this service",
    tail: "GET /events/history",
  },
  unreachable: {
    dot: "err",
    chip: "service unreachable",
    chipTitle: "GET /runs failed — no service data could be loaded.",
    foot: "service unreachable",
    tail: "unavailable",
  },
};

function setSourceMode(mode) {
  const copy = SOURCE[mode];
  const chip = document.querySelector(".topbar-meta .chip");
  if (chip) {
    chip.replaceChildren(el("span", `dot ${copy.dot}`), document.createTextNode(copy.chip));
    chip.title = copy.chipTitle;
  }
  const foot = document.querySelector(".rail-foot");
  if (foot) foot.replaceChildren(el("span", `dot ${copy.dot}`), document.createTextNode(copy.foot));
  const tailChip = document.querySelector(".tail .section-head .chip");
  if (tailChip) tailChip.textContent = copy.tail;
}

function renderRailUnavailable() {
  renderCounts();
  renderTail();
  $("run-empty").hidden = true;
  const list = $("run-list");
  list.replaceChildren();
  const notice = el("p", "rail-empty");
  notice.append(document.createTextNode("service unreachable — GET /runs failed. "));
  const retry = el("button", "ctx-attach", "retry");
  retry.type = "button";
  retry.addEventListener("click", () => void loadLive());
  notice.append(retry);
  list.append(notice);
}

async function loadLive() {
  setSourceMode("loading");
  try {
    const [runs, tail] = await Promise.all([fetchLiveRuns(), fetchLiveTail()]);
    state.runs = runs.sort(byNewest);
    state.tail = tail;
  } catch {
    state.runs = [];
    state.tail = [];
    setSourceMode("unreachable");
    renderRailUnavailable();
    return;
  }
  setSourceMode("live");
  renderCounts();
  renderRunList();
  renderTail();
  const id = parseHash() || state.runs[0]?.run_id;
  if (id) void selectRun(id);
  else renderContext();
}

function bootFixtures() {
  setSourceMode("fixtures");
  state.runs = RUNS.slice().sort(byNewest);
  state.tail = WEBHOOK_TAIL;
  renderCounts();
  renderTail();
  const initial = parseHash() || state.runs[0]?.run_id;
  if (initial) void selectRun(initial);
  else renderContext();
}

/* ── wiring ─────────────────────────────────────────────────────────── */
if (!FIXTURES) {
  const refresh = el("button", "ask-btn", "refresh");
  refresh.type = "button";
  refresh.title = "Re-fetch GET /runs and GET /events/history";
  refresh.addEventListener("click", () => void loadLive());
  document.querySelector(".rail-tools")?.append(refresh);
}
$("run-search").addEventListener("input", (event) => {
  state.query = event.target.value.trim().toLowerCase();
  renderRunList();
});
$("run-search").addEventListener("keydown", (event) => {
  if (event.key === "Escape") {
    event.target.value = "";
    state.query = "";
    renderRunList();
    event.target.blur();
  }
});
document.querySelectorAll(".filters button").forEach((button) => {
  button.addEventListener("click", () => {
    state.filter = button.dataset.filter;
    document.querySelectorAll(".filters button").forEach((item) => item.classList.toggle("active", item === button));
    renderRunList();
  });
});
document.addEventListener("keydown", (event) => {
  const target = event.target;
  const typing = target instanceof HTMLElement && (target.tagName === "INPUT" || target.tagName === "TEXTAREA" || target.isContentEditable);
  if (event.key === "/" && !typing) {
    event.preventDefault();
    $("run-search").focus();
  }
});
window.addEventListener("hashchange", () => {
  const id = parseHash();
  if (id && id !== state.selectedId) void selectRun(id);
});

$("chat-form").addEventListener("submit", submitMessage);
$("chat-stop").addEventListener("click", stopReply);
chatInput.addEventListener("input", updateChatControls);
chatInput.addEventListener("keydown", (event) => {
  if (event.key === "Enter" && !event.shiftKey && !event.isComposing) {
    event.preventDefault();
    void submitMessage();
  }
});
window.addEventListener("pagehide", cancelReader);

if (FIXTURES) bootFixtures();
else void loadLive();
updateChatControls();
setInterval(updateLiveClocks, 1000);
void startChat();
