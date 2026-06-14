// Chat: send flow, message bubbles, and the pipeline trace panel.

import { el, clear, byId, icon, ICONS } from "./dom.js";
import { respond, respondStream, canStream } from "./api.js";
import { state } from "./state.js";
import { upsertMessage } from "./history.js";

const SUGGESTIONS = [
  { title: "Browse the catalog", text: "Any dinosaur films available?" },
  { title: "My subscription", text: "What's my subscription status?" },
  { title: "Account help", text: "How do I update my payment method?" },
  { title: "Talk to a human", text: "I want to cancel my account." },
];

const ACTION_KIND = { answer: "ok", clarify: "info", escalate: "warn", handoff: "warn", block: "danger" };
const GUARD_KIND = { pass: "ok", modified: "warn", blocked: "danger" };
const RUNTIME_NOTE =
  "This runtime is LLM-driven and doesn't expose confidence, citations, or guardrail details.";

let dom = {};
let inFlight = false;

export function initChat() {
  dom = {
    transcript: byId("transcript"),
    form: byId("composer-form"),
    input: byId("composer-input"),
    send: byId("composer-send"),
    traceBody: byId("trace-body"),
    traceRuntime: byId("trace-runtime"),
  };

  dom.form.addEventListener("submit", (e) => {
    e.preventDefault();
    submitCurrent();
  });

  dom.input.addEventListener("input", autogrow);
  dom.input.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      submitCurrent();
    }
  });

  resetChat();
}

/** Clear the transcript back to the welcome screen and empty the trace panel. */
export function resetChat() {
  renderWelcome();
  renderEmptyTrace();
  setTraceRuntime(state.runtime);
}

export function setTraceRuntime(runtime) {
  if (dom.traceRuntime) dom.traceRuntime.textContent = runtime;
}

function autogrow() {
  dom.input.style.height = "auto";
  dom.input.style.height = Math.min(dom.input.scrollHeight, 180) + "px";
}

function submitCurrent() {
  const text = dom.input.value;
  dom.input.value = "";
  autogrow();
  sendMessage(text);
}

function setEnabled(on) {
  dom.send.disabled = !on;
  dom.input.disabled = !on;
}

function scrollToBottom() {
  dom.transcript.scrollTop = dom.transcript.scrollHeight;
}

async function sendMessage(rawText) {
  const text = (rawText || "").trim();
  if (!text || inFlight) return;
  const runtime = state.runtime;

  removeWelcome();
  appendUser(text);
  const thinking = appendThinking();
  setEnabled(false);
  inFlight = true;

  try {
    const body = {
      customer_id: typeof state.customerId === "number" ? state.customerId : null,
      conversation_id: state.conversationId,
      message: text,
    };
    if (canStream(runtime)) {
      thinking.remove();
      await streamRuntime(runtime, body); // real chunk streaming + chunk-level output guardrail
    } else {
      const res = await respond(runtime, body);
      thinking.remove();
      appendBot(res, runtime);
      renderTrace(res, runtime);
    }
  } catch (err) {
    thinking.remove();
    appendError(err.message || String(err));
  } finally {
    inFlight = false;
    setEnabled(true);
    dom.input.focus();
  }
}

/* ------------------------------------------------------------------ welcome */

function renderWelcome() {
  clear(dom.transcript);
  const grid = el("div", { class: "suggestions" });
  for (const s of SUGGESTIONS) {
    grid.append(
      el("button", { class: "suggestion", type: "button", onClick: () => sendMessage(s.text) }, [
        el("strong", { text: s.title }),
        el("span", { text: s.text }),
      ]),
    );
  }
  dom.transcript.append(
    el("div", { class: "welcome" }, [
      el("div", { class: "welcome__orb", html: icon(ICONS.spark, 30) }),
      el("h1", { text: "How can I help today?" }),
      el("p", {
        text: "Ask about the film catalog, your subscription or rentals, or general account help. Every reply shows the agent pipeline that produced it.",
      }),
      grid,
    ]),
  );
}

function removeWelcome() {
  const w = dom.transcript.querySelector(".welcome");
  if (w) w.remove();
}

/* ----------------------------------------------------------------- messages */

function initialsOf(name) {
  if (!name) return "AI";
  const caps = name.match(/[A-Z]/g);
  if (caps && caps.length >= 2) return (caps[0] + caps[1]).toUpperCase();
  return name.slice(0, 2).toUpperCase();
}

function sessionMeta() {
  return { customerId: state.customerId ?? null, runtime: state.runtime };
}

// `persist` is false when replaying a saved conversation so we don't double-store.
function appendUser(text, persist = true) {
  const msg = el("div", { class: "msg msg--user" }, [
    el("div", { class: "msg__avatar", text: "You" }),
    el("div", { class: "msg__col" }, [el("div", { class: "bubble", text })]),
  ]);
  dom.transcript.append(msg);
  scrollToBottom();
  if (persist) upsertMessage(state.conversationId, { role: "user", text }, sessionMeta());
}

// The agent + intent/action badges under a bot bubble. Shared by the instant and streamed paths.
function botMetaNode(res, runtime) {
  const agent = res.selected_agent || (runtime === "core" ? "Agent" : runtime.toUpperCase());
  const meta = el("div", { class: "msg__meta" }, [el("span", { class: "msg__agent", text: agent })]);
  if (runtime === "core") {
    if (res.intent) meta.append(badge(res.intent, "accent"));
    if (res.next_action) meta.append(badge(res.next_action, ACTION_KIND[res.next_action] || "muted"));
  } else {
    meta.append(badge(runtime, "muted"));
  }
  return meta;
}

function appendBot(res, runtime, persist = true) {
  const answer = res.answer ?? res.reply ?? "(no answer returned)";
  const agent = res.selected_agent || (runtime === "core" ? "Agent" : runtime.toUpperCase());
  const msg = el("div", { class: "msg msg--bot" }, [
    el("div", { class: "msg__avatar", text: initialsOf(agent) }),
    el("div", { class: "msg__col" }, [el("div", { class: "bubble", text: answer }), botMetaNode(res, runtime)]),
  ]);
  dom.transcript.append(msg);
  scrollToBottom();
  if (persist) {
    upsertMessage(
      state.conversationId,
      { role: "bot", text: answer, runtime, response: res },
      { customerId: state.customerId ?? null, runtime },
    );
  }
}

// Stream a runtime's answer chunk-by-chunk. The server validates each chunk and sends a
// `blocked` event (with a safe replacement) if the output guardrail trips mid-stream; `done`
// carries the authoritative response for the trace panel + persistence. Works for any
// streamable runtime (core uses res.answer, adk uses res.reply).
async function streamRuntime(runtime, body) {
  const avatar = el("div", { class: "msg__avatar", html: icon(ICONS.spark, 16) });
  const bubble = el("div", { class: "bubble" });
  const col = el("div", { class: "msg__col" }, [bubble]);
  const node = el("div", { class: "msg msg--bot" }, [avatar, col]);
  dom.transcript.append(node);
  scrollToBottom();

  await respondStream(runtime, body, (ev) => {
    if (ev.type === "chunk") {
      bubble.textContent += ev.text;
      scrollToBottom();
    } else if (ev.type === "blocked") {
      bubble.textContent = ev.text;
      bubble.classList.add("bubble--error");
      scrollToBottom();
    } else if (ev.type === "error") {
      throw new Error(ev.detail || "stream error");
    } else if (ev.type === "done") {
      const res = ev.response;
      const answer = res.answer ?? res.reply ?? bubble.textContent; // authoritative
      bubble.textContent = answer;
      avatar.textContent = initialsOf(res.selected_agent || (runtime === "core" ? "Agent" : runtime.toUpperCase()));
      col.append(botMetaNode(res, runtime));
      upsertMessage(
        state.conversationId,
        { role: "bot", text: answer, runtime, response: res },
        { customerId: state.customerId ?? null, runtime },
      );
      renderTrace(res, runtime);
    }
  });
}

/** Replay a saved conversation into the transcript and re-render its last trace. */
export function loadConversation(conv) {
  clear(dom.transcript);
  let lastBot = null;
  for (const m of conv.messages || []) {
    if (m.role === "user") appendUser(m.text, false);
    else if (m.role === "bot" && m.response) {
      appendBot(m.response, m.runtime || "core", false);
      lastBot = m;
    } else if (m.role === "bot") {
      // Degraded entry without a stored response — show the text only.
      appendUser(m.text, false);
    }
  }
  if (lastBot) renderTrace(lastBot.response, lastBot.runtime || "core");
  else renderEmptyTrace();
  setTraceRuntime(state.runtime);
  scrollToBottom();
}

function appendThinking() {
  const node = el("div", { class: "msg msg--bot" }, [
    el("div", { class: "msg__avatar", html: icon(ICONS.spark, 16) }),
    el("div", { class: "msg__col" }, [
      el("div", { class: "bubble thinking" }, [el("i"), el("i"), el("i")]),
    ]),
  ]);
  dom.transcript.append(node);
  scrollToBottom();
  return node;
}

function appendError(message) {
  dom.transcript.append(
    el("div", { class: "msg msg--bot" }, [
      el("div", { class: "msg__avatar", html: icon(ICONS.alert, 16) }),
      el("div", { class: "msg__col" }, [
        el("div", { class: "bubble bubble--error", text: `Request failed: ${message}` }),
      ]),
    ]),
  );
  scrollToBottom();
}

/* -------------------------------------------------------------------- badges */

function badge(text, kind = "muted") {
  return el("span", { class: "badge", dataset: { kind }, text });
}

/* --------------------------------------------------------------- trace panel */

export function renderEmptyTrace() {
  clear(dom.traceBody);
  dom.traceBody.append(
    el("div", { class: "trace-empty" }, [
      el("div", { html: icon(ICONS.route, 30) }),
      "Send a message to see the agent pipeline that produced the reply.",
    ]),
  );
}

function renderTrace(res, runtime) {
  clear(dom.traceBody);
  setTraceRuntime(runtime);
  if (runtime === "core") renderCoreTrace(res);
  else renderRuntimeTrace(res, runtime);
}

function stage(name, st, detail) {
  return el("div", { class: "stage", dataset: { state: st } }, [
    el("div", { class: "stage__rail" }, [
      el("div", { class: "stage__node", html: icon(st === "bad" ? ICONS.alert : ICONS.check, 10) }),
      el("div", { class: "stage__line" }),
    ]),
    el("div", { class: "stage__body" }, [
      el("div", { class: "stage__name", text: name }),
      el("div", { class: "stage__detail", text: detail }),
    ]),
  ]);
}

function renderCoreTrace(res) {
  const blocked = res.next_action === "block";
  const conf = typeof res.confidence === "number" ? res.confidence : 0;
  const guard = res.guardrail_result || { status: "pass", checks: [], reasons: [] };

  // Pipeline stepper.
  const pipe = el("div", { class: "pipeline" });
  pipe.append(stage("Input guardrail", blocked ? "bad" : "ok", blocked ? "blocked before triage" : "passed"));
  pipe.append(
    blocked
      ? stage("Triage", "skip", "skipped")
      : stage("Triage", "ok", `${res.intent} · conf ${conf.toFixed(2)}`),
  );
  pipe.append(blocked ? stage("Router", "skip", "skipped") : stage("Router", "ok", res.selected_agent));
  pipe.append(
    blocked
      ? stage("Specialist", "skip", "skipped")
      : stage("Specialist", "ok", res.tools_used?.length ? res.tools_used.join(", ") : "no tools"),
  );
  pipe.append(stage("Output guardrail", GUARD_KIND[guard.status] || "ok", guard.status));
  dom.traceBody.append(pipe);

  // Routing card.
  dom.traceBody.append(
    tcard("Routing", [
      row("Intent", badge(res.intent, "accent")),
      row("Agent", el("span", { class: "tcard__value", text: res.selected_agent })),
      row("Next action", badge(res.next_action, ACTION_KIND[res.next_action] || "muted")),
    ]),
  );

  // Confidence card.
  if (!blocked) dom.traceBody.append(confidenceCard(conf));

  // Tools card.
  dom.traceBody.append(
    tcard("Tools used", [
      res.tools_used?.length
        ? el("div", { class: "chips" }, res.tools_used.map((t) => el("span", { class: "chip", text: t })))
        : el("div", { class: "stage__detail", text: "No tools were called." }),
    ]),
  );

  // Citations card (only when present).
  if (res.citations?.length) {
    const list = res.citations.map((c) =>
      el("div", { class: "citation" }, [
        el("div", { class: "citation__src", text: c.source }),
        c.snippet ? el("div", { class: "citation__snip", text: c.snippet }) : null,
      ]),
    );
    dom.traceBody.append(tcard("Citations", list));
  }

  // Guardrail card.
  const guardChildren = [row("Status", badge(guard.status, GUARD_KIND[guard.status] || "muted"))];
  if (guard.checks?.length) {
    guardChildren.push(
      el("div", { class: "chips", style: "margin-top:10px" }, guard.checks.map((c) => el("span", { class: "chip", text: c }))),
    );
  }
  if (guard.reasons?.length) {
    guardChildren.push(el("ul", { class: "reasons" }, guard.reasons.map((r) => el("li", { text: r }))));
  }
  dom.traceBody.append(tcard("Output guardrail", guardChildren));
}

function renderRuntimeTrace(res, runtime) {
  const agent = res.selected_agent || "—";
  const pipe = el("div", { class: "pipeline" });
  pipe.append(stage(`Runtime · ${runtime.toUpperCase()}`, "ok", "reply produced"));
  pipe.append(
    stage("Specialist", "ok", agent),
  );
  pipe.append(
    res.tools_used?.length ? stage("Tools (MCP)", "ok", res.tools_used.join(", ")) : stage("Tools (MCP)", "skip", "no tools"),
  );
  dom.traceBody.append(pipe);

  dom.traceBody.append(
    tcard("Runtime", [
      row("Engine", badge(runtime.toUpperCase(), "accent")),
      row("Agent", el("span", { class: "tcard__value", text: agent })),
    ]),
  );

  dom.traceBody.append(
    tcard("Tools used", [
      res.tools_used?.length
        ? el("div", { class: "chips" }, res.tools_used.map((t) => el("span", { class: "chip", text: t })))
        : el("div", { class: "stage__detail", text: "No tools were called." }),
    ]),
  );

  dom.traceBody.append(el("div", { class: "tnote", text: RUNTIME_NOTE }));
}

/* -------------------------------------------------------------- trace pieces */

function tcard(label, children) {
  return el("div", { class: "tcard" }, [el("div", { class: "tcard__label", text: label }), ...[].concat(children)]);
}

function row(label, valueNode) {
  return el("div", { class: "tcard__row", style: "margin-bottom:8px" }, [
    el("span", { class: "stage__detail", text: label }),
    valueNode,
  ]);
}

function confidenceCard(conf) {
  const thr = state.confidenceThreshold;
  const good = conf >= thr;
  const card = tcard("Confidence", [
    el("div", { class: "tcard__row" }, [
      el("span", { class: "tcard__value", text: conf.toFixed(2) }),
      badge(good ? "above threshold" : "below threshold", good ? "ok" : "warn"),
    ]),
    el("div", { class: "confbar" }, [
      el("div", { class: "confbar__fill", dataset: { good: String(good) }, style: `width:${Math.round(conf * 100)}%` }),
      el("div", { class: "confmark", style: `left:${Math.round(thr * 100)}%` }),
    ]),
    el("div", { class: "conf-meta" }, [el("span", { text: "0.0" }), el("span", { text: `threshold ${thr.toFixed(2)}` }), el("span", { text: "1.0" })]),
  ]);
  return card;
}
