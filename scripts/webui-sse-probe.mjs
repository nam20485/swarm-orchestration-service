// Browser probe for the live observability webui (issues I1a/I1b).
//
// Purpose: serves src/webhook_receiver/static/index.html together with a
// synthetic SSE stream that reproduces the coalesced-chunk conditions — one
// agent_tool_call (structured "json" row) plus 10 agent_message_chunk
// fragments (~300 chars each, ~3000 total, i.e. beyond the old 1500 cap) —
// renders the page in headless Chrome and asserts the POST-FIX DOM.
//
// Usage: node scripts/webui-sse-probe.mjs [--expand]
//   --expand  injects a click on #live-expand-chunks into the served page
//             (harness-side only, the file on disk is never modified) and
//             additionally requires the chunk row's <details> to be open.
//
// Gotcha: the SSE stream MUST be closed with res.end(). An open-ended stream
// keeps headless Chrome from ever settling, so --virtual-time-budget with
// --dump-dom hangs instead of printing the DOM. Event ids are deterministic so
// a reconnect replay is deduped by the page's own seenIds set.
import { createServer } from "node:http";
import { spawn } from "node:child_process";
import { readFileSync, mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { fileURLToPath } from "node:url";
import path from "node:path";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const HTML_PATH = path.resolve(HERE, "..", "src", "webhook_receiver", "static", "index.html");
const PORT = 4179;
const expand = process.argv.includes("--expand");
const INJECT =
  '<script>document.getElementById("live-expand-chunks").click();</script>';

const raw = readFileSync(HTML_PATH, "utf8");
const html = expand ? raw.replace("</body>", `${INJECT}</body>`) : raw;

const chunks = Array.from({ length: 10 }, (_, i) =>
  `LINE-${i}-START ${"x".repeat(280)} LINE-${i}-END\n`
);

const server = createServer((req, res) => {
  if (req.url === "/") {
    res.writeHead(200, { "content-type": "text/html; charset=utf-8" });
    res.end(html);
    return;
  }
  if (req.url === "/events") {
    res.writeHead(200, {
      "content-type": "text/event-stream",
      "cache-control": "no-cache",
      connection: "keep-alive",
    });
    res.write("retry: 60000\n\n");
    let seq = 0;
    const send = (type, data) =>
      res.write(`event: ${type}\nid: 1795000000-probe-${++seq}\ndata: ${JSON.stringify(data)}\n\n`);
    send("agent_tool_call", { run_id: "probe-run", tool: "bash", title: "probe", payload: { cmd: "echo hi" } });
    for (const c of chunks) send("agent_message_chunk", { run_id: "probe-run", text: c });
    res.end(); // close the stream — see the virtual-time gotcha above
    return;
  }
  res.writeHead(404);
  res.end();
});

const listen = () =>
  new Promise((resolve) => server.listen(PORT, "127.0.0.1", resolve));

const dumpDom = (profile) => new Promise((resolve) => {
  const args = [
    "--headless=new",
    "--disable-gpu",
    "--no-first-run",
    "--no-default-browser-check",
    `--user-data-dir=${profile}`,
    "--virtual-time-budget=6000",
    "--dump-dom",
    `http://127.0.0.1:${PORT}/`,
  ];
  // ASYNC spawn with FILE redirection — two deadlocks avoided:
  // 1. spawnSync would freeze this process's event loop, so the SSE/HTTP
  //    server above could never answer chrome's requests (self-deadlock).
  // 2. Piped stdout would be held open by lingering chrome children
  //    (crashpad/gpu) after the main process exits; files avoid the EOF wait.
  // `timeout` bounds a wedged render; profile paths must stay short (chrome's
  // singleton socket has a ~108-char Unix path limit).
  const domFile = path.join(profile, "dom.html");
  const errFile = path.join(profile, "stderr.log");
  const quoted = args.map((a) => `'${a}'`).join(" ");
  const cmd = `CHROME=$(command -v google-chrome || command -v google-chrome-stable); ` +
    `timeout 60 "$CHROME" ${quoted} > '${domFile}' 2> '${errFile}'`;
  const child = spawn("bash", ["-c", cmd]);
  child.on("error", (err) => resolve({ status: -1, error: err, stdout: "", stderr: "" }));
  child.on("exit", (code) => {
    let dom = "";
    let stderr = "";
    try { dom = readFileSync(domFile, "utf8"); } catch { /* chrome never wrote */ }
    try { stderr = readFileSync(errFile, "utf8"); } catch { /* ditto */ }
    resolve({ status: code, error: null, stdout: dom, stderr });
  });
});

// A closed <details> still carries its children in the DOM, so the full-text
// assertions hold whether or not the row is expanded.
const assert = (label, ok) => {
  console.log(`${ok ? "PASS" : "FAIL"}  ${label}`);
  return ok;
};

const main = async () => {
  await listen();
  const profile = mkdtempSync(path.join(tmpdir(), "webui-sse-probe-"));
  try {
    const run = await dumpDom(profile);
    if (run.error) {
      console.log(`FAIL  chrome not runnable: ${run.error.message}`);
      return 1;
    }
    if (run.status !== 0) {
      console.log(`FAIL  chrome exited ${run.status}: ${run.stderr.slice(0, 400)}`);
      return 1;
    }
    const dom = run.stdout;
    const detailsCount = (dom.match(/<details\b/g) || []).length;
    const chunkInput = (dom.match(/<input[^>]*id="live-expand-chunks"[^>]*>/) || [])[0];
    const checks = [
      assert("×10 coalesced-fragment tag rendered", dom.includes("×10")),
      assert("exactly 2 <details> (json row + merged chunk row)", detailsCount === 2),
      assert("LINE-0-START present (buffer keeps the head)", dom.includes("LINE-0-START")),
      assert("LINE-9-END present (buffer keeps the tail)", dom.includes("LINE-9-END")),
      assert("#live-expand-chunks present", chunkInput !== undefined),
      assert("#live-expand-chunks unchecked by default",
        chunkInput !== undefined && !/\bchecked\b/.test(chunkInput)),
      assert("#back-top present", dom.includes('id="back-top"')),
    ];
    if (expand) {
      const at = dom.indexOf("LINE-0-START");
      const open = at >= 0 && (() => {
        const start = dom.lastIndexOf("<details", at);
        return dom.slice(start, dom.indexOf(">", start) + 1).includes(" open");
      })();
      checks.push(assert("chunk row <details> carries open (--expand)", open));
    }
    return checks.every((ok) => ok) ? 0 : 1;
  } finally {
    server.close();
    rmSync(profile, { recursive: true, force: true });
  }
};

process.exitCode = await main();
