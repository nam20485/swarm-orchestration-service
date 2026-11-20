// DEV ONLY: process-local conversation state for the local console preview.
// It implements the same service contract as the deployed Function, with
// controlled fixture replies. No AI service is called.
import { RUNS } from '../web/data.mjs';
import { ChatError } from '../functions/chat-handler.mjs';

const done = (state) => ["completed", "failed", "interrupted"].includes(state);
const stageAnchors = ["webhook_accepted", "prompt_queued", "sandbox_provisioned", "agent_session_started", "agent_finished", "prompt_consumed"];

function fmtDuration(seconds) {
  if (seconds == null) return "—";
  const total = Math.round(seconds);
  const m = Math.floor(total / 60);
  const s = total % 60;
  return m ? `${m}m ${s}s` : `${s}s`;
}
function fmtOffset(seconds) {
  if (seconds < 60) return `+${seconds < 10 ? Number(seconds.toFixed(1)) : Math.round(seconds)}s`;
  return `+${Math.floor(seconds / 60)}m ${String(Math.round(seconds % 60)).padStart(2, "0")}s`;
}

function localReply(text, runId) {
  const run = RUNS.find((item) => item.run_id === runId);
  const lines = ["**Local preview reply** — no AI service was called.", ""];
  if (run) {
    const m = run.manifest;
    lines.push(`You asked about **#${m.issue} · ${m.title}** (\`${run.run_id.slice(0, 8)}\`).`);
    if (m.ok === false) {
      lines.push(
        `It ended **failed** after ${fmtDuration(m.duration_s)} with \`${m.error || m.stop_reason}\`. The terminal event is \`${run.events.at(-1).type}\`.`
      );
    } else if (m.ok === true) {
      lines.push(
        `It **completed** in ${fmtDuration(m.duration_s)} with \`stop_reason: ${m.stop_reason}\`. Queue wait was ${m.queue_wait_s}s and the workspace was ${m.sandbox ? `sandbox \`${m.sandbox}\`` : "a plain scratch directory"}.`
      );
    } else {
      lines.push(`It is **still running**. The latest event is \`${run.events.at(-1).type}\` at ${fmtOffset(run.events.at(-1).at)}.`);
    }
    lines.push("", "Anchors in this trace:");
    for (const type of stageAnchors) {
      const event = run.events.find((item) => item.type === type);
      if (event) lines.push(`- \`${type}\` at ${fmtOffset(event.at)}`);
      else if (type === "sandbox_provisioned" && !m.sandbox) lines.push("- no sandbox for this label — the session used a scratch directory");
    }
    if (m.ok === false) {
      lines.push("", "Start with the terminal events: `agent_finished` carries the stop reason and the following `prompt_consumed` carries the envelope outcome. A released sandbox with reason `session_error` or `session_timeout` narrows the failure to the session, not the gate.");
    } else {
      lines.push("", "The path is gate → frozen `PromptInfo` → FIFO queue → workspace → one cold ACP session → terminal consumption, with the event store fanning every step out over `/events`.");
    }
  } else {
    lines.push("No run is attached to this question, so here is the pipeline contract only:", "");
    lines.push("- `webhook_received` → size guard, HMAC, JSON parse");
    lines.push("- `webhook_accepted` / `webhook_filtered` → transport gate");
    lines.push("- `prompt_queued` → frozen envelope enters the FIFO");
    lines.push("- `sandbox_provisioned` → optional SwarmSandbox workspace");
    lines.push("- `agent_session_started` → one cold ACP session per envelope");
    lines.push("- `prompt_consumed` → queue marks the envelope done");
    lines.push("", "Select a run to attach its trace, then ask again.");
  }
  lines.push("", "This is fixture text from `site/dev/memory-service.mjs`. With the Qoder backend enabled, the same UI is answered by a Cloud Agent grounded in the selected run.");
  return lines.join("\n");
}

export function createMemoryService() {
  let conversation = null;
  let closed = false;

  const copy = () =>
    conversation
      ? {
          id: conversation.id,
          title: conversation.title,
          revision: conversation.revision,
          state: conversation.state,
          messages: conversation.messages.map((message) => ({ ...message })),
          ...(conversation.runId ? { runId: conversation.runId } : {}),
          ...(conversation.requestId ? { requestId: conversation.requestId } : {}),
        }
      : null;

  const bump = () => {
    conversation.revision += 1;
    for (const notify of conversation.listeners) notify();
  };

  const owned = (id) => {
    if (!conversation || conversation.id !== id) throw new ChatError("not_found");
    return conversation;
  };

  function generate(item, reply) {
    const chunks = reply.match(/\s+|\S+/g) || [];
    let index = 0;
    const tick = () => {
      if (closed || done(item.state)) return;
      const message = item.messages.at(-1);
      let add = "";
      for (let count = 0; count < 5 && index < chunks.length; count += 1) add += chunks[index++];
      message.text += add;
      message.state = "running";
      item.state = "running";
      bump();
      if (index < chunks.length) item.timer = setTimeout(tick, 28 + Math.random() * 38);
      else {
        message.state = "completed";
        item.state = "completed";
        bump();
      }
    };
    item.timer = setTimeout(tick, 320);
  }

  return {
    async authorize() {
      return { id: "local-visitor" };
    },
    info() {
      return { mode: "local-demo", persistence: "memory-until-server-exit" };
    },
    async list() {
      return conversation ? [copy()] : [];
    },
    async create(principal) {
      if (conversation) return copy();
      conversation = {
        id: `c_${crypto.randomUUID()}`,
        owner: principal.id,
        title: "Local demo",
        revision: 0,
        state: "idle",
        messages: [],
        requests: new Map(),
        listeners: new Set(),
        runId: undefined,
        requestId: undefined,
        timer: undefined,
      };
      return copy();
    },
    async get(principal, id) {
      const item = owned(id);
      if (item.owner && item.owner !== principal.id) throw new ChatError("not_found");
      return copy();
    },
    async send(principal, id, { requestId, text, runId }) {
      const item = owned(id);
      const previous = item.requests.get(requestId);
      if (previous !== undefined) {
        if (previous !== text) throw new ChatError("request_conflict");
        return copy();
      }
      if (["running", "pending"].includes(item.state) || item.messages.length >= 98) throw new ChatError("conversation_busy");
      item.requests.set(requestId, text);
      item.title = text.slice(0, 48);
      item.requestId = requestId;
      item.runId = `run_${crypto.randomUUID().replace(/-/g, "").slice(0, 16)}`;
      item.state = "running";
      item.messages.push(
        { id: `m_${crypto.randomUUID()}`, role: "user", text, state: "completed" },
        { id: `m_${crypto.randomUUID()}`, role: "assistant", text: "", state: "running" }
      );
      bump();
      generate(item, localReply(text, runId));
      return copy();
    },
    async interrupt(principal, id, { runId }) {
      const item = owned(id);
      if (!runId || runId !== item.runId) throw new ChatError("request_conflict");
      if (!done(item.state)) {
        clearTimeout(item.timer);
        item.state = "interrupted";
        const message = item.messages.at(-1);
        if (message?.role === "assistant") message.state = "interrupted";
        bump();
      }
      return copy();
    },
    async *watch(principal, id, { signal }) {
      const item = owned(id);
      let dirty = true;
      let wake;
      const notify = () => {
        dirty = true;
        const resume = wake;
        wake = undefined;
        resume?.();
      };
      item.listeners.add(notify);
      const onAbort = () => notify();
      signal.addEventListener("abort", onAbort, { once: true });
      try {
        while (!signal.aborted && !closed) {
          if (!dirty) await new Promise((resolve) => { wake = resolve; });
          if (signal.aborted || closed) return;
          dirty = false;
          yield copy();
          if (done(item.state)) return;
        }
      } finally {
        item.listeners.delete(notify);
        signal.removeEventListener("abort", onAbort);
      }
    },
    close() {
      closed = true;
      if (conversation) {
        clearTimeout(conversation.timer);
        for (const notify of conversation.listeners) notify();
      }
    },
  };
}
