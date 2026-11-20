// Live adapter: maps the receiver's read-only API onto the shapes the console
// renders. Same-origin fetches only (the page CSP is `connect-src 'self'`), so
// this works when the console is served by the service at /console.
// Nothing here is a fallback: every function throws on a non-OK response and
// the caller shows an error state instead of substituting fixture data.

async function getJson(path) {
  const response = await fetch(path, { credentials: "same-origin", headers: { accept: "application/json" } });
  if (!response.ok) throw new Error(`${path} -> ${response.status}`);
  return response.json();
}

// agent_tool_call carries `kind`, agent_usage carries `used`/`size`; the
// console renders `tool` and `input_tokens`/`context_window`.
function normalizeData(event) {
  const data = event.data;
  if (!data) return data;
  if (event.type === "agent_tool_call") return { ...data, tool: data.tool ?? data.kind };
  if (event.type === "agent_usage")
    return { ...data, input_tokens: data.input_tokens ?? data.used, context_window: data.context_window ?? data.size };
  return data;
}

export async function fetchLiveRuns() {
  const index = await getJson("/runs");
  return index.map((entry) => {
    const manifest = entry.manifest || {};
    const endedAt = manifest.ended_at ? (Date.parse(manifest.ended_at) - Date.parse(manifest.started_at)) / 1000 : null;
    return {
      run_id: entry.run_id,
      manifest: {
        ...manifest,
        title: manifest.label || manifest.repo || entry.run_id,
        duration_s: Number.isFinite(endedAt) ? endedAt : null,
      },
      events: null,
    };
  });
}

export async function fetchLiveRunEvents(run) {
  const events = await getJson(`/runs/${encodeURIComponent(run.run_id)}/events`);
  // /runs omits the manifest for run dirs without a parsable manifest.json —
  // no anchor means no offsets (null renders "—"), never NaN
  const start = Date.parse(run.manifest.started_at) / 1000;
  return events.map((event) => ({
    id: event.id,
    at: Number.isFinite(start) ? event.ts - start : null,
    type: event.type,
    data: normalizeData(event),
  }));
}

export async function fetchLiveTail() {
  const history = await getJson("/events/history");
  return history
    .filter((event) => event.type.startsWith("webhook_"))
    .map((event) => ({
      id: event.id,
      ts: new Date(event.ts * 1000).toISOString(),
      type: event.type,
      data: { ...event.data, delivery: event.data?.delivery_id ?? event.data?.delivery },
    }))
    .reverse();
}
