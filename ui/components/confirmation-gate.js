/**
 * Phase 3 Week 13 — Confirmation Gate UI Component
 *
 * Generic component for advisory confirmations (Law 1).
 * Phase 3 has no Tier 3 features, so no actual advisories render yet.
 * Future expansions (tactical threat, module targeting) populate this framework.
 */

class ConfirmationGateComponent {
  constructor() {
    this.confirmations = new Map();
    this.containerEl = null;
    this.pollInterval = null;
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
      this.containerEl.innerHTML = "";
    }
  }

  /**
   * Start polling /week13/confirmations/pending every 2 seconds.
   */
  startPolling() {
    this.pollInterval = setInterval(() => {
      this.fetchPending();
    }, 2000);
    this.fetchPending(); // Fetch immediately
  }

  /**
   * Stop polling.
   */
  stopPolling() {
    if (this.pollInterval) {
      clearInterval(this.pollInterval);
      this.pollInterval = null;
    }
  }

  /**
   * Fetch pending confirmations from the API.
   */
  async fetchPending() {
    const url = this.apiUrl('/week13/confirmations/pending');
    if (!url) return;
    try {
      const res = await fetch(url);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();

      const confirmations = data.confirmations || [];

      // Update internal map
      this.confirmations.clear();
      for (const conf of confirmations) {
        this.confirmations.set(conf.id, conf);
      }

      // Re-render
      this.render();
    } catch (err) {
      console.error("Failed to fetch pending confirmations:", err);
    }
  }

  /**
   * Render all pending confirmations into the container.
   */
  render() {
    if (!this.containerEl) return;

    this.containerEl.innerHTML = "";

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
    whyEl.setAttribute("aria-label", "Why is this suggested?");
    whyEl.textContent = "Why?";
    whyEl.addEventListener("click", () => {
      this.showWhy(id, conf);
    });

    const whyPlaceholderEl = document.createElement("p");
    whyPlaceholderEl.className = "confirmation-why-placeholder";
    whyPlaceholderEl.id = `confirmation-why-${id}`;
    whyPlaceholderEl.style.display = "none";

    const emEl = document.createElement("em");
    emEl.textContent = "Tier 3 explainability is reserved for a future Commander-approved expansion.";

    const smallEl = document.createElement("small");
    smallEl.textContent = conf.why_text || "See docs/ai/phase4_advisories.md";

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
    confirmBtn.textContent = "✓ Confirm";
    confirmBtn.setAttribute("aria-label", "Confirm this suggestion");
    confirmBtn.addEventListener("click", () => {
      this.respond(id, "confirm");
    });

    const declineBtn = document.createElement("button");
    declineBtn.type = "button";
    declineBtn.className = "confirmation-btn decline";
    declineBtn.textContent = "✗ Decline";
    declineBtn.setAttribute("aria-label", "Decline this suggestion");
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
}

// Export for use in other modules
if (typeof module !== "undefined" && module.exports) {
  module.exports = ConfirmationGateComponent;
}

// Test hook for Vitest; keeps this classic script browser-compatible.
if (typeof globalThis.__confirmationGateExports === "undefined") {
  globalThis.__confirmationGateExports = { ConfirmationGateComponent };
}
