import { consumeSSE } from './sse.mjs';

// Browser-local reader ownership only; not authorization, history or dispatch deduplication.
// Keep applyFrame synchronous: validate/project the frame, update this view, and return
// true only after handling a terminal state. Perform async history reads separately.
export function createConversationStream(applyFrame) {
  let active;
  const cancel = () => {
    const previous = active;
    active = undefined;
    previous?.abort();
  };
  return {
    cancel,
    async read(openResponse) {
      cancel();
      const controller = new AbortController();
      active = controller;
      let response;
      try {
        // Open inside this scope so a late fetch response cannot replace a newer reader.
        response = await openResponse(controller.signal);
        if (active !== controller) {
          await response.body?.cancel().catch(() => {});
          return;
        }
        await consumeSSE(response, frame => {
          if (active !== controller) return true;
          return applyFrame(frame);
        }, { signal: controller.signal });
      } catch (error) {
        // Switching/unmounting owns cancellation; only the active view receives errors.
        if (active === controller) throw error;
      } finally {
        if (active === controller) active = undefined;
      }
    },
  };
}
