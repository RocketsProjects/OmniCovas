/**
 * Boot: wire log entries from the WS event bus after all scripts load.
 *
 * Extracted from the last inline <script> blocks in index.html so the Tauri
 * CSP can enforce script-src 'self' (ADR 0003 defense-in-depth follow-on).
 * Behavior unchanged.
 */
window.OmniEvents.addEventListener('event', function (ev) {
  if (window._addLogEntry) window._addLogEntry(ev.detail);
});
