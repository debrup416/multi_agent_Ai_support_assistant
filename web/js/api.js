// Thin fetch wrappers around the backend. Same-origin, so no CORS, no base URL.

const RESPOND_ENDPOINTS = {
  core: "/agent/respond",
  adk: "/adk/respond",
  sk: "/sk/respond",
};

async function getJSON(path) {
  const res = await fetch(path, { headers: { accept: "application/json" } });
  if (!res.ok) throw new Error(`GET ${path} → ${res.status} ${res.statusText}`);
  return res.json();
}

/** Send a customer message through the chosen runtime. Returns the parsed response. */
export async function respond(runtime, body) {
  const path = RESPOND_ENDPOINTS[runtime] || RESPOND_ENDPOINTS.core;
  const res = await fetch(path, {
    method: "POST",
    headers: { "content-type": "application/json", accept: "application/json" },
    body: JSON.stringify(body),
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    const detail =
      data && data.detail
        ? typeof data.detail === "string"
          ? data.detail
          : JSON.stringify(data.detail)
        : res.statusText;
    throw new Error(`${res.status} — ${detail}`);
  }
  return data;
}

const STREAM_ENDPOINTS = {
  core: "/agent/respond/stream",
  adk: "/adk/respond/stream",
};

/** True if the runtime streams (NDJSON). Others fall back to the one-shot respond(). */
export const canStream = (runtime) => runtime in STREAM_ENDPOINTS;

/** Stream a runtime's reply. Invokes onEvent(ev) for each NDJSON event (chunk/blocked/done/error). */
export async function respondStream(runtime, body, onEvent) {
  const res = await fetch(STREAM_ENDPOINTS[runtime] || STREAM_ENDPOINTS.core, {
    method: "POST",
    headers: { "content-type": "application/json", accept: "application/x-ndjson" },
    body: JSON.stringify(body),
  });
  if (!res.ok || !res.body) {
    const data = await res.json().catch(() => ({}));
    throw new Error(`${res.status} — ${data.detail || res.statusText}`);
  }
  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buf = "";
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    buf += decoder.decode(value, { stream: true });
    let nl;
    while ((nl = buf.indexOf("\n")) >= 0) {
      const line = buf.slice(0, nl).trim();
      buf = buf.slice(nl + 1);
      if (line) onEvent(JSON.parse(line));
    }
  }
  const tail = buf.trim();
  if (tail) onEvent(JSON.parse(tail));
}

export const getCapabilities = () => getJSON("/capabilities");
export const getReady = () => getJSON("/ready");
export const getRoutes = () => getJSON("/routes");
export const getAgents = () => getJSON("/agents");
export const getKb = () => getJSON("/kb");
export const getHandoffs = () => getJSON("/handoffs");
