/**
 * Phase 3 Week 13 — Privacy Page Controller
 *
 * Manages privacy toggles, data export, and data deletion.
 * All toggles default OFF (Law 8: Privacy-by-Default).
 */

class PrivacyController {
  constructor() {
    this.deleteConfirmStage = 0;
    this._primitivesPromise = import('../components/command-primitives.js').catch(e => {
      console.error('[Privacy] Failed to load command primitives:', e);
      return null;
    });
    this.init();
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

  async init() {
    this.bindButtons();
    if (!this.apiBase) {
      this._showWaiting();
      window.OmniEvents?.addEventListener('bridge-connected', () => this._loadAndRender(), { once: true });
      return;
    }
    await this._loadAndRender();
  }

  async _loadAndRender() {
    this.renderRouteHero();
    await this.loadToggles();
  }

  async renderRouteHero() {
    const Primitives = await this._primitivesPromise;
    if (!Primitives) return;

    const container = document.getElementById('view-privacy');
    if (!container) return;

    container.querySelector('.route-hero')?.remove();

    const hero = Primitives.createRouteHero({
      title: 'Privacy',
      kicker: 'Data Flow',
      statusText: this.apiBase ? 'Data flow locked' : 'Bridge not ready',
      statusVariant: this.apiBase ? 'locked' : 'not-loaded',
      primaryValues: [
        { label: 'Posture', value: 'Local-only' },
        { label: 'Outbound', value: 'None' }
      ]
    });

    container.prepend(hero);
  }

  _showWaiting() {
    const list = document.getElementById('privacy-toggles-list');
    if (!list) return;
    const p = document.createElement('p');
    p.className = 'field-value unknown';
    p.textContent = 'Waiting for OmniCOVAS bridge…';
    list.replaceChildren(p);
  }

  async loadToggles() {
    if (!this.apiBase) return;
    const Primitives = await this._primitivesPromise;
    try {
      const res = await fetch(`${this.apiBase}/week13/privacy/toggles`);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();

      const container = document.getElementById("privacy-toggles-list");
      if (!container) return;

      container.replaceChildren();
      for (const [key, info] of Object.entries(data)) {
        const card = this.createToggleCard(key, info, Primitives);
        container.appendChild(card);
      }
    } catch (err) {
      console.error("Failed to load privacy toggles:", err);
    }
  }

  createToggleCard(key, info, Primitives) {
    /* The dedicated privacy layout keeps title/description left and the
       toggle/status control right. Command cards put status chrome between
       text rows, which produced the smoke-test floating-dot failure. */
    Primitives = null;
    if (Primitives) {
      const statusVariant = info.locked ? 'locked' : (info.enabled ? 'available' : 'off');
      const card = Primitives.createCommandCard({
        title: this.formatToggleLabel(key),
        statusBadge: { variant: statusVariant },
        detail: () => {
          const wrap = document.createElement('div');
          wrap.className = 'toggle-detail-drawer';
          const desc = document.createElement('p');
          desc.textContent = info.description || "";
          wrap.appendChild(desc);

          if (info.locked) {
            const lockNotice = document.createElement("p");
            lockNotice.className = "toggle-description--locked";
            lockNotice.textContent = info.locked_reason || "Locked disabled.";
            wrap.appendChild(lockNotice);
          }
          return wrap;
        }
      });

      if (!info.locked) {
        const toggleContainer = document.createElement('div');
        toggleContainer.className = 'card-toggle-container';

        const toggleSwitch = document.createElement("label");
        toggleSwitch.className = "toggle-switch";
        const checkbox = document.createElement("input");
        checkbox.type = "checkbox";
        checkbox.checked = Boolean(info.enabled);
        checkbox.setAttribute("aria-label", `Toggle ${this.formatToggleLabel(key)}`);
        checkbox.addEventListener("change", () => {
          this.setToggle(key, checkbox.checked);
        });
        const slider = document.createElement("span");
        slider.className = "toggle-slider";
        toggleSwitch.appendChild(checkbox);
        toggleSwitch.appendChild(slider);

        toggleContainer.appendChild(toggleSwitch);
        card.appendChild(toggleContainer);
      }
      return card;
    }

    const card = document.createElement("div");
    card.className = "toggle-card";
    if (info.locked) card.classList.add("toggle-card--locked");
    const storedOnly = this.isStoredOnlyPreference(key, info);
    if (storedOnly) card.classList.add("toggle-card--stored-only");
    card.setAttribute("role", "region");
    card.setAttribute("aria-labelledby", `toggle-label-${key}`);
    /* Correction #13: explicit enabled/disabled state for CSS alignment. */
    card.dataset.enabled = info.locked || storedOnly
      ? "false"
      : (Boolean(info.enabled) ? "true" : "false");

    const header = document.createElement("div");
    header.className = "toggle-header";

    const label = document.createElement("div");
    label.className = "toggle-label command-card-title";
    label.id = `toggle-label-${key}`;
    label.textContent = this.formatToggleLabel(key);

    header.appendChild(label);
    let checkbox = null;
    if (info.locked) {
      const status = document.createElement('span');
      status.className = 'status-badge status-badge--locked toggle-status';
      status.textContent = 'Locked';
      header.appendChild(status);
    } else if (storedOnly) {
      const status = document.createElement('span');
      status.className = 'status-badge status-badge--locked toggle-status';
      status.textContent = 'Stored only';
      header.appendChild(status);
    } else {
      const toggleSwitch = document.createElement("label");
      toggleSwitch.className = "toggle-switch";

      checkbox = document.createElement("input");
      checkbox.type = "checkbox";
      checkbox.checked = Boolean(info.enabled);
      checkbox.setAttribute("aria-label", `Toggle ${label.textContent}`);
      checkbox.addEventListener("change", () => {
        this.setToggle(key, checkbox.checked);
      });

      const slider = document.createElement("span");
      slider.className = "toggle-slider";

      toggleSwitch.appendChild(checkbox);
      toggleSwitch.appendChild(slider);
      header.appendChild(toggleSwitch);
    }

    const desc = document.createElement("p");
    desc.className = "toggle-description detail-drawer-body";
    desc.textContent = info.locked
      ? this.lockedDescription(info)
      : (info.description || "");

    card.appendChild(header);
    card.appendChild(desc);

    return card;
  }

  lockedDescription(info) {
    const description = String(info.description || "").trim();
    const reason = String(info.locked_reason || "Locked disabled.").trim();
    return description.includes(reason) ? description : `${description} ${reason}`.trim();
  }

  isStoredOnlyPreference(key, info) {
    return ['ai_provider_calls', 'crash_reports', 'squadron_telemetry', 'usage_analytics'].includes(key)
      && /^(?:Stored local preference only|Local-only stored preference)\./i.test(String(info.description || ""));
  }

  formatToggleLabel(key) {
    const labels = {
      eddn_submission: "EDDN Market Data",
      edsm_tracking: "EDSM Tracking",
      squadron_telemetry: "Squadron Telemetry",
      ai_provider_calls: "AI Provider API Calls",
      crash_reports: "Crash Reports",
      usage_analytics: "Usage Analytics",
    };
    return labels[key] || key;
  }

  async setToggle(key, enabled) {
    const url = this.apiUrl(`/week13/privacy/toggles/${key}`);
    if (!url) return;
    try {
      const res = await fetch(url, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ enabled }),
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const result = await res.json();
      if (result.status === "locked") {
        await this.loadToggles();
      }
      console.log(`Privacy toggle ${key} set to ${enabled}`);
    } catch (err) {
      console.error(`Failed to set toggle ${key}:`, err);
      // Reload toggles to sync UI with server
      await this.loadToggles();
    }
  }

  async loadDataFlows() {
    try {
      // This map declares the current inert/reserved posture. No live
      // outbound implementation is activated by the stored preferences.
      return {
        flows: [
          {
            destination: "EDDN (Elite Dangerous Data Network)",
            status: "disabled",
            frequency: "Disabled in Phase 6 local-only baseline",
            purpose: "Future provider-specific playbook required",
            call_count: 0,
          },
          {
            destination: "EDSM (Elite Dangerous Star Map)",
            status: "disabled",
            frequency: "Disabled in Phase 6 local-only baseline",
            purpose: "Future provider-specific playbook required",
            call_count: 0,
          },
          {
            destination: "Squadron Servers",
            status: "not_shipped",
            frequency: "Reserved — requires future security doctrine",
            purpose: "No outbound squadron traffic in this baseline",
            call_count: 0,
          },
          {
            destination: "Telemetry Sync (peer)",
            status: "reserved",
            frequency: "Reserved — requires future security doctrine",
            purpose: "Reserved — requires future security doctrine",
            call_count: 0,
          },
          {
            destination: "Discord Integration",
            status: "reserved",
            frequency: "Reserved — requires provider enablement playbook",
            purpose: "Reserved — requires provider enablement playbook",
            call_count: 0,
          },
          {
            destination: "Top Secret Mode",
            status: "reserved",
            frequency: "Reserved — requires future security doctrine",
            purpose: "Reserved — requires future security doctrine",
            call_count: 0,
          },
          {
            destination: "Burn Command",
            status: "reserved",
            frequency: "Reserved — requires future security doctrine",
            purpose: "Reserved — requires future security doctrine",
            call_count: 0,
          },
          {
            destination: "Peer Relay",
            status: "reserved",
            frequency: "Reserved — requires future security doctrine",
            purpose: "Reserved — requires future security doctrine",
            call_count: 0,
          },
          {
            destination: "ChaCha20-Poly1305 In-Flight Encryption",
            status: "reserved",
            frequency: "Reserved — requires future security doctrine",
            purpose: "Reserved — requires future security doctrine",
            call_count: 0,
          },
          {
            destination: "Cross-Squadron Model (three-tier)",
            status: "reserved",
            frequency: "Reserved — requires future security doctrine",
            purpose: "Reserved — requires future security doctrine",
            call_count: 0,
          },
          {
            destination: "Loot Coordination",
            status: "reserved",
            frequency: "Reserved — requires future security doctrine",
            purpose: "Reserved — requires future security doctrine",
            call_count: 0,
          },
          {
            destination: "AI Provider API (Gemini/OpenAI/Local LLM)",
            status: "not_shipped",
            frequency: "Reserved — activation not wired in this build",
            purpose: "NullProvider remains the active runtime posture",
            call_count: 0,
          },
        ],
      };
    } catch (err) {
      console.error("Failed to load data flows:", err);
      return { flows: [] };
    }
  }

  async showDataFlowsModal() {
    const data = await this.loadDataFlows();
    const container = document.getElementById("data-flows-list");
    const noBanner = document.getElementById("no-flows-banner");

    if (!container) return;

    const flows = data.flows || [];
    const hasActiveFlows = flows.some((f) => f.status === "active");

    if (noBanner) {
      noBanner.style.display = hasActiveFlows ? "none" : "block";
    }

    container.replaceChildren();
    for (const flow of flows) {
      const card = this.createFlowCard(flow);
      container.appendChild(card);
    }

    document.getElementById("data-flows-modal").style.display = "flex";
  }

  createFlowCard(flow) {
    const card = document.createElement("div");
    card.className = "flow-card";

    const dest = document.createElement("div");
    dest.className = "flow-destination";
    dest.textContent = flow.destination;

    const status = document.createElement("span");
    status.className = `flow-status ${flow.status}`;
    status.textContent = this.formatFlowStatus(flow.status);

    const freq = document.createElement("div");
    freq.className = "flow-frequency";
    freq.textContent = `Frequency: ${flow.frequency}`;

    const purpose = document.createElement("div");
    purpose.className = "flow-purpose";
    purpose.textContent = `Purpose: ${flow.purpose}`;

    card.appendChild(dest);
    card.appendChild(status);
    card.appendChild(freq);
    card.appendChild(purpose);

    return card;
  }

  formatFlowStatus(status) {
    const labels = {
      active: "ACTIVE",
      disabled: "DISABLED",
      not_shipped: "NOT YET SHIPPED",
      reserved: "RESERVED",
    };
    return labels[status] || status;
  }

  bindButtons() {
    // Data Flows
    document.getElementById("view-data-flows-btn")?.addEventListener("click", () => {
      this.showDataFlowsModal();
    });

    document.getElementById("close-flows-modal-btn")?.addEventListener("click", () => {
      document.getElementById("data-flows-modal").style.display = "none";
    });

    // Export Data
    document.getElementById("export-data-btn")?.addEventListener("click", () => {
      this.exportData();
    });

    // Delete Data (Two-stage confirmation)
    document.getElementById("delete-data-btn")?.addEventListener("click", () => {
      this.showDeleteConfirmModal();
    });

    document.getElementById("delete-confirm-cancel-btn")?.addEventListener("click", () => {
      this.deleteConfirmStage = 0;
      document.getElementById("delete-confirm-modal").style.display = "none";
    });

    document.getElementById("delete-confirm-1st-btn")?.addEventListener("click", () => {
      this.deleteConfirmStage = 1;
      document.getElementById("delete-confirm-buttons").style.display = "none";
      document.getElementById("delete-confirm-2nd-buttons").style.display = "block";
    });

    document.getElementById("delete-confirm-cancel-2nd-btn")?.addEventListener("click", () => {
      this.deleteConfirmStage = 0;
      document.getElementById("delete-confirm-modal").style.display = "none";
      document.getElementById("delete-confirm-buttons").style.display = "block";
      document.getElementById("delete-confirm-2nd-buttons").style.display = "none";
    });

    document.getElementById("delete-confirm-2nd-btn")?.addEventListener("click", () => {
      this.permanentlyDeleteData();
    });
  }

  showDeleteConfirmModal() {
    this.deleteConfirmStage = 0;
    document.getElementById("delete-confirm-buttons").style.display = "flex";
    document.getElementById("delete-confirm-2nd-buttons").style.display = "none";
    document.getElementById("delete-confirm-modal").style.display = "flex";
  }

  async exportData() {
    const url = this.apiUrl('/week13/privacy/export');
    if (!url) return;

    try {
      const res = await fetch(url, {
        method: "POST",
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();

      // Create JSON blob and download
      const json = JSON.stringify(data, null, 2);
      const blob = new Blob([json], { type: "application/json" });
      const blobUrl = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = blobUrl;
      a.download = `omnicovas-configuration-snapshot-${new Date().toISOString().slice(0, 10)}.json`;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(blobUrl);

      console.log("Configuration snapshot exported successfully");
    } catch (err) {
      console.error("Failed to export data:", err);
      alert("Failed to export configuration snapshot. See console for details.");
    }
  }

  async permanentlyDeleteData() {
    const url = this.apiUrl('/week13/privacy/delete');
    if (!url) return;

    try {
      const res = await fetch(url, {
        method: "POST",
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);

      // Close modal
      document.getElementById("delete-confirm-modal").style.display = "none";

      // Show success message and reload
      alert("Configuration vault reset. Activity Log and local database records were not deleted. Please restart the app.");
      window.location.reload();
    } catch (err) {
      console.error("Failed to delete data:", err);
      alert("Failed to reset configuration vault. See console for details.");
    }
  }
}

// Initialize on page load
if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", () => {
    new PrivacyController();
  });
} else {
  new PrivacyController();
}

// Test hook for Vitest; keeps this browser-compatible without changing production module/script loading.
globalThis.__privacyExports = { PrivacyController };
