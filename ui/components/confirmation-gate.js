/**
 * Phase 3 Week 13 — Confirmation Gate UI Component
 *
 * Generic component for advisory confirmations (Law 1).
 * Phase 3 has no Tier 3 features, so no actual advisories render yet.
 * Future expansions (tactical threat, module targeting) populate this framework.
 */

const POLL_BASE_MS = 2000;
const POLL_MAX_BACKOFF_MS = 60000;

class ConfirmationGateComponent {
  constructor() {
    this.confirmations = new Map();
    this.containerEl = null;
    this.pollTimer = null;
    this.activeLocalDialog = null;
    this.statusEl = null;
    /* Poll lifecycle state. `connected` is tri-state (null = not yet known)
       so the first transition in either direction emits exactly one line.

       `pollGeneration` is the lifecycle token. Every start/stop bumps it, so
       a request issued by an earlier generation can never render, reschedule,
       or alter counters after an unmount — even if it settles late. */
    this.pollDelayMs = POLL_BASE_MS;
    this.pollGeneration = 0;
    this.inflightRequests = 0;
    this.pollWakeups = 0;
    this.pollAbort = null;
    this.connected = null;
    this._onBridgeConnected = null;
  }

  get apiBase() {
    if (window.Shell?.httpBase) return window.Shell.httpBase;
    if (window.OMNICOVAS_PORT) return `http://127.0.0.1:${window.OMNICOVAS_PORT}`;
    return null;
  }

  apiUrl(path) {
    const base = this.apiBase;
    return base ? `${base}${path}` : null;
  }

  /**
   * Mount the component into a DOM container.
   *
   * @param {HTMLElement|string} selector - Container to render into
   */
  mount(selector) {
    const el = typeof selector === "string" ? document.querySelector(selector) : selector;
    if (!el) {
      console.error("ConfirmationGate mount target not found:", selector);
      return;
    }

    this.containerEl = el;
    this.containerEl.className = "confirmation-gate-container";

    // Start polling for pending confirmations
    this.startPolling();
  }

  /**
   * Unmount and clean up.
   */
  unmount() {
    this.stopPolling();
    if (this.containerEl) {
      this.containerEl.replaceChildren();
    }
  }

  /**
   * Start polling /week13/confirmations/pending.
   *
   * Responsive while connected (2s); backs off exponentially to a 60s ceiling
   * while the local bridge is down so a disconnected session does not burn
   * wakeups or flood the console (Principle 10). A `bridge-connected` signal
   * resets the cadence immediately.
   */
  startPolling() {
    this.stopPolling();
    this.pollGeneration += 1;
    this._onBridgeConnected = () => this.onBridgeConnected();
    window.OmniEvents?.addEventListener('bridge-connected', this._onBridgeConnected);
    this.scheduleNextPoll(0);
  }

  /** Schedule exactly one pending-poll for the current generation. */
  scheduleNextPoll(delayMs) {
    const generation = this.pollGeneration;
    if (this.pollTimer !== null) {
      clearTimeout(this.pollTimer);
      this.pollTimer = null;
    }
    this.pollTimer = setTimeout(() => {
      this.pollTimer = null;
      this.pollWakeups += 1;
      if (generation !== this.pollGeneration) return; // stopped or restarted
      this.fetchPending().finally(() => {
        if (generation === this.pollGeneration && this._onBridgeConnected !== null) {
          this.scheduleNextPoll(this.pollDelayMs);
        }
      });
    }, delayMs);
  }

  /** Bridge came back: drop to the responsive cadence at once. */
  onBridgeConnected() {
    this.pollDelayMs = POLL_BASE_MS;
    // Requeue rather than firing directly, so a signal arriving mid-request
    // replaces the pending wakeup instead of stacking a second one.
    if (this.inflightRequests > 0) return;
    this.scheduleNextPoll(0);
  }

  /**
   * Stop polling and release every timer, listener, and unresolved request.
   */
  stopPolling() {
    this.pollGeneration += 1; // invalidate anything already in flight
    if (this.pollTimer !== null) {
      clearTimeout(this.pollTimer);
      this.pollTimer = null;
    }
    if (this.pollAbort) {
      try {
        this.pollAbort.abort();
      } catch {
        /* AbortController is unavailable in some test environments. */
      }
      this.pollAbort = null;
    }
    if (this._onBridgeConnected) {
      window.OmniEvents?.removeEventListener('bridge-connected', this._onBridgeConnected);
      this._onBridgeConnected = null;
    }
    this.pollDelayMs = POLL_BASE_MS;
    this.inflightRequests = 0;
  }

  /**
   * Fetch pending confirmations from the API.
   *
   * Emits at most one diagnostic per connection-state transition, so a long
   * disconnected session leaves one line rather than one line every 2s.
   */
  async fetchPending() {
    const generation = this.pollGeneration;
    const url = this.apiUrl('/week13/confirmations/pending');
    if (!url) {
      // No bridge yet. Back off instead of waking every 2s forever; a
      // `bridge-connected` signal short-circuits the wait when it arrives.
      this.pollDelayMs = Math.min(this.pollDelayMs * 2, POLL_MAX_BACKOFF_MS);
      return;
    }
    if (this.inflightRequests > 0) return; // never overlap requests

    this.inflightRequests += 1;
    let signal;
    try {
      this.pollAbort = new AbortController();
      signal = this.pollAbort.signal;
    } catch {
      signal = undefined;
    }

    try {
      const res = await fetch(url, signal ? { signal } : undefined);
      if (generation !== this.pollGeneration) return; // stale: abandon quietly
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      if (generation !== this.pollGeneration) return;

      const confirmations = data.confirmations || [];

      // Update internal map
      this.confirmations.clear();
      for (const conf of confirmations) {
        this.confirmations.set(conf.id, conf);
      }

      // Re-render
      this.render();
      this.markPollConnected();
    } catch (err) {
      if (generation !== this.pollGeneration) return; // stale failure: ignore
      this.markPollDisconnected(err);
    } finally {
      if (generation === this.pollGeneration) {
        this.inflightRequests = Math.max(0, this.inflightRequests - 1);
        this.pollAbort = null;
      }
    }
  }

  /** Record a healthy poll; log only on the disconnected → connected edge. */
  markPollConnected() {
    if (this.connected === false) {
      console.info('Confirmation Gate: local bridge reachable again; resuming normal polling.');
    }
    this.connected = true;
    this.pollDelayMs = POLL_BASE_MS;
  }

  /** Record a failed poll; log only on the connected → disconnected edge. */
  markPollDisconnected(err) {
    if (this.connected !== false) {
      console.error('Failed to fetch pending confirmations:', err);
    }
    this.connected = false;
    this.pollDelayMs = Math.min(this.pollDelayMs * 2, POLL_MAX_BACKOFF_MS);
  }

  /**
   * Render all pending confirmations into the container.
   */
  render() {
    if (!this.containerEl) return;

    this.containerEl.replaceChildren();

    if (this.confirmations.size === 0) {
      // No pending confirmations — optionally show placeholder
      return;
    }

    for (const [id, conf] of this.confirmations) {
      const card = this.createConfirmationCard(id, conf);
      this.containerEl.appendChild(card);
    }
  }

  /**
   * Create a single confirmation card.
   */
  createConfirmationCard(id, conf) {
    const card = document.createElement("div");
    card.className = "confirmation-card";
    card.id = `confirmation-${id}`;
    card.role = "region";
    card.setAttribute("aria-labelledby", `confirmation-suggestion-${id}`);

    const suggestionEl = document.createElement("div");
    suggestionEl.className = "confirmation-suggestion";
    suggestionEl.id = `confirmation-suggestion-${id}`;
    suggestionEl.textContent = conf.suggestion_text || "(no suggestion text)";

    const whyEl = document.createElement("button");
    whyEl.type = "button";
    whyEl.className = "confirmation-why-btn";
    whyEl.setAttribute("aria-label", "Why OmniCOVAS is suggesting this");
    whyEl.textContent = "Why this?";
    whyEl.addEventListener("click", () => {
      this.showWhy(id, conf);
    });

    const whyPlaceholderEl = document.createElement("p");
    whyPlaceholderEl.className = "confirmation-why-placeholder";
    whyPlaceholderEl.id = `confirmation-why-${id}`;
    whyPlaceholderEl.style.display = "none";

    const emEl = document.createElement("em");
    emEl.textContent = "Review the reason before deciding.";

    const smallEl = document.createElement("small");
    smallEl.textContent = conf.why_text || "No additional explanation is available.";

    whyPlaceholderEl.appendChild(emEl);
    whyPlaceholderEl.appendChild(document.createElement("br"));
    whyPlaceholderEl.appendChild(smallEl);

    const timeoutEl = document.createElement("p");
    timeoutEl.className = "confirmation-timeout";
    if (conf.timeout_at) {
      const timeout = new Date(conf.timeout_at);
      const now = new Date();
      const remaining = Math.max(0, Math.floor((timeout - now) / 1000));
      timeoutEl.textContent = `Timeout in ${remaining}s`;
    }

    const buttonsEl = document.createElement("div");
    buttonsEl.className = "confirmation-buttons";

    const confirmBtn = document.createElement("button");
    confirmBtn.type = "button";
    confirmBtn.className = "confirmation-btn confirm";
    confirmBtn.textContent = "Apply suggestion";
    confirmBtn.setAttribute("aria-label", "Apply this suggestion");
    confirmBtn.addEventListener("click", () => {
      this.respond(id, "confirm");
    });

    const declineBtn = document.createElement("button");
    declineBtn.type = "button";
    declineBtn.className = "confirmation-btn decline";
    declineBtn.textContent = "Cancel";
    declineBtn.setAttribute("aria-label", "Cancel this suggestion");
    declineBtn.addEventListener("click", () => {
      this.respond(id, "decline");
    });

    buttonsEl.appendChild(confirmBtn);
    buttonsEl.appendChild(declineBtn);

    card.appendChild(suggestionEl);
    card.appendChild(whyEl);
    card.appendChild(whyPlaceholderEl);
    card.appendChild(timeoutEl);
    card.appendChild(buttonsEl);

    return card;
  }

  /**
   * Show the "Why?" explanation.
   */
  showWhy(id, conf) {
    const placeholderEl = document.getElementById(`confirmation-why-${id}`);
    if (placeholderEl) {
      const isVisible = placeholderEl.style.display !== "none";
      placeholderEl.style.display = isVisible ? "none" : "block";
    }
  }

  /**
   * Send a response to the server.
   */
  async respond(id, response) {
    const url = this.apiUrl(`/week13/confirmations/${id}`);
    if (!url) return;
    try {
      const res = await fetch(url, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ response }),
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);

      // Remove from local map
      this.confirmations.delete(id);
      this.render();

      console.log(`Confirmation ${id} responded with: ${response}`);
    } catch (err) {
      console.error(`Failed to respond to confirmation ${id}:`, err);
    }
  }

  /**
   * Confirm a protected local UI action through the one shared Commander gate.
   *
   * This is intentionally separate from the Week 13 advisory queue.  It binds
   * a Commander's click to a local mutation request but does not claim or
   * execute a game action.
   */
  confirmLocalAction(options = {}) {
    if (this.activeLocalDialog) return Promise.resolve(false);

    const title = String(options.title || 'Confirm local action');
    const message = String(options.message || 'Review this action before continuing.');
    const confirmLabel = String(options.confirmLabel || 'Confirm');
    const cancelLabel = String(options.cancelLabel || 'Cancel');
    const secondMessage = options.secondMessage
      ? String(options.secondMessage)
      : null;
    const finalConfirmLabel = String(options.finalConfirmLabel || confirmLabel);
    const previousFocus = document.activeElement;

    return new Promise((resolve) => {
      const overlay = document.createElement('div');
      overlay.className = 'confirmation-local-overlay';

      const dialog = document.createElement('section');
      dialog.className = 'confirmation-local-dialog';
      if (options.danger) dialog.classList.add('confirmation-local-dialog--danger');
      dialog.setAttribute('role', 'dialog');
      dialog.setAttribute('aria-modal', 'true');
      dialog.setAttribute('aria-labelledby', 'confirmation-local-title');
      dialog.setAttribute('aria-describedby', 'confirmation-local-message');

      const heading = document.createElement('h2');
      heading.id = 'confirmation-local-title';
      heading.className = 'confirmation-local-title';
      heading.textContent = title;

      const body = document.createElement('p');
      body.id = 'confirmation-local-message';
      body.className = 'confirmation-local-message';
      body.textContent = message;

      const buttons = document.createElement('div');
      buttons.className = 'confirmation-buttons';

      const confirmButton = document.createElement('button');
      confirmButton.type = 'button';
      confirmButton.className = 'confirmation-btn confirm';
      if (options.danger) confirmButton.classList.add('danger');
      confirmButton.dataset.confirmLocal = 'true';
      confirmButton.textContent = confirmLabel;

      const cancelButton = document.createElement('button');
      cancelButton.type = 'button';
      cancelButton.className = 'confirmation-btn decline';
      cancelButton.dataset.cancelLocal = 'true';
      cancelButton.textContent = cancelLabel;

      let stage = 1;
      const finish = (accepted) => {
        document.removeEventListener('keydown', onKeydown);
        overlay.remove();
        this.activeLocalDialog = null;
        this.restoreFocusAfterDialog(previousFocus);
        resolve(accepted);
      };
      const onKeydown = (event) => {
        if (event.key === 'Escape') {
          event.preventDefault();
          finish(false);
        }
      };

      confirmButton.addEventListener('click', () => {
        if (secondMessage && stage === 1) {
          stage = 2;
          body.textContent = secondMessage;
          confirmButton.textContent = finalConfirmLabel;
          confirmButton.focus();
          return;
        }
        finish(true);
      });
      cancelButton.addEventListener('click', () => finish(false));

      buttons.append(confirmButton, cancelButton);
      dialog.append(heading, body, buttons);
      overlay.appendChild(dialog);
      document.body.appendChild(overlay);
      document.addEventListener('keydown', onKeydown);
      this.activeLocalDialog = overlay;
      /* Error prevention: a dangerous dialog opens on the safe choice, so a
         stray Enter/Space cancels rather than destroys. Non-dangerous dialogs
         keep opening on Confirm — that stays the intended fast path. */
      if (options.danger) {
        cancelButton.focus();
      } else {
        confirmButton.focus();
      }
    });
  }

  /**
   * Return focus after a dialog closes.
   *
   * Prefers the invoking control. When it is gone (or was never focusable —
   * e.g. a programmatic caller), falls back deterministically to the route
   * landmark instead of letting focus drop silently onto <body>, which would
   * strand keyboard and screen-reader users at the top of the document.
   */
  restoreFocusAfterDialog(previousFocus) {
    if (previousFocus instanceof HTMLElement
      && previousFocus.isConnected
      && previousFocus !== document.body) {
      previousFocus.focus();
      return;
    }
    const fallback = document.querySelector('main')
      || document.querySelector('[role="main"]');
    if (!fallback) return;
    if (!fallback.hasAttribute('tabindex')) fallback.setAttribute('tabindex', '-1');
    fallback.focus();
  }

  /**
   * Bounded delay for flows waiting on a commander decision.
   *
   * Timers for the confirmation surface live in this component, so route
   * controllers can wait on a decision without introducing their own timer
   * calls (the Activity Log view is scanned for timer/DOM-sink identifiers).
   */
  delay(ms) {
    return new Promise((resolve) => setTimeout(resolve, Math.max(0, Number(ms) || 0)));
  }

  /** Show a non-blocking result through the same shared UI surface. */
  announce(message, options = {}) {
    this.statusEl?.remove();
    const status = document.createElement('div');
    status.className = 'confirmation-status';
    status.classList.add(`confirmation-status--${String(options.kind || 'info')}`);
    // A warning here means the action succeeded but its audit record did not,
    // which the commander must not miss — announce it as assertively as an error.
    const assertive = options.kind === 'error' || options.kind === 'warning';
    status.setAttribute('role', assertive ? 'alert' : 'status');
    status.textContent = String(message || '');
    document.body.appendChild(status);
    this.statusEl = status;
    window.setTimeout(() => {
      if (this.statusEl === status) this.statusEl = null;
      status.remove();
    }, 5000);
  }
}

// Export for use in other modules
if (typeof module !== "undefined" && module.exports) {
  module.exports = ConfirmationGateComponent;
}

// Test hook for Vitest; keeps this classic script browser-compatible.
if (typeof globalThis.__confirmationGateExports === "undefined") {
  globalThis.__confirmationGateExports = { ConfirmationGateComponent };
}
/* Production-safe constructor export. A top-level class declaration is not a
   reliable Window property across classic/module loading boundaries. */
globalThis.ConfirmationGateComponent = ConfirmationGateComponent;
