// DEV ONLY: serves site/web and mounts the production chat handler with an
// in-memory fixture service, so the full console flow works before deploying.
import { createServer } from "node:http";
import { stat } from "node:fs/promises";
import { createReadStream } from "node:fs";
import { Readable } from "node:stream";
import { fileURLToPath } from "node:url";
import path from "node:path";
import { createChatHandler } from "../functions/chat-handler.mjs";
import { createMemoryService } from "./memory-service.mjs";

const HOST = "127.0.0.1";
const PORT = Number(process.env.PORT || 4173);
const WEB_ROOT = path.resolve(fileURLToPath(new URL("../web/", import.meta.url)));
const MIME = {
  ".html": "text/html; charset=utf-8",
  ".css": "text/css; charset=utf-8",
  ".mjs": "text/javascript; charset=utf-8",
  ".js": "text/javascript; charset=utf-8",
  ".json": "application/json; charset=utf-8",
  ".svg": "image/svg+xml",
  ".png": "image/png",
  ".ico": "image/x-icon",
  ".txt": "text/plain; charset=utf-8",
  ".woff2": "font/woff2",
};

const service = createMemoryService();
const handler = createChatHandler({ service });

async function readBody(request) {
  const chunks = [];
  for await (const chunk of request) chunks.push(chunk);
  return Buffer.concat(chunks);
}

async function serveStatic(request, response, pathname) {
  const relative = pathname === "/" ? "index.html" : pathname.replace(/^\/+/, "");
  const filePath = path.resolve(WEB_ROOT, relative);
  if (filePath !== WEB_ROOT && !filePath.startsWith(`${WEB_ROOT}${path.sep}`)) {
    response.writeHead(403, { "content-type": "text/plain; charset=utf-8" });
    response.end("Forbidden");
    return;
  }
  try {
    const info = await stat(filePath);
    if (!info.isFile()) throw Object.assign(new Error("not a file"), { code: "ENOENT" });
    response.writeHead(200, {
      "content-type": MIME[path.extname(filePath).toLowerCase()] || "application/octet-stream",
      "cache-control": "no-store",
      "x-content-type-options": "nosniff",
    });
    if (request.method === "HEAD") {
      response.end();
      return;
    }
    createReadStream(filePath).pipe(response);
  } catch {
    response.writeHead(404, { "content-type": "text/plain; charset=utf-8" });
    response.end("Not found");
  }
}

async function serveFunction(request, response, url) {
  const controller = new AbortController();
  response.on("close", () => {
    if (!response.writableEnded) controller.abort();
  });
  const headers = new Headers();
  for (const [key, value] of Object.entries(request.headers)) {
    if (["host", "connection", "content-length", "accept-encoding"].includes(key)) continue;
    if (value !== undefined) headers.set(key, Array.isArray(value) ? value.join(",") : value);
  }
  const body = ["GET", "HEAD"].includes(request.method || "GET") ? undefined : await readBody(request);
  let chatResponse;
  try {
    chatResponse = await handler(new Request(url, {
      method: request.method,
      headers,
      body,
      signal: controller.signal,
    }));
  } catch {
    response.writeHead(500, { "content-type": "application/json; charset=utf-8" });
    response.end(JSON.stringify({ error: { code: "service_unavailable" } }));
    return;
  }
  response.writeHead(chatResponse.status, Object.fromEntries(chatResponse.headers));
  if (chatResponse.body && request.method !== "HEAD") Readable.fromWeb(chatResponse.body).pipe(response);
  else {
    await chatResponse.body?.cancel().catch(() => {});
    response.end();
  }
}

const server = createServer(async (request, response) => {
  let url;
  try {
    url = new URL(request.url || "/", `http://${request.headers.host || `${HOST}:${PORT}`}`);
  } catch {
    response.writeHead(400).end();
    return;
  }
  if (url.pathname.startsWith("/functions/v1/app/")) {
    await serveFunction(request, response, url);
    return;
  }
  let pathname;
  try {
    pathname = decodeURIComponent(url.pathname);
  } catch {
    response.writeHead(400, { "content-type": "text/plain; charset=utf-8" });
    response.end("Bad request");
    return;
  }
  // This server has no run data, so the demo always opens in fixture mode.
  if (request.method === "GET" && pathname === "/" && !url.searchParams.has("fixtures")) {
    response.writeHead(302, { location: "/?fixtures=1" });
    response.end();
    return;
  }
  await serveStatic(request, response, pathname);
});

server.listen(PORT, HOST, () => {
  console.log(`site dev · http://${HOST}:${PORT}`);
  console.log(`  serving ${WEB_ROOT}`);
  console.log("  mounting /functions/v1/app/api/chat with local-demo fixtures");
});

for (const signal of ["SIGINT", "SIGTERM"]) {
  process.on(signal, () => {
    service.close();
    server.close(() => process.exit(0));
  });
}
