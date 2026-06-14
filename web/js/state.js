// Shared session state, persisted to localStorage so a refresh keeps the customer,
// conversation, and selected runtime. The conversation id is generated client-side.

const STORAGE_KEY = "support-assistant-ui/v1";

function load() {
  try {
    return JSON.parse(localStorage.getItem(STORAGE_KEY)) || {};
  } catch {
    return {};
  }
}

function persist() {
  try {
    localStorage.setItem(
      STORAGE_KEY,
      JSON.stringify({
        customerId: state.customerId,
        conversationId: state.conversationId,
        runtime: state.runtime,
      }),
    );
  } catch {
    /* storage unavailable — non-fatal */
  }
}

export function newConversationId() {
  const rand = Math.random().toString(36).slice(2, 8);
  return `conv-${Date.now().toString(36)}-${rand}`;
}

const saved = load();

export const state = {
  customerId: saved.customerId === undefined ? 1 : saved.customerId, // number | null
  conversationId: saved.conversationId || newConversationId(),
  runtime: saved.runtime || "core",
  confidenceThreshold: 0.55,
  capabilities: { runtimes: ["core"] },
};

export function setCustomerId(value) {
  state.customerId = value;
  persist();
}

export function setRuntime(value) {
  state.runtime = value;
  persist();
}

export function resetConversation() {
  state.conversationId = newConversationId();
  persist();
  return state.conversationId;
}

export function setConversation(id) {
  state.conversationId = id;
  persist();
}

export function setCapabilities(caps) {
  state.capabilities = caps || { runtimes: ["core"] };
  if (typeof caps?.confidence_threshold === "number") {
    state.confidenceThreshold = caps.confidence_threshold;
  }
  // If a previously-saved runtime is no longer mounted, fall back to core.
  if (!state.capabilities.runtimes?.includes(state.runtime)) {
    setRuntime("core");
  }
}
