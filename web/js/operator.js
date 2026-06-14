// Operator views — read-only browsers over the existing introspection endpoints.

import { el, clear, byId } from "./dom.js";
import { getRoutes, getAgents, getKb, getHandoffs } from "./api.js";

const LOADERS = {
  routes: { fetch: getRoutes, render: renderRoutes },
  agents: { fetch: getAgents, render: renderAgents },
  kb: { fetch: getKb, render: renderKb },
  handoffs: { fetch: getHandoffs, render: renderHandoffs },
};

export async function loadOperatorTab(tab) {
  const body = byId("operator-body");
  const loader = LOADERS[tab] || LOADERS.routes;
  clear(body);
  body.append(el("div", { class: "spinner" }));
  try {
    const data = await loader.fetch();
    clear(body);
    loader.render(body, data);
  } catch (err) {
    clear(body);
    body.append(el("div", { class: "op-error", text: `Couldn't load ${tab}: ${err.message || err}` }));
  }
}

/* --------------------------------------------------------------------- views */

function renderRoutes(body, data) {
  body.append(
    el("div", { class: "op-callout" }, [
      el("div", {}, [el("span", { class: "k", text: "Confidence threshold" }), el("span", { class: "v", text: String(data.confidence_threshold) })]),
      el("div", {}, [el("span", { class: "k", text: "Fallback agent" }), el("span", { class: "v", text: data.fallback_agent })]),
      el("div", {}, [el("span", { class: "k", text: "Routes" }), el("span", { class: "v", text: String(Object.keys(data.routes || {}).length) })]),
    ]),
  );

  const rows = Object.entries(data.routes || {}).map(([intent, agent]) =>
    el("tr", {}, [el("td", {}, [el("code", { text: intent })]), el("td", { text: agent })]),
  );
  body.append(table(["Intent", "Specialist agent"], rows));
}

function renderAgents(body, agents) {
  if (!agents?.length) return body.append(emptyState("No agents registered."));
  const cards = agents.map((a) =>
    el("div", { class: "card" }, [
      el("h3", { class: "card__title", text: a.name }),
      el("div", { class: "card__body", text: a.responsibility || "" }),
      a.tools?.length
        ? el("div", { class: "chips" }, a.tools.map((t) => el("span", { class: "chip", text: t })))
        : el("div", { class: "card__sub", text: "no tools" }),
    ]),
  );
  body.append(el("div", { class: "cards" }, cards));
}

function renderKb(body, articles) {
  if (!articles?.length) return body.append(emptyState("Knowledge base is empty."));
  const cards = articles.map((a) =>
    el("div", { class: "card" }, [
      el("div", { class: "card__sub", text: a.id }),
      el("h3", { class: "card__title", text: a.title }),
      el("div", { class: "card__body", text: a.snippet || "" }),
    ]),
  );
  body.append(el("div", { class: "cards" }, cards));
}

function renderHandoffs(body, tickets) {
  if (!tickets?.length) {
    return body.append(
      emptyState("No handoff tickets yet. Ask to cancel/refund/close an account in chat to create one."),
    );
  }
  const rows = tickets.map((t) =>
    el("tr", {}, [
      el("td", {}, [el("code", { text: t.ticket_id })]),
      el("td", {}, [el("span", { class: "badge", dataset: { kind: "info" }, text: t.status })]),
      el("td", {}, [el("span", { class: "badge", dataset: { kind: "info" }, text: t.source || "core" })]),
      el("td", { text: formatDate(t.created_at) }),
      el("td", { text: t.summary }),
      el("td", { text: t.reason }),
    ]),
  );
  body.append(table(["Ticket", "Status", "Created by", "Created", "Summary", "Reason"], rows));
}

/* ------------------------------------------------------------------- helpers */

function table(headers, rows) {
  return el("table", { class: "table" }, [
    el("thead", {}, [el("tr", {}, headers.map((h) => el("th", { text: h })))]),
    el("tbody", {}, rows),
  ]);
}

function emptyState(text) {
  return el("div", { class: "op-empty", text });
}

function formatDate(iso) {
  if (!iso) return "—";
  try {
    return new Date(iso).toLocaleString();
  } catch {
    return iso;
  }
}
