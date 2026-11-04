/**
 * Boot: mount the commander-facing Confirmation Gate globally across routes.
 *
 * Extracted from the last inline <script> blocks in index.html so the Tauri
 * CSP can enforce script-src 'self' (ADR 0003 defense-in-depth follow-on).
 * Behavior unchanged: the gate mounts once the DOM is ready.
 */
document.addEventListener('DOMContentLoaded', function () {
  if (typeof globalThis.ConfirmationGateComponent !== 'function') {
    console.error('[confirmation-gate] Component unavailable; protected actions remain disabled.');
    return;
  }
  window.OmniConfirmationGate = new ConfirmationGateComponent();
  window.OmniConfirmationGate.mount('#confirmation-gate-root');
});
