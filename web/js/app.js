// Entry point: restore state, fetch capabilities + readiness, build the runtime
// switcher, render the conversations list, and wire navigation + session controls.

import { el, clear, byId } from "./dom.js";
import {
  state,
  setCustomerId,
  setRuntime,
  setConversation,
  resetConversation,
  setCapabilities,
} from "./state.js";
import { getCapabilities, getReady } from "./api.js";
import { initChat, resetChat, setTraceRuntime, loadConversation } from "./chat.js";
import { loadOperatorTab } from "./operator.js";
import { listConversations, getConversation, deleteConversation, HISTORY_EVENT } from "./history.js";

const RUNTIME_LABELS = { core: "Core", adk: "ADK", sk: "SK" };
const RUNTIME_HINTS = {
  core: "Deterministic pipeline — full guardrails, routing & trace.",
  adk: "Google ADK — LLM-driven delegation over MCP tools.",
  sk: "Semantic Kernel — LLM handoff orchestration over MCP tools.",
};

let currentOpTab = "routes";

function setView(view) {
  byId("app").dataset.view = view;
  document.querySelectorAll("[data-nav]").forEach((b) => b.classList.toggle("is-active", b.dataset.nav === view));
  if (view === "operator") loadOperatorTab(currentOpTab);
}

/* ----------------------------------------------------------- runtime switcher */

function buildRuntimeSwitcher() {
  const host = byId("runtime-switcher");
  clear(host);
  for (const rt of state.capabilities.runtimes || ["core"]) {
    host.append(
      el("button", {
        class: "seg__btn" + (rt === state.runtime ? " is-active" : ""),
        type: "button",
        role: "tab",
        dataset: { runtime: rt },
        text: RUNTIME_LABELS[rt] || rt,
        onClick: () => selectRuntime(rt),
      }),
    );
  }
  updateRuntimeHint();
}

function selectRuntime(rt) {
  setRuntime(rt);
  byId("runtime-switcher")
    .querySelectorAll(".seg__btn")
    .forEach((b) => b.classList.toggle("is-active", b.dataset.runtime === rt));
  setTraceRuntime(rt);
  updateRuntimeHint();
}

function updateRuntimeHint() {
  byId("runtime-hint").textContent = RUNTIME_HINTS[state.runtime] || "";
}

/* -------------------------------------------------------- conversations panel */

function timeAgo(ts) {
  const s = Math.floor((Date.now() - ts) / 1000);
  if (s < 60) return "just now";
  const m = Math.floor(s / 60);
  if (m < 60) return `${m}m ago`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h}h ago`;
  const d = Math.floor(h / 24);
  if (d < 7) return `${d}d ago`;
  return new Date(ts).toLocaleDateString();
}

function renderConversationList() {
  const host = byId("conversation-list");
  clear(host);
  const convos = listConversations();
  if (!convos.length) {
    host.append(
      el("div", { class: "convos__empty", text: "No saved conversations yet — start chatting and they'll appear here." }),
    );
    return;
  }
  for (const c of convos) {
    const bits = [timeAgo(c.updatedAt)];
    if (c.runtime && c.runtime !== "core") bits.push(c.runtime.toUpperCase());
    if (typeof c.customerId === "number") bits.push(`cust ${c.customerId}`);
    host.append(
      el("div", { class: "convo" + (c.id === state.conversationId ? " is-active" : ""), dataset: { id: c.id } }, [
        el("button", { class: "convo__main", type: "button", title: c.title, onClick: () => selectConversation(c.id) }, [
          el("span", { class: "convo__title", text: c.title }),
          el("span", { class: "convo__meta", text: bits.join(" · ") }),
        ]),
        el(
          "button",
          {
            class: "convo__del",
            type: "button",
            title: "Delete conversation",
            "aria-label": "Delete conversation",
            onClick: (e) => {
              e.stopPropagation();
              removeConversation(c.id);
            },
          },
          "×",
        ),
      ]),
    );
  }
}

function selectConversation(id) {
  const conv = getConversation(id);
  if (!conv) return;
  setConversation(id);
  setCustomerId(typeof conv.customerId === "number" ? conv.customerId : null);
  if (conv.runtime && (state.capabilities.runtimes || []).includes(conv.runtime)) selectRuntime(conv.runtime);
  reflectSession();
  loadConversation(conv);
  setView("chat");
  renderConversationList();
}

function newChat() {
  resetConversation();
  resetChat();
  reflectSession();
  setView("chat");
  renderConversationList();
}

function removeConversation(id) {
  const wasActive = id === state.conversationId;
  deleteConversation(id); // emits HISTORY_EVENT → list re-renders
  if (wasActive) newChat();
}

/* ------------------------------------------------------------------- session */

function reflectSession() {
  byId("customer-id").value = typeof state.customerId === "number" ? state.customerId : "";
}

function activateOpTab(tab) {
  currentOpTab = tab;
  document.querySelectorAll("[data-optab]").forEach((b) => b.classList.toggle("is-active", b.dataset.optab === tab));
  loadOperatorTab(tab);
}

async function loadStatus() {
  try {
    const caps = await getCapabilities();
    setCapabilities(caps);
    const modelDot = byId("status-model").querySelector(".dot");
    const modelLabel = byId("status-model").querySelector(".status__model");
    if (caps.active_model) {
      modelLabel.textContent = caps.active_model;
      modelDot.dataset.state = "ok";
    } else {
      modelLabel.textContent = "no LLM key";
      modelDot.dataset.state = "bad";
    }
  } catch {
    /* leave defaults */
  }
  buildRuntimeSwitcher();
  setTraceRuntime(state.runtime);

  try {
    const ready = await getReady();
    byId("status-db").querySelector(".dot").dataset.state = ready.database ? "ok" : "bad";
  } catch {
    byId("status-db").querySelector(".dot").dataset.state = "bad";
  }
}

function wire() {
  document.querySelectorAll("[data-nav]").forEach((b) => b.addEventListener("click", () => setView(b.dataset.nav)));
  document.querySelectorAll("[data-optab]").forEach((b) => b.addEventListener("click", () => activateOpTab(b.dataset.optab)));
  byId("operator-refresh").addEventListener("click", () => loadOperatorTab(currentOpTab));
  byId("new-chat").addEventListener("click", newChat);

  byId("customer-id").addEventListener("change", (e) => {
    const raw = e.target.value.trim();
    setCustomerId(raw === "" ? null : Math.max(1, parseInt(raw, 10) || 1));
    reflectSession();
  });

  document.addEventListener(HISTORY_EVENT, renderConversationList);
}

function main() {
  initChat();
  reflectSession();
  wire();
  renderConversationList();
  loadStatus();

  // Resume the most-recent active thread on reload, if it has any history.
  const current = getConversation(state.conversationId);
  if (current && current.messages?.length) loadConversation(current);
}

main();
