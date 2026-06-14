// Tiny DOM helpers. Everything user-facing is set via text nodes / textContent so
// untrusted content (LLM answers, KB snippets) can never inject markup. The `html`
// prop is reserved for trusted internal SVG icons only.

/**
 * Create an element.
 * @param {string} tag
 * @param {Object} [props]  class | text | html | dataset | aria* | on<Event> | attrs
 * @param {Array|Node|string} [children]
 */
export function el(tag, props = {}, children = []) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(props)) {
    if (value == null || value === false) continue;
    if (key === "class") node.className = value;
    else if (key === "text") node.textContent = value;
    else if (key === "html") node.innerHTML = value; // trusted icons only
    else if (key === "dataset") Object.assign(node.dataset, value);
    else if (key.startsWith("on") && typeof value === "function") {
      node.addEventListener(key.slice(2).toLowerCase(), value);
    } else node.setAttribute(key, value);
  }
  for (const child of Array.isArray(children) ? children : [children]) {
    if (child == null || child === false) continue;
    node.append(child.nodeType ? child : document.createTextNode(String(child)));
  }
  return node;
}

export function clear(node) {
  while (node.firstChild) node.removeChild(node.firstChild);
}

export function byId(id) {
  return document.getElementById(id);
}

/** A small inline icon (stroke style, inherits currentColor). */
export function icon(path, size = 16) {
  return `<svg viewBox="0 0 24 24" width="${size}" height="${size}" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round">${path}</svg>`;
}

export const ICONS = {
  check: "<path d='M20 6 9 17l-5-5'/>",
  alert: "<path d='M12 9v4M12 17h.01'/><path d='M10.3 3.9 1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0z'/>",
  shield: "<path d='M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z'/>",
  route: "<circle cx='6' cy='19' r='2'/><circle cx='18' cy='5' r='2'/><path d='M6 17V8a4 4 0 0 1 4-4h6'/>",
  spark: "<path d='M12 3l1.8 4.2L18 9l-4.2 1.8L12 15l-1.8-4.2L6 9l4.2-1.8z'/>",
  cog: "<circle cx='12' cy='12' r='3'/><path d='M12 2v3M12 19v3M4.9 4.9l2.1 2.1M17 17l2.1 2.1M2 12h3M19 12h3M4.9 19.1 7 17M17 7l2.1-2.1'/>",
};
