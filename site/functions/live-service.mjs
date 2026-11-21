// Live conversation service for the Swarm Ops Console.
//
// Browser -> same-origin Function -> Qoder Cloud Agents. The browser gets an
// opaque conversation id backed by one Cloud Session per browser session; the
// visitor cookie and Cloud metadata together establish ownership. There is no
// application database: the process-local state below is a cache, never a
// durable coordinator. Cloud history is the source of truth for replies, so a
// cold Function instance can recover completed turns from the Session.
import { CloudAgentsError, createCloudAgentsClient, ensureCloudResources } from './cloud-agents.mjs';
import { ChatError } from './chat-handler.mjs';
import { readSSE } from './sse.mjs';
import {
  SYSTEM_INSTRUCTIONS, buildAugmentedText, contentText, knownRun, projectUserText, requestIdFromContent,
} from './run-context.mjs';

const APP = 'swarm-ops-console';
const PURPOSE = 'run-analyst';
// Stable across redeploys. Changing it invalidates existing visitor bindings.
const APPLICATION_SCOPE = 'swarm-ops-console:production:v1';
const VISITOR_COOKIE = 'swarm_v';
const SESSION_COOKIE = 'swarm_s';
const VISITOR_PATTERN = /^[a-f0-9]{64}$/;
const SESSION_PATTERN = /^sess_[A-Za-z0-9_-]{1,100}$/;
// Kept short enough that `run_${event.id}` still fits the handler's 100-char identifier bound.
const EVENT_PATTERN = /^evt_[A-Za-z0-9_-]{1,90}$/;
const HISTORY_TYPES = 'user.message,user.interrupt,agent.message,session.status_idle,session.error';
const MAX_TURNS = 15;
const MAX_ASSISTANT_CHARS = 8000;
const MAX_HISTORY_PAGES = 12;
const MESSAGES_PER_HOUR = 40;
const SUCCESS_STOPS = new Set(['end_turn', 'max_tokens', 'stop_sequence']);

const hex = bytes => Array.from(crypto.getRandomValues(new Uint8Array(bytes)), byte => byte.toString(16).padStart(2, '0')).join('');

async function digest(value) {
  const hash = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(value));
  return Array.from(new Uint8Array(hash), byte => byte.toString(16).padStart(2, '0')).join('');
}

function cookies(request) {
  const header = request.headers.get('cookie');
  const result = {};
  if (!header) return result;
  for (const part of header.split(';')) {
    const index = part.indexOf('=');
    if (index < 0) continue;
    const name = part.slice(0, index).trim();
    const value = part.slice(index + 1).trim();
    if (name && !(name in result)) result[name] = value;
  }
  return result;
}

const cookie = (name, value) => `${name}=${value}; Path=/; HttpOnly; Secure; SameSite=Strict`;
const clearCookie = name => `${name}=; Path=/; HttpOnly; Secure; SameSite=Strict; Max-Age=0`;

function appError(error) {
  if (error instanceof ChatError) return error;
  if (error instanceof CloudAgentsError) {
    switch (error.code) {
      case 'ai_not_configured': return new ChatError('chat_not_configured');
      case 'ai_rate_limited': return new ChatError('rate_limited');
      case 'ai_conflict': return new ChatError('conversation_busy');
      case 'ai_resource_not_found': return new ChatError('not_found');
      case 'ai_request_unknown':
      case 'ai_initialization_pending': return new ChatError('dispatch_unknown');
      case 'ai_request_invalid':
      case 'ai_request_rejected': return new ChatError('invalid_request');
      default: return new ChatError('service_unavailable');
    }
  }
  return new ChatError('service_unavailable');
}

// Serializes work inside one Function instance. It is not a durable lock; the
// Cloud resource metadata scan is what makes reuse and recovery work.
function createProcessCoordinator() {
  const records = new Map();
  const queues = new Map();
  return {
    withLock(key, callback) {
      const prior = queues.get(key) || Promise.resolve();
      const run = prior.catch(() => {}).then(async () => {
        const lease = {
          async read() { return records.get(key) || null; },
          async write(value) { records.set(key, value); },
          async assertHeld() {},
        };
        return callback(lease);
      });
      queues.set(key, run);
      run.finally(() => { if (queues.get(key) === run) queues.delete(key); }).catch(() => {});
      return run;
    },
  };
}

function createKeyLock() {
  const queues = new Map();
  return (key, callback) => {
    const prior = queues.get(key) || Promise.resolve();
    const run = prior.catch(() => {}).then(callback);
    queues.set(key, run);
    run.finally(() => { if (queues.get(key) === run) queues.delete(key); }).catch(() => {});
    return run;
  };
}

export function createLiveService({ origin, getToken } = {}) {
  const cloud = createCloudAgentsClient({ origin, ...(getToken ? { getToken } : {}) });
  const coordinator = createProcessCoordinator();
  const createLock = createKeyLock();
  const sessions = new Map();
  const usage = new Map();
  const revisions = new Map();
  let bindingPromise;
  let chosenModel;

  function localState(id) {
    let state = sessions.get(id);
    if (!state) {
      state = { requests: new Map(), pending: null, interrupted: new Set(), drafts: new Map() };
      if (sessions.size > 2000) sessions.clear();
      sessions.set(id, state);
    }
    return state;
  }

  function nextRevision(id) {
    const value = Math.max(Date.now(), (revisions.get(id) || 0) + 1);
    revisions.set(id, value);
    if (revisions.size > 4000) revisions.clear();
    return value;
  }

  const ownerOf = visitor => digest(`${APPLICATION_SCOPE}:visitor:${visitor}`);

  function owns(session, principal) {
    const metadata = session?.metadata;
    return typeof metadata === 'object' && metadata !== null
      && metadata.app === APP && metadata.purpose === PURPOSE
      && metadata.owner === principal.owner;
  }

  function ownsIntent(session, principal, intent) {
    return owns(session, principal) && session.metadata.intent === intent;
  }

  async function sessionById(id) {
    const session = await cloud.request(`/api/v1/cloud/sessions/${id}`);
    if (!session || session.id !== id) throw new CloudAgentsError('ai_response_invalid');
    return session;
  }

  async function owned(principal, id) {
    if (!SESSION_PATTERN.test(id)) throw new ChatError('not_found');
    let session;
    try {
      session = await sessionById(id);
    } catch (error) {
      if (error instanceof CloudAgentsError && error.code === 'ai_resource_not_found') {
        principal.setCookie.push(clearCookie(SESSION_COOKIE));
        throw new ChatError('not_found');
      }
      throw error;
    }
    if (!owns(session, principal)) throw new ChatError('not_found');
    if (session.archived_at || ['deleted', 'terminated'].includes(session.status)) {
      principal.setCookie.push(clearCookie(SESSION_COOKIE));
      throw new ChatError('not_found');
    }
    return session;
  }

  async function chooseModel() {
    if (chosenModel) return chosenModel;
    const result = await cloud.request('/api/v1/cloud/models');
    if (!Array.isArray(result?.data)) throw new CloudAgentsError('ai_response_invalid');
    const enabled = result.data
      .filter(model => model && model.is_enabled === true && typeof model.id === 'string' && model.id)
      .map(model => model.id)
      .sort();
    if (!enabled.length) throw new CloudAgentsError('ai_configuration_invalid');
    chosenModel = enabled.includes('ultimate') ? 'ultimate' : enabled[0];
    return chosenModel;
  }

  function binding() {
    if (!bindingPromise) {
      bindingPromise = (async () => {
        const model = await chooseModel();
        return ensureCloudResources({
          client: cloud,
          coordinator,
          applicationScope: APPLICATION_SCOPE,
          agent: {
            name: 'Swarm ops run analyst',
            model,
            system: SYSTEM_INSTRUCTIONS,
            tools: [],
            metadata: { app: APP, purpose: PURPOSE },
          },
          environment: {
            name: 'Swarm ops console environment',
            config: { type: 'cloud' },
            metadata: { app: APP, purpose: PURPOSE },
          },
        });
      })().catch(error => { bindingPromise = null; throw error; });
    }
    return bindingPromise;
  }

  async function ownedSessions(principal) {
    const found = [];
    let cursor, pages = 0;
    while (pages < 6) {
      const query = `/api/v1/cloud/sessions?limit=100${cursor ? `&after_id=${encodeURIComponent(cursor)}` : ''}`;
      const page = await cloud.request(query);
      if (!Array.isArray(page?.data) || typeof page.has_more !== 'boolean') throw new CloudAgentsError('ai_response_invalid');
      for (const session of page.data) {
        if (!session || typeof session.id !== 'string' || !SESSION_PATTERN.test(session.id)) continue;
        if (session.archived_at || ['deleted', 'terminated'].includes(session.status)) continue;
        if (owns(session, principal)) found.push(session);
      }
      if (!page.has_more) return found;
      if (typeof page.last_id !== 'string' || !page.last_id || page.last_id === cursor) throw new CloudAgentsError('ai_response_invalid');
      cursor = page.last_id;
      pages += 1;
    }
    throw new CloudAgentsError('ai_response_invalid');
  }

  async function adopt(principal) {
    const found = await ownedSessions(principal);
    if (!found.length) return null;
    const session = found[0];
    principal.setCookie.push(cookie(SESSION_COOKIE, session.id));
    return session;
  }

  async function fetchHistory(id) {
    const events = [];
    let cursor, pages = 0;
    while (pages < MAX_HISTORY_PAGES) {
      const query = `/api/v1/cloud/sessions/${id}/events?order=asc&limit=100&type=${encodeURIComponent(HISTORY_TYPES)}`
        + (cursor ? `&after_id=${encodeURIComponent(cursor)}` : '');
      const page = await cloud.request(query);
      if (!Array.isArray(page?.data) || typeof page.has_more !== 'boolean') throw new CloudAgentsError('ai_response_invalid');
      for (const event of page.data) {
        if (event && typeof event === 'object' && typeof event.type === 'string') events.push(event);
      }
      if (!page.has_more) break;
      if (typeof page.last_id !== 'string' || !page.last_id || page.last_id === cursor) throw new CloudAgentsError('ai_response_invalid');
      cursor = page.last_id;
      pages += 1;
    }
    if (pages >= MAX_HISTORY_PAGES) throw new CloudAgentsError('ai_response_invalid');
    const lastId = events.length && EVENT_PATTERN.test(events.at(-1).id) ? events.at(-1).id : null;
    return { events, lastId };
  }

  function newTurn(event) {
    return {
      userEventId: event.id,
      requestId: requestIdFromContent(event.content) || undefined,
      text: projectUserText(event.content),
      parts: [],
      state: 'running',
      terminal: null,
    };
  }

  // Applies one public Cloud event to the console projection. Returns true when
  // the visible conversation may have changed.
  function applyEvent(turns, event, local) {
    switch (event.type) {
      case 'user.message': {
        if (!EVENT_PATTERN.test(event.id)) return false;
        if (turns.some(turn => turn.userEventId === event.id)) return false;
        const turn = newTurn(event);
        if (!turn.text) return false;
        turns.push(turn);
        local?.drafts.clear();
        if (local?.interrupted.has(turn.userEventId)) { turn.state = 'interrupted'; turn.terminal = 'interrupt'; }
        return true;
      }
      case 'agent.message': {
        const turn = turns.at(-1);
        if (!turn || !EVENT_PATTERN.test(event.id)) return false;
        const text = clipText(contentText(event.content));
        const part = turn.parts.find(item => item.id === event.id);
        if (part) {
          if (part.text === text && part.done) return false;
          part.text = text;
          part.done = true;
        } else {
          turn.parts.push({ id: event.id, text, done: true });
        }
        return true;
      }
      case 'session.status_idle': {
        const turn = turns.at(-1);
        if (!turn || turn.terminal) return false;
        const stop = event.stop_reason?.type;
        if (stop === 'requires_action') { turn.state = 'failed'; turn.terminal = 'requires_action'; }
        else if (typeof stop === 'string' && !SUCCESS_STOPS.has(stop)) { turn.state = 'failed'; turn.terminal = stop; }
        else { turn.state = 'completed'; turn.terminal = stop || 'end_turn'; }
        return true;
      }
      case 'session.error': {
        const turn = turns.at(-1);
        if (!turn || turn.terminal) return false;
        if (event.retry_status?.type === 'retrying') return false;
        turn.state = 'failed';
        turn.terminal = 'error';
        return true;
      }
      case 'user.interrupt': {
        const turn = turns.at(-1);
        if (!turn) return false;
        turn.state = 'interrupted';
        turn.terminal = 'interrupt';
        local?.interrupted.add(turn.userEventId);
        return true;
      }
      default:
        return false;
    }
  }

  function project(events, local) {
    const turns = [];
    for (const event of events) applyEvent(turns, event, local);
    if (local) {
      const last = turns.at(-1);
      if (last && local.drafts.size) {
        for (const [id, draft] of local.drafts) {
          const part = last.parts.find(item => item.id === id);
          if (part?.done) { local.drafts.delete(id); continue; }
          if (!part) last.parts.push({ id, text: draft.text, done: false });
        }
      }
      for (const turn of turns) {
        if (local.interrupted.has(turn.userEventId) && turn.state !== 'interrupted') {
          turn.state = 'interrupted';
          turn.terminal = 'interrupt';
        }
      }
    }
    return turns;
  }

  const clipText = value => (value.length > MAX_ASSISTANT_CHARS ? `${value.slice(0, MAX_ASSISTANT_CHARS - 1)}…` : value);
  const turnText = turn => clipText(turn.parts.map(part => part.text).join(''));

  function conversationState(turns, session, pending) {
    const last = turns.at(-1);
    if (pending && (!last || last.requestId !== pending.requestId)) return 'running';
    if (!last) return 'idle';
    if (session.archived_at) return last.state === 'completed' ? 'completed' : 'failed';
    switch (session.status) {
      case 'running':
      case 'canceling': return 'running';
      case 'rescheduled': return 'pending';
      case 'terminated':
      case 'deleted': return last.state === 'completed' ? 'completed' : 'failed';
      default: return last.state;
    }
  }

  function buildSnapshot(id, turns, session, local) {
    const pending = local.pending;
    const historyHasPending = pending && turns.some(turn => turn.requestId === pending.requestId
      || (pending.acceptedEventId && turn.userEventId === pending.acceptedEventId));
    if (historyHasPending) local.pending = null;
    const overlay = pending && !historyHasPending ? pending : null;
    const visible = turns.slice(-MAX_TURNS);
    const messages = [];
    for (const turn of visible) {
      messages.push({ id: `u_${turn.userEventId}`, role: 'user', text: turn.text, state: 'completed' });
      let text = turnText(turn);
      if (turn.terminal === 'requires_action') {
        text += `${text ? '\n\n' : ''}_This console does not support tool approvals, so the answer stopped._`;
      }
      messages.push({ id: `a_${turn.userEventId}`, role: 'assistant', text, state: turn.state });
    }
    let key = visible.at(-1)?.userEventId;
    if (overlay) {
      key = EVENT_PATTERN.test(overlay.acceptedEventId || '') ? overlay.acceptedEventId : `tmp_${overlay.requestId.replace(/-/g, '')}`;
      messages.push({ id: `u_${key}`, role: 'user', text: overlay.text, state: 'completed' });
      messages.push({ id: `a_${key}`, role: 'assistant', text: overlay.partial || '', state: overlay.interrupted ? 'interrupted' : 'running' });
    }
    const state = overlay ? (overlay.interrupted ? 'interrupted' : 'running') : conversationState(visible, session, null);
    const last = visible.at(-1);
    const requestId = overlay?.requestId || last?.requestId;
    const first = turns[0]?.text || overlay?.text || '';
    return {
      id,
      title: (first || 'Run analysis').slice(0, 48),
      revision: nextRevision(id),
      state,
      messages,
      ...(['running', 'pending'].includes(state) && key ? { runId: `run_${key}` } : {}),
      ...(requestId ? { requestId } : {}),
    };
  }

  async function snapshotFor(principal, session) {
    const local = localState(session.id);
    const { events } = await fetchHistory(session.id);
    const turns = project(events, local);
    return buildSnapshot(session.id, turns, session, local);
  }

  async function reconcilePending(principal, session) {
    const local = localState(session.id);
    if (!local.pending?.requestId) return;
    const { events } = await fetchHistory(session.id);
    const turns = project(events, local);
    if (turns.some(turn => turn.requestId === local.pending.requestId)) local.pending = null;
  }

  function assertQuota(visitor) {
    const now = Date.now();
    const entry = usage.get(visitor);
    if (!entry || now - entry.start > 3600_000) return;
    if (entry.count >= MESSAGES_PER_HOUR) throw new ChatError('rate_limited');
  }

  function recordUse(visitor) {
    const now = Date.now();
    let entry = usage.get(visitor);
    if (!entry || now - entry.start > 3600_000) {
      entry = { start: now, count: 0 };
      usage.set(visitor, entry);
    }
    entry.count += 1;
    if (usage.size > 4000) {
      for (const [key, value] of usage) if (now - value.start > 3600_000) usage.delete(key);
    }
  }

  async function createSession(principal, requestId) {
    const bindingValue = await binding();
    const intent = await digest(`${APPLICATION_SCOPE}:session:${requestId}`);
    const meta = { app: APP, purpose: PURPOSE, owner: principal.owner, intent };
    const session = await cloud.request('/api/v1/cloud/sessions', {
      method: 'POST',
      idempotencyKey: `sites-session-${intent}`,
      body: {
        agent: { id: bindingValue.agent.id, type: 'agent', version: bindingValue.agent.version },
        environment_id: bindingValue.environment_id,
        title: 'Swarm ops console',
        metadata: meta,
      },
    });
    if (!session || typeof session.id !== 'string' || !SESSION_PATTERN.test(session.id)) {
      // The write may have succeeded; recover by the intent metadata instead of retrying.
      const recovered = (await ownedSessions(principal)).find(item => item.metadata?.intent === intent);
      if (!recovered) throw new CloudAgentsError('ai_request_unknown');
      principal.setCookie.push(cookie(SESSION_COOKIE, recovered.id));
      return sessionById(recovered.id);
    }
    if (!ownsIntent(session, principal, intent)) throw new CloudAgentsError('ai_response_invalid');
    principal.setCookie.push(cookie(SESSION_COOKIE, session.id));
    localState(session.id);
    return session;
  }

  async function getOrCreate(principal, requestId) {
    if (principal.sessionId) {
      try {
        return await owned(principal, principal.sessionId);
      } catch (error) {
        if (!(error instanceof ChatError) || error.code !== 'not_found') throw error;
        principal.setCookie.push(clearCookie(SESSION_COOKIE));
        principal.sessionId = null;
      }
    }
    const adopted = await adopt(principal);
    if (adopted) return adopted;
    return createLock(principal.visitor, async () => {
      const again = await ownedSessions(principal);
      if (again.length) {
        principal.setCookie.push(cookie(SESSION_COOKIE, again[0].id));
        return again[0];
      }
      return createSession(principal, requestId);
    });
  }

  async function* watch(principal, id, { signal }) {
    const session = await owned(principal, id);
    const local = localState(id);
    // Connect upstream before reading history so no event can fall between the
    // read and the live stream. Buffered history covers everything before the
    // connection; the stream covers deltas and events after it.
    let upstream;
    try {
      upstream = await cloud.openStream(id, { signal });
    } catch (error) {
      throw appError(error);
    }
    let events;
    try {
      ({ events } = await fetchHistory(id));
    } catch (error) {
      upstream.close();
      throw appError(error);
    }
    const turns = project(events, local);
    if (local.pending && turns.some(turn => turn.requestId === local.pending.requestId
      || (local.pending.acceptedEventId && turn.userEventId === local.pending.acceptedEventId))) local.pending = null;
    yield buildSnapshot(id, turns, session, local);
    let lastYield = 0;
    const shouldYield = force => {
      const now = performance.now();
      if (force || now - lastYield >= 120) { lastYield = now; return true; }
      return false;
    };
    try {
      for await (const frame of readSSE(upstream.body, { signal })) {
        if (signal.aborted) return;
        let payload;
        try { payload = JSON.parse(frame.data); } catch { continue; }
        const type = typeof payload?.type === 'string' ? payload.type : frame.event;
        let changed = false;
        let finished = false;
        if (type === 'event_start') {
          const event = payload.event;
          if (event?.type === 'agent.message' && EVENT_PATTERN.test(event.id || '')) {
            const turn = turns.at(-1);
            if (turn) {
              const part = turn.parts.find(item => item.id === event.id);
              if (!part) {
                turn.parts.push({ id: event.id, text: '', done: false });
                local.drafts.set(event.id, { text: '' });
                changed = true;
              } else if (!part.done) {
                part.text = ''; // A replay starts this draft over.
                local.drafts.set(event.id, { text: '' });
                changed = true;
              }
            }
          }
        } else if (type === 'event_delta') {
          const turn = turns.at(-1);
          const delta = payload.delta;
          if (turn && EVENT_PATTERN.test(payload.event_id || '') && delta?.type === 'content_delta'
            && delta.content?.type === 'text' && typeof delta.content.text === 'string') {
            let part = turn.parts.find(item => item.id === payload.event_id);
            if (!part) {
              part = { id: payload.event_id, text: '', done: false };
              turn.parts.push(part);
            }
            if (!part.done && part.text.length < MAX_ASSISTANT_CHARS) {
              part.text = (part.text + delta.content.text.slice(0, 4000)).slice(0, MAX_ASSISTANT_CHARS);
              local.drafts.set(payload.event_id, { text: part.text });
              changed = true;
            }
          }
        } else if (type === 'agent.message' || type === 'user.message' || type === 'user.interrupt'
          || type === 'session.status_idle' || type === 'session.error') {
          changed = applyEvent(turns, payload, local);
          if (type === 'agent.message' && EVENT_PATTERN.test(payload.id || '')) local.drafts.delete(payload.id);
          if (type === 'user.interrupt' || type === 'session.status_idle') finished = true;
          if (type === 'session.error' && payload.retry_status?.type !== 'retrying') finished = true;
        } else if (type === 'session.status_running' || type === 'session.status_rescheduled') {
          const nextStatus = type === 'session.status_running' ? 'running' : 'rescheduled';
          changed = session.status !== nextStatus;
          session.status = nextStatus;
        } else if (typedTerminal(type)) {
          const turn = turns.at(-1);
          if (turn && !turn.terminal) { turn.state = 'failed'; turn.terminal = 'terminated'; }
          session.status = type === 'session.status_deleted' ? 'deleted' : 'terminated';
          changed = true;
          finished = true;
        }
        if (changed && shouldYield(false)) yield buildSnapshot(id, turns, session, local);
        if (finished) {
          yield buildSnapshot(id, turns, session, local);
          return;
        }
      }
    } catch (error) {
      if (signal.aborted) return;
      throw appError(error);
    } finally {
      upstream.close();
    }
    if (signal.aborted) return;
    // EOF is not completion. Reconcile once, and only close when the Session is terminal.
    let current;
    try {
      current = await sessionById(id);
    } catch {
      throw new ChatError('service_unavailable');
    }
    if (!owns(current, principal)) throw new ChatError('not_found');
    const state = conversationState(turns.slice(-MAX_TURNS), current, local.pending);
    if (['completed', 'failed', 'interrupted'].includes(state)) {
      yield buildSnapshot(id, turns, current, local);
      return;
    }
    throw new ChatError('service_unavailable');
  }

  return {
    async authorize(request) {
      const jar = cookies(request);
      const setCookie = [];
      let visitor = VISITOR_PATTERN.test(jar[VISITOR_COOKIE] || '') ? jar[VISITOR_COOKIE] : null;
      if (!visitor) {
        visitor = hex(32);
        setCookie.push(cookie(VISITOR_COOKIE, visitor));
      }
      const sessionId = SESSION_PATTERN.test(jar[SESSION_COOKIE] || '') ? jar[SESSION_COOKIE] : null;
      return {
        id: `visitor_${visitor.slice(0, 16)}`,
        visitor,
        sessionId,
        owner: await ownerOf(visitor),
        setCookie,
      };
    },

    /** @returns {{ mode: 'live', persistence: string }} */
    info() {
      return { mode: 'live', persistence: 'cloud-session' };
    },

    async list(principal) {
      try {
        if (principal.sessionId) {
          let session;
          try {
            session = await owned(principal, principal.sessionId);
          } catch (error) {
            if (error instanceof ChatError && error.code === 'not_found') return [];
            throw error;
          }
          return [await snapshotFor(principal, session)];
        }
        const session = await adopt(principal);
        if (!session) return [];
        return [await snapshotFor(principal, session)];
      } catch (error) {
        throw appError(error);
      }
    },

    async create(principal, { requestId }) {
      try {
        const session = await getOrCreate(principal, requestId);
        return await snapshotFor(principal, session);
      } catch (error) {
        throw appError(error);
      }
    },

    async get(principal, id) {
      try {
        const session = await owned(principal, id);
        return await snapshotFor(principal, session);
      } catch (error) {
        throw appError(error);
      }
    },

    async send(principal, id, command) {
      const { requestId, text, runId } = command;
      try {
        const session = await owned(principal, id);
        const local = localState(id);
        const previous = local.requests.get(requestId);
        if (previous) {
          if (previous.text !== text) throw new ChatError('request_conflict');
          if (previous.state === 'accepted') return await snapshotFor(principal, session);
          if (previous.state === 'unknown') {
            await reconcilePending(principal, session);
            if (local.pending?.requestId === requestId) return await snapshotFor(principal, session);
            throw new ChatError('dispatch_unknown');
          }
        }
        if (runId && !knownRun(runId)) throw new ChatError('invalid_request');
        if (['running', 'canceling', 'rescheduled'].includes(session.status)) throw new ChatError('conversation_busy');
        assertQuota(principal.visitor);
        const { events } = await fetchHistory(id);
        const turns = project(events, local);
        recordUse(principal.visitor);
        const pending = {
          requestId,
          text,
          acceptedEventId: null,
          runId: `run_tmp_${requestId.replace(/-/g, '')}`,
          partial: '',
        };
        local.requests.set(requestId, { text, state: 'sending' });
        if (local.requests.size > 100) local.requests.delete(local.requests.keys().next().value);
        let accepted = false;
        try {
          const result = await cloud.request(`/api/v1/cloud/sessions/${id}/events`, {
            method: 'POST',
            body: { events: [{ type: 'user.message', content: [{ type: 'text', text: buildAugmentedText(text, requestId, runId) }] }] },
          });
          const event = Array.isArray(result?.data)
            ? result.data.find(item => item?.type === 'user.message' && EVENT_PATTERN.test(item.id || ''))
            : null;
          if (event) {
            pending.acceptedEventId = event.id;
            pending.runId = `run_${event.id}`;
          }
          local.pending = pending;
          local.requests.set(requestId, { text, state: 'accepted' });
          accepted = true;
        } catch (error) {
          if (error instanceof CloudAgentsError && ['ai_request_unknown', 'ai_service_unavailable'].includes(error.code)) {
            // The write may have landed. Reconcile by the server-owned request marker.
            local.requests.set(requestId, { text, state: 'unknown' });
            try {
              const history = await fetchHistory(id);
              const found = project(history.events, local).find(turn => turn.requestId === requestId);
              if (found) {
                pending.acceptedEventId = found.userEventId;
                pending.runId = `run_${found.userEventId}`;
                local.pending = pending;
                local.requests.set(requestId, { text, state: 'accepted' });
                accepted = true;
              }
            } catch { /* Pending stays unknown; the client recovers via reads. */ }
            if (!accepted) throw new ChatError('dispatch_unknown');
          } else {
            local.requests.set(requestId, { text, state: 'rejected' });
            throw error;
          }
        }
        return buildSnapshot(id, turns, session, local);
      } catch (error) {
        throw appError(error);
      }
    },

    async interrupt(principal, id, { runId }) {
      try {
        const session = await owned(principal, id);
        const local = localState(id);
        const { events } = await fetchHistory(id);
        const turns = project(events, local);
        const last = turns.at(-1);
        const expected = [
          last ? `run_${last.userEventId}` : null,
          local.pending?.runId || null,
          local.pending?.acceptedEventId ? `run_${local.pending.acceptedEventId}` : null,
        ].filter(Boolean);
        if (!expected.includes(runId)) throw new ChatError('request_conflict');
        if (!['running', 'canceling', 'rescheduled'].includes(session.status)) {
          return buildSnapshot(id, turns, session, local);
        }
        await cloud.request(`/api/v1/cloud/sessions/${id}/cancel`, { method: 'POST' });
        if (last && runId === `run_${last.userEventId}`) {
          local.interrupted.add(last.userEventId);
          last.state = 'interrupted';
          last.terminal = 'interrupt';
        }
        if (local.pending && (runId === local.pending.runId
          || (local.pending.acceptedEventId && runId === `run_${local.pending.acceptedEventId}`))) {
          local.pending.interrupted = true;
          if (local.pending.acceptedEventId) local.interrupted.add(local.pending.acceptedEventId);
        }
        // Cancel is applied asynchronously; present the stopping state now and let
        // the next read confirm the idle transition.
        session.status = 'idle';
        return buildSnapshot(id, turns, session, local);
      } catch (error) {
        throw appError(error);
      }
    },

    watch,
  };
}

// Public lifecycle events that are not part of the filtered console history but
// may arrive on the stream and should end a watch.
function typedTerminal(type) {
  return type === 'session.status_terminated' || type === 'session.status_deleted';
}
