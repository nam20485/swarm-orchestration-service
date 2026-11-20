import { encodeSSE } from './sse.mjs';

const states = new Set(['idle', 'running', 'pending', 'completed', 'failed', 'interrupted']);
const terminal = new Set(['completed', 'failed', 'interrupted']);
const identifier = value => typeof value === 'string' && /^[A-Za-z0-9_-]{1,100}$/.test(value);
const codes = {
  chat_not_configured: [503, 'Connect a conversation service before using live chat.'],
  login_required: [401, 'Sign in to continue.'],
  forbidden: [403, 'This conversation is not available.'],
  not_found: [404, 'Conversation not found.'],
  invalid_request: [400, 'Check the message and try again.'],
  payload_too_large: [413, 'Use a shorter message.'],
  request_conflict: [409, 'This request ID belongs to another message.'],
  conversation_busy: [409, 'Wait for this reply or stop it before sending.'],
  dispatch_unknown: [202, 'Message outcome is pending. Recover its status without resending.'],
  rate_limited: [429, 'Too many messages. Try again in a few minutes.'],
  service_unavailable: [503, 'Chat is temporarily unavailable. Your message has been kept.'],
};

export class ChatError extends Error {
  constructor(code) { super(code); this.code = code; }
}

const fail = code => { throw new ChatError(code); };

// This is the only public projection. Cloud IDs, credentials and provider errors
// must stay inside the application's service implementation.
function snapshot(value) {
  if (!identifier(value?.id) || typeof value.title !== 'string' || value.title.length > 120
    || !Number.isSafeInteger(value.revision) || value.revision < 0
    || !states.has(value.state) || !Array.isArray(value.messages) || value.messages.length > 100) fail('service_unavailable');
  const messages = value.messages.map(message => {
    if (!identifier(message?.id) || !['user', 'assistant'].includes(message.role)
      || typeof message.text !== 'string' || message.text.length > 32000 || !states.has(message.state)) fail('service_unavailable');
    return { id: message.id, role: message.role, text: message.text, state: message.state };
  });
  const result = { id: value.id, title: value.title, revision: value.revision, state: value.state, messages,
    ...(identifier(value.runId) ? { runId: value.runId } : {}),
    ...(identifier(value.requestId) ? { requestId: value.requestId } : {}) };
  if (new TextEncoder().encode(JSON.stringify(result)).length > 240000) fail('service_unavailable');
  return result;
}

async function input(request) {
  if (request.headers.get('content-type')?.split(';')[0].trim() !== 'application/json') fail('invalid_request');
  const reader = request.body?.getReader();
  if (!reader) fail('invalid_request');
  const chunks = []; let length = 0;
  try {
    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      length += value.byteLength;
      if (length > 16384) { await reader.cancel(); fail('payload_too_large'); }
      chunks.push(value);
    }
  } finally { reader.releaseLock(); }
  const bytes = new Uint8Array(length); let offset = 0;
  for (const chunk of chunks) { bytes.set(chunk, offset); offset += chunk.length; }
  try {
    const parsed = JSON.parse(new TextDecoder('utf-8', { fatal: true }).decode(bytes));
    if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) fail('invalid_request');
    return parsed;
  } catch { fail('invalid_request'); }
}

function requestId(request) {
  const value = request.headers.get('idempotency-key');
  if (typeof value !== 'string' || !/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(value)) fail('invalid_request');
  return value;
}

/**
 * The application owns this service; there is no default production adapter.
 * Every method receives the authorized principal and must enforce ownership.
 * watch() registers before yielding the current snapshot, then yields monotonically
 * increasing snapshots. Its signal/return cleanup must release upstream readers.
 * @param {{ service?: {
 *   authorize: (request: Request) => Promise<{ id: string }>,
 *   info: () => { mode: 'local-demo' | 'live', persistence: string },
 *   list: (principal: { id: string }) => Promise<unknown[]>,
 *   create: (principal: { id: string }, command: { requestId: string }) => Promise<unknown>,
 *   get: (principal: { id: string }, id: string) => Promise<unknown>,
 *   send: (principal: { id: string }, id: string, command: { requestId: string, text: string, runId?: string }, request: Request) => Promise<unknown>,
 *   interrupt: (principal: { id: string }, id: string, command: { requestId: string, runId: string }) => Promise<unknown>,
 *   watch: (principal: { id: string }, id: string, options: { signal: AbortSignal }) => AsyncIterable<unknown>,
 * }, streamLifetimeMs?: number }} [options]
 */
export function createChatHandler({ service, streamLifetimeMs = 45000 } = {}) {
  if (!Number.isSafeInteger(streamLifetimeMs) || streamLifetimeMs < 1 || streamLifetimeMs > 60000) throw Error('chat_configuration_invalid');
  return async request => {
    const diagnosticId = crypto.randomUUID();
    try {
      const path = new URL(request.url).pathname.replace(/^\/(?:functions\/v1\/)?(?:app|app-d[0-9a-f]{32})(?=\/|$)/, '');
      if (!path.startsWith('/api/chat/')) return Response.json({ error: { code: 'not_found' } }, { status: 404 });
      if (!service || ['authorize', 'info', 'list', 'create', 'get', 'send', 'interrupt', 'watch'].some(key => typeof service[key] !== 'function')) fail('chat_not_configured');
      const principal = await service.authorize(request);
      if (!principal || typeof principal.id !== 'string' || !principal.id) fail('login_required');
      const json = (value, status = 200) => Response.json(value, { status, headers: responseHeaders(principal) });
      if (path === '/api/chat/config' && request.method === 'GET') {
        const info = service.info();
        return json({ mode: info.mode === 'local-demo' ? 'local-demo' : 'live' });
      }
      if (path === '/api/chat/conversations') {
        if (request.method === 'GET') {
          const items = await service.list(principal);
          if (!Array.isArray(items) || items.length > 100) fail('service_unavailable');
          return json({ conversations: items.map(item => {
            const value = snapshot(item);
            return { id: value.id, title: value.title, state: value.state };
          }) });
        }
        if (request.method === 'POST') {
          await input(request);
          return json({ conversation: snapshot(await service.create(principal, { requestId: requestId(request) })) }, 201);
        }
        return json({ error: { code: 'invalid_request' } }, 405);
      }
      const route = path.match(/^\/api\/chat\/conversations\/([A-Za-z0-9_-]{1,100})(?:\/(messages|events|interrupt))?$/);
      if (!route) fail('not_found');
      const [, id, action] = route;
      if (!action && request.method === 'GET') return json({ conversation: snapshot(await service.get(principal, id)) });
      if (action === 'messages' && request.method === 'POST') {
        const commandId = requestId(request), body = await input(request);
        if (typeof body.text !== 'string' || !body.text.trim() || body.text.length > 4000) fail('invalid_request');
        if (body.runId !== undefined && !identifier(body.runId)) fail('invalid_request');
        return json({ conversation: snapshot(await service.send(principal, id, {
          requestId: commandId, text: body.text.trim(), ...(body.runId ? { runId: body.runId } : {}),
        }, request)) }, 202);
      }
      if (action === 'interrupt' && request.method === 'POST') {
        const commandId = requestId(request), body = await input(request);
        if (!identifier(body.runId)) fail('invalid_request');
        return json({ conversation: snapshot(await service.interrupt(principal, id, { requestId: commandId, runId: body.runId })) });
      }
      if (action === 'events' && request.method === 'GET') {
        await service.get(principal, id); // Deny ownership before starting HTTP 200.
        return streamResponse(service, principal, id, request.signal, streamLifetimeMs);
      }
      return json({ error: { code: 'invalid_request' } }, 405);
    } catch (error) {
      const code = error instanceof ChatError && codes[error.code] ? error.code : 'service_unavailable';
      const [status, message] = codes[code];
      return Response.json({ error: { code, message, diagnosticId } }, { status, headers: { 'cache-control': 'no-store' } });
    }
  };
}

// The service may set its own browser session cookies on the authorized response.
function responseHeaders(principal, extra) {
  const headers = new Headers({ 'cache-control': 'no-store' });
  if (extra) for (const [name, value] of Object.entries(extra)) headers.set(name, value);
  if (Array.isArray(principal?.setCookie)) {
    for (const cookie of principal.setCookie) {
      if (typeof cookie === 'string' && cookie.length <= 1024 && !/[\r\n]/.test(cookie)) headers.append('set-cookie', cookie);
    }
  }
  return headers;
}

function streamResponse(service, principal, id, requestSignal, lifetimeMs) {
  const lifetime = new AbortController();
  let iterator, timer, heartbeat, output, closed = false, first = true;
  const cleanup = () => {
    if (closed) return;
    closed = true; clearTimeout(timer); clearInterval(heartbeat); lifetime.abort();
    requestSignal.removeEventListener('abort', abort);
    try { void Promise.resolve(iterator?.return?.()).catch(() => {}); } catch {}
  };
  const abort = () => { cleanup(); try { output?.close(); } catch {} };
  if (requestSignal.aborted) abort();
  else requestSignal.addEventListener('abort', abort, { once: true });
  const body = new ReadableStream({
    start(controller) {
      output = controller;
      if (closed) { controller.close(); return; }
      try {
        iterator = service.watch(principal, id, { signal: lifetime.signal })[Symbol.asyncIterator]();
        timer = setTimeout(abort, lifetimeMs);
        heartbeat = setInterval(() => {
          if (!closed && controller.desiredSize > 0) controller.enqueue(new TextEncoder().encode(': keepalive\n\n'));
        }, 10000);
      } catch (error) { cleanup(); throw error; }
    },
    async pull(controller) {
      try {
        const next = await iterator.next();
        if (closed) return;
        if (next.done) { cleanup(); controller.close(); return; }
        const conversation = snapshot(next.value);
        controller.enqueue(encodeSSE(first ? 'ready' : 'snapshot', { conversation }));
        const finished = !first && terminal.has(conversation.state);
        first = false;
        if (finished) { cleanup(); controller.close(); }
      } catch {
        if (!closed) {
          controller.enqueue(encodeSSE('stream-error', { code: 'service_unavailable' }));
          cleanup(); controller.close();
        }
      }
    },
    cancel: cleanup,
  });
  return new Response(body, { headers: responseHeaders(principal, {
    'content-type': 'text/event-stream; charset=utf-8',
    'cache-control': 'no-store, no-transform',
  }) });
}
