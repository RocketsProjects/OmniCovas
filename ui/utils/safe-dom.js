/**
 * OmniCOVAS — Safe DOM helpers (Phase 3 hotfix).
 * Canonical XSS-safe rendering. See ADR 0003.
 */

export function escapeHtml(value) {
  if (value === null || value === undefined) return "";
  const str = typeof value === "string" ? value : String(value);
  const div = document.createElement("div");
  div.textContent = str;
  return div.innerHTML;
}

export function setSafeText(el, value) {
  if (!el) return;
  el.textContent = value === null || value === undefined ? "" : String(value);
}

export function appendTextChild(parent, tagName, text, className) {
  const child = document.createElement(tagName);
  if (className) child.className = className;
  child.textContent = text === null || text === undefined ? "" : String(text);
  parent.appendChild(child);
  return child;
}
