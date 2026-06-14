// Saved conversations, persisted to localStorage so users can resume past threads.
// Pure store — no DOM. Every write emits a "history-changed" event for the UI to
// re-render the conversations list.

const KEY = "support-assistant-ui/conversations/v1";
const MAX_CONVERSATIONS = 50;
export const HISTORY_EVENT = "history-changed";

function loadAll() {
  try {
    return JSON.parse(localStorage.getItem(KEY)) || {};
  } catch {
    return {};
  }
}

function saveAll(map) {
  // Keep only the most-recently-updated conversations to bound storage.
  const kept = Object.values(map)
    .sort((a, b) => b.updatedAt - a.updatedAt)
    .slice(0, MAX_CONVERSATIONS);
  const trimmed = {};
  for (const c of kept) trimmed[c.id] = c;
  try {
    localStorage.setItem(KEY, JSON.stringify(trimmed));
  } catch {
    /* quota exceeded — drop silently */
  }
}

function emitChanged() {
  document.dispatchEvent(new CustomEvent(HISTORY_EVENT));
}

function titleFrom(text) {
  const t = (text || "").trim().replace(/\s+/g, " ");
  if (!t) return "New chat";
  return t.length > 42 ? t.slice(0, 41) + "…" : t;
}

export function listConversations() {
  return Object.values(loadAll()).sort((a, b) => b.updatedAt - a.updatedAt);
}

export function getConversation(id) {
  return loadAll()[id] || null;
}

/**
 * Append a message to a conversation (creating it on first use), then persist.
 * @param {string} id            conversation id
 * @param {{role:string, text:string, runtime?:string, response?:object}} message
 * @param {{customerId?:number|null, runtime?:string}} [meta]
 */
export function upsertMessage(id, message, meta = {}) {
  const map = loadAll();
  const now = Date.now();
  let conv = map[id];
  if (!conv) {
    conv = {
      id,
      title: "New chat",
      customerId: meta.customerId ?? null,
      runtime: meta.runtime || "core",
      messages: [],
      createdAt: now,
      updatedAt: now,
    };
    map[id] = conv;
  }
  conv.messages.push(message);
  if (conv.title === "New chat" && message.role === "user") conv.title = titleFrom(message.text);
  if (meta.customerId !== undefined) conv.customerId = meta.customerId;
  if (meta.runtime) conv.runtime = meta.runtime;
  conv.updatedAt = now;
  saveAll(map);
  emitChanged();
  return conv;
}

export function deleteConversation(id) {
  const map = loadAll();
  if (map[id]) {
    delete map[id];
    saveAll(map);
    emitChanged();
  }
}
