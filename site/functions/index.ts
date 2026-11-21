import { createChatHandler } from './chat-handler.mjs';
import { createLiveService } from './live-service.mjs';

// `https://api.qoder.com` is runtime.cloudAgents.apiOrigin from sites.get_context.
// QODER_PAT stays platform-managed and is read only inside this Function.
Deno.serve(createChatHandler({
  service: createLiveService({ origin: 'https://api.qoder.com' }),
}));
