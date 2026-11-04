/**
 * Phase 3 Week 13 — Privacy Page Controller
 *
 * Manages privacy toggles, data export, and data deletion.
 * All toggles default OFF (Law 8: Privacy-by-Default).
 */

class PrivacyController {
  constructor() {
    this.memoryStatus = null;
    this.memoryActionInFlight = false;
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

  async confirmProtectedAction(options) {
    const gate = window.OmniConfirmationGate;
    if (!gate?.confirmLocalAction) {
      console.error('[Privacy] Shared Confirmation Gate is unavailable.');
      return false;
    }
    return gate.confirmLocalAction(options);
  }

  notify(message, kind = 'info') {
    if (window.OmniConfirmationGate?.announce) {
      window.OmniConfirmationGate.announce(message, { kind });
    } else {
      console.info(`[Privacy] ${message}`);
    }
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
    await Promise.all([this.loadToggles(), this.loadMemoryStatus()]);
  }

  async renderRouteHero() {
    const Primitives = await this._primitivesPromise;
    if (!Primitives) return;

    const container = document.getElementById('view-privacy');
    if (!container) return;

    container.querySelector('.route-hero')?.remove();
    container.querySelector('.page-header')?.remove();
    container.querySelector('.ocv-page-header')?.remove();

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
    this.renderMemoryUnavailable('Waiting for the local backend bridge.');
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

  async loadMemoryStatus(options = {}) {
    const url = this.apiUrl('/memory/status');
    if (!url) {
      this.renderMemoryUnavailable('Waiting for the local backend bridge.');
      return;
    }
    try {
      const res = await fetch(url);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      this.memoryStatus = data;
      this.renderMemory(data, options);
    } catch (err) {
      console.error('[Privacy] Commander Memory status unavailable:', err);
      this.memoryStatus = null;
      this.renderMemoryUnavailable(
        'Commander Memory is unavailable. Existing local data was not changed.',
      );
    }
  }

  renderMemoryUnavailable(message) {
    const badge = document.getElementById('memory-status-badge');
    if (badge) {
      badge.className = 'status-badge status-badge--not-loaded';
      badge.textContent = 'Unavailable';
    }
    this.setText('memory-total-records', '—');
    this.setText('memory-profile-count', '—');
    this.setText('memory-last-rebuild', 'Unknown');
    for (const id of [
      'memory-pause-btn',
      'memory-rebuild-btn',
      'memory-export-btn',
      'memory-clear-btn',
    ]) {
      const button = document.getElementById(id);
      if (button) button.disabled = true;
    }
    for (const id of ['memory-categories-list', 'memory-profiles-list']) {
      const container = document.getElementById(id);
      if (!container) continue;
      const empty = document.createElement('p');
      empty.className = 'field-value unknown memory-empty';
      empty.textContent = message;
      container.replaceChildren(empty);
    }
    this.setMemoryActionStatus(message, 'warning');
  }

  setText(id, value) {
    const element = document.getElementById(id);
    if (element) element.textContent = String(value);
  }

  setMemoryActionStatus(message, kind = 'info') {
    const status = document.getElementById('memory-action-status');
    if (!status) return;
    status.textContent = String(message || '');
    status.dataset.kind = kind;
  }

  formatObservedTime(value) {
    if (!value) return 'Never';
    const parsed = new Date(value);
    if (Number.isNaN(parsed.getTime())) return 'Unknown';
    return parsed.toLocaleString();
  }

  renderMemory(data, options = {}) {
    const paused = Boolean(data?.paused);
    const rebuilding = Boolean(data?.rebuilding);
    const total = Number(data?.total_records || 0);
    const profiles = Array.isArray(data?.profiles) ? data.profiles : [];
    const badge = document.getElementById('memory-status-badge');
    if (badge) {
      badge.className = `status-badge status-badge--${
        rebuilding ? 'stale' : paused ? 'disabled' : total > 0 ? 'available' : 'not-loaded'
      }`;
      badge.textContent = rebuilding
        ? 'Rebuilding'
        : paused
          ? 'Paused'
          : total > 0
            ? 'Remembering locally'
            : 'Ready — empty';
    }

    this.setText('memory-total-records', total.toLocaleString());
    this.setText('memory-profile-count', profiles.length.toLocaleString());
    this.setText('memory-last-rebuild', this.formatObservedTime(data?.last_rebuild_at));

    const busy = this.memoryActionInFlight || rebuilding;
    const pauseButton = document.getElementById('memory-pause-btn');
    if (pauseButton) {
      pauseButton.disabled = busy;
      pauseButton.textContent = paused ? 'Resume Memory' : 'Pause Memory';
      pauseButton.setAttribute('aria-pressed', String(paused));
    }
    const rebuildButton = document.getElementById('memory-rebuild-btn');
    if (rebuildButton) rebuildButton.disabled = busy;
    const exportButton = document.getElementById('memory-export-btn');
    if (exportButton) exportButton.disabled = busy;
    const clearButton = document.getElementById('memory-clear-btn');
    if (clearButton) clearButton.disabled = busy || total === 0;

    this.renderMemoryCategories(data?.categories || {}, busy);
    this.renderMemoryProfiles(profiles, busy);
    if (!this.memoryActionInFlight && !options.preserveMessage) {
      this.setMemoryActionStatus(
        paused
          ? 'Acquisition is paused. Existing remembered records remain available.'
          : rebuilding
            ? 'Rebuilding from retained local history. Current sources still outrank Memory.'
            : 'Commander Memory is local-only and records observed history, never current truth.',
        paused || rebuilding ? 'warning' : 'info',
      );
    }
  }

  renderMemoryCategories(categories, busy) {
    const container = document.getElementById('memory-categories-list');
    if (!container) return;
    container.replaceChildren();
    const labels = {
      systems: 'Systems',
      stations: 'Stations',
      market: 'Market snapshots',
      outfitting: 'Outfitting snapshots',
      shipyard: 'Shipyard snapshots',
    };
    for (const [category, label] of Object.entries(labels)) {
      const count = Number(categories?.[category] || 0);
      const row = document.createElement('article');
      row.className = 'memory-record';
      row.dataset.memoryCategory = category;

      const header = document.createElement('div');
      header.className = 'memory-record-header';
      const title = document.createElement('span');
      title.className = 'memory-record-title';
      title.textContent = label;
      const countElement = document.createElement('span');
      countElement.className = 'status-badge status-badge--cached';
      countElement.textContent = `${count.toLocaleString()} remembered`;
      header.append(title, countElement);

      const actions = document.createElement('div');
      actions.className = 'memory-record-actions';
      const remove = document.createElement('button');
      remove.type = 'button';
      remove.className = 'privacy-danger-button cmd-btn cmd-btn--danger';
      remove.textContent = `Delete ${label}`;
      remove.disabled = busy || count === 0;
      remove.addEventListener('click', () => {
        this.runProtectedMemoryAction('delete_category', { category });
      });
      actions.appendChild(remove);
      row.append(header, actions);
      container.appendChild(row);
    }
  }

  renderMemoryProfiles(profiles, busy) {
    const container = document.getElementById('memory-profiles-list');
    if (!container) return;
    container.replaceChildren();
    if (profiles.length === 0) {
      const empty = document.createElement('p');
      empty.className = 'field-value unknown memory-empty';
      empty.textContent = 'No local Commander profile has been observed yet.';
      container.appendChild(empty);
      return;
    }
    for (const profile of profiles) {
      const forgotten = Boolean(profile?.forgotten);
      const paused = Boolean(profile?.paused);
      const row = document.createElement('article');
      row.className = 'memory-record';
      row.dataset.memoryProfile = String(profile?.profile_key || '');

      const header = document.createElement('div');
      header.className = 'memory-record-header';
      const title = document.createElement('span');
      title.className = 'memory-record-title';
      title.textContent = forgotten
        ? 'Forgotten local profile'
        : String(profile?.display_name || 'Local Commander profile');
      const state = document.createElement('span');
      state.className = `status-badge status-badge--${forgotten || paused ? 'disabled' : 'local-only'}`;
      state.textContent = forgotten ? 'Forgotten' : paused ? 'Paused' : 'Active';
      header.append(title, state);

      const meta = document.createElement('p');
      meta.className = 'memory-record-meta';
      meta.textContent = forgotten
        ? 'Display name removed; paused tombstone prevents silent rebuild.'
        : `First seen ${this.formatObservedTime(profile?.first_seen_at)} · Last seen ${this.formatObservedTime(profile?.last_seen_at)}`;

      const actions = document.createElement('div');
      actions.className = 'memory-record-actions';
      if (!forgotten) {
        const pause = document.createElement('button');
        pause.type = 'button';
        pause.className = 'privacy-secondary-button cmd-btn cmd-btn--quiet';
        pause.textContent = paused ? 'Resume Profile' : 'Pause Profile';
        pause.disabled = busy;
        pause.addEventListener('click', () => {
          this.setMemoryProfilePaused(profile.profile_key, !paused);
        });
        const forget = document.createElement('button');
        forget.type = 'button';
        forget.className = 'privacy-danger-button cmd-btn cmd-btn--danger';
        forget.textContent = 'Forget Profile';
        forget.disabled = busy;
        forget.addEventListener('click', () => {
          this.runProtectedMemoryAction('forget_profile', {
            profile_key: profile.profile_key,
          });
        });
        actions.append(pause, forget);
      }
      row.append(header, meta, actions);
      container.appendChild(row);
    }
  }

  async setMemoryPaused(paused) {
    const url = this.apiUrl('/memory/pause');
    if (!url || this.memoryActionInFlight) return;
    this.memoryActionInFlight = true;
    this.renderMemory(this.memoryStatus || {});
    this.setMemoryActionStatus(paused ? 'Pausing Memory acquisition…' : 'Resuming Memory acquisition…');
    try {
      const res = await fetch(url, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ paused: Boolean(paused) }),
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      this.memoryStatus = await res.json();
      this.setMemoryActionStatus(
        paused
          ? 'Memory acquisition paused. Existing records were not deleted.'
          : 'Memory acquisition resumed for new local observations.',
        'success',
      );
    } catch (err) {
      console.error('[Privacy] Failed to change Memory pause state:', err);
      this.setMemoryActionStatus('Could not change Memory acquisition state.', 'error');
    } finally {
      this.memoryActionInFlight = false;
      await this.loadMemoryStatus({ preserveMessage: true });
    }
  }

  async setMemoryProfilePaused(profileKey, paused) {
    const encoded = encodeURIComponent(String(profileKey || ''));
    const url = this.apiUrl(`/memory/profiles/${encoded}/pause`);
    if (!url || this.memoryActionInFlight) return;
    this.memoryActionInFlight = true;
    this.renderMemory(this.memoryStatus || {});
    try {
      const res = await fetch(url, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ paused: Boolean(paused) }),
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      this.setMemoryActionStatus(
        paused
          ? 'Profile acquisition paused. Existing records remain available.'
          : 'Profile acquisition resumed.',
        'success',
      );
    } catch (err) {
      console.error('[Privacy] Failed to change profile pause state:', err);
      this.setMemoryActionStatus('Could not change the profile pause state.', 'error');
    } finally {
      this.memoryActionInFlight = false;
      await this.loadMemoryStatus({ preserveMessage: true });
    }
  }

  async runProtectedMemoryAction(action, parameters = {}) {
    if (this.memoryActionInFlight) return;
    const gate = window.OmniConfirmationGate;
    const proposeUrl = this.apiUrl('/memory/actions/propose');
    const authorizeUrl = this.apiUrl('/memory/actions/authorize');
    if (!gate?.delay || !proposeUrl || !authorizeUrl) {
      this.setMemoryActionStatus(
        'The shared Confirmation Gate or local backend is unavailable. Nothing changed.',
        'error',
      );
      return;
    }

    this.memoryActionInFlight = true;
    this.renderMemory(this.memoryStatus || {});
    let confirmationId = null;
    try {
      const proposal = await fetch(proposeUrl, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ action, ...parameters }),
      });
      if (!proposal.ok) throw await this.memoryHttpError(proposal);
      const proposed = await proposal.json();
      confirmationId = proposed?.confirmation_id || null;
      if (!confirmationId) throw new Error('No confirmation id was returned.');
      this.setMemoryActionStatus(
        'Awaiting your decision in the shared Confirmation Gate. Nothing has changed yet.',
        'warning',
      );
      const result = await this.awaitMemoryAuthorization(authorizeUrl, confirmationId);
      if (action === 'export') {
        await this.downloadMemoryExport(result);
      } else {
        this.setMemoryActionStatus(this.memoryActionSuccessMessage(action, result), 'success');
      }
    } catch (err) {
      console.error('[Privacy] Protected Memory action did not complete:', err);
      this.setMemoryActionStatus(
        err?.commanderMessage || 'The Memory action did not complete. Existing data is unchanged unless a success was reported.',
        'error',
      );
    } finally {
      this.memoryActionInFlight = false;
      await this.loadMemoryStatus({ preserveMessage: true });
    }
  }

  async awaitMemoryAuthorization(authorizeUrl, confirmationId) {
    const gate = window.OmniConfirmationGate;
    for (let attempt = 0; attempt < 300; attempt += 1) {
      const res = await fetch(authorizeUrl, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ confirmation_id: confirmationId }),
      });
      if (res.ok) {
        const data = await res.json();
        if (data?.authorized) return data;
        await gate.delay(1000);
        continue;
      }
      throw await this.memoryHttpError(res);
    }
    const error = new Error('Commander Memory confirmation wait timed out.');
    error.commanderMessage = 'The confirmation timed out. No Memory action was authorized.';
    throw error;
  }

  async memoryHttpError(response) {
    let detail = '';
    try {
      detail = String((await response.json())?.detail || '');
    } catch (_error) {
      detail = '';
    }
    const error = new Error(`HTTP ${response.status}: ${detail}`);
    error.commanderMessage = /declin/i.test(detail)
      ? 'You declined the Memory action. Nothing changed.'
      : /expired|timed out/i.test(detail)
        ? 'The confirmation expired. No Memory action was authorized.'
        : detail || 'The local backend refused the Memory action.';
    return error;
  }

  memoryActionSuccessMessage(action, result) {
    const count = Number(result?.deleted_records || 0).toLocaleString();
    const messages = {
      clear: `Commander Memory cleared — ${count} derived records removed. The flight recorder was preserved.`,
      delete_category: `Remembered category deleted — ${count} derived records removed.`,
      forget_profile: `Profile forgotten — ${count} derived records removed and acquisition left paused.`,
      rebuild: `Commander Memory rebuilt from ${Number(result?.events_scanned || 0).toLocaleString()} retained local events.`,
    };
    return messages[action] || 'Commander Memory action completed.';
  }

  async downloadMemoryExport(result) {
    const resultUrl = this.apiUrl('/memory/export/result');
    const exportId = result?.export_id;
    if (!resultUrl || !exportId || !result?.payload) {
      throw new Error('The backend returned an incomplete export ticket.');
    }
    let filename = null;
    try {
      const json = JSON.stringify(result.payload, null, 2);
      const blob = new Blob([json], { type: 'application/json' });
      const blobUrl = URL.createObjectURL(blob);
      filename = `omnicovas-commander-memory-${new Date().toISOString().slice(0, 10)}.json`;
      const anchor = document.createElement('a');
      anchor.href = blobUrl;
      anchor.download = filename;
      document.body.appendChild(anchor);
      anchor.click();
      anchor.remove();
      URL.revokeObjectURL(blobUrl);
    } catch (err) {
      await this.reportMemoryExportResult(resultUrl, exportId, 'failed');
      throw err;
    }
    const recorded = await this.reportMemoryExportResult(
      resultUrl,
      exportId,
      'download_initiated',
    );
    this.setMemoryActionStatus(
      recorded
        ? `Commander Memory download initiated as ${filename}. Completion cannot be observed.`
        : `Download initiated as ${filename}, but the proof result could not be recorded.`,
      recorded ? 'success' : 'warning',
    );
  }

  async reportMemoryExportResult(url, exportId, outcome) {
    for (let attempt = 0; attempt < 2; attempt += 1) {
      try {
        const res = await fetch(url, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ export_id: exportId, outcome }),
        });
        if (res.ok) return true;
        if (res.status < 500) return false;
      } catch (err) {
        console.error('[Privacy] Memory export result report failed:', err);
      }
    }
    return false;
  }

  openMemoryProof() {
    if (typeof window.Shell?.startRouteTransfer !== 'function') {
      window.location.hash = '#/activity-log';
      return;
    }
    window.Shell.startRouteTransfer({
      originRoute: '/privacy',
      originPackage: 'Privacy',
      originSectionId: 'commander-memory-section',
      targetRoute: '/activity-log',
      targetSectionId: 'log-search',
      targetEntityId: 'commander-memory',
      targetLabel: 'Commander Memory proof',
      reason: 'Review Commander Memory actions and confirmation evidence.',
      returnLabel: 'Return to Commander Memory controls',
      returnTarget: { route: '/privacy', sectionId: 'commander-memory-section' },
    });
  }

  openObservedGalaxy() {
    if (typeof window.Shell?.startRouteTransfer !== 'function') {
      window.location.hash = '#/intel';
      return;
    }
    window.Shell.startRouteTransfer({
      originRoute: '/privacy',
      originPackage: 'Privacy',
      originSectionId: 'commander-memory-section',
      targetRoute: '/intel',
      targetSectionId: 'intel-domain-memory',
      targetEntityId: 'commander-memory',
      targetLabel: 'Observed Galaxy',
      reason: 'Explore private remembered systems, stations, and local snapshots.',
      returnLabel: 'Return to Commander Memory controls',
      returnTarget: { route: '/privacy', sectionId: 'commander-memory-section' },
    });
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

    this.openDataFlowsModal();
  }

  /* FU-013 (C1): the outbound-posture dialog is visually modal but had no
     focus management — no aria-modal, no focus moved in, no trap, no Escape,
     and no restoration on close. A keyboard or screen-reader commander opened
     a blocking dialog while their focus stayed behind it, able to tab into
     content the dialog was covering. */
  openDataFlowsModal() {
    const modal = document.getElementById("data-flows-modal");
    if (!modal) return;
    this.flowsModalReturnFocus = document.activeElement;
    modal.setAttribute("aria-modal", "true");
    modal.style.display = "flex";

    if (!this.flowsModalKeydown) {
      this.flowsModalKeydown = (event) => {
        if (event.key === "Escape") {
          event.preventDefault();
          this.closeDataFlowsModal();
          return;
        }
        if (event.key !== "Tab") return;
        const focusable = this.focusableWithin(modal);
        if (focusable.length === 0) return;
        const first = focusable[0];
        const last = focusable[focusable.length - 1];
        const active = document.activeElement;
        if (event.shiftKey && (active === first || !modal.contains(active))) {
          event.preventDefault();
          last.focus();
        } else if (!event.shiftKey && active === last) {
          event.preventDefault();
          first.focus();
        }
      };
    }
    document.addEventListener("keydown", this.flowsModalKeydown, true);

    const focusable = this.focusableWithin(modal);
    (focusable[0] || modal).focus?.();
  }

  closeDataFlowsModal() {
    const modal = document.getElementById("data-flows-modal");
    if (!modal) return;
    modal.style.display = "none";
    modal.removeAttribute("aria-modal");
    if (this.flowsModalKeydown) {
      document.removeEventListener("keydown", this.flowsModalKeydown, true);
    }
    /* Return the commander to the control they opened it from, not to the
       top of the document. */
    const target = this.flowsModalReturnFocus;
    this.flowsModalReturnFocus = null;
    if (target && typeof target.focus === "function" && document.contains(target)) {
      target.focus();
    }
  }

  focusableWithin(root) {
    const selector = [
      "button:not([disabled])",
      "a[href]",
      "input:not([disabled])",
      "select:not([disabled])",
      "textarea:not([disabled])",
      '[tabindex]:not([tabindex="-1"])',
    ].join(",");
    return Array.from(root.querySelectorAll(selector)).filter((el) => {
      const rect = el.getBoundingClientRect();
      return rect.width > 0 && rect.height > 0;
    });
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
    document.getElementById('memory-refresh-btn')?.addEventListener('click', () => {
      this.loadMemoryStatus();
    });
    document.getElementById('memory-observed-galaxy-btn')?.addEventListener('click', () => {
      this.openObservedGalaxy();
    });
    document.getElementById('memory-pause-btn')?.addEventListener('click', () => {
      this.setMemoryPaused(!Boolean(this.memoryStatus?.paused));
    });
    document.getElementById('memory-rebuild-btn')?.addEventListener('click', () => {
      this.runProtectedMemoryAction('rebuild');
    });
    document.getElementById('memory-export-btn')?.addEventListener('click', () => {
      this.runProtectedMemoryAction('export');
    });
    document.getElementById('memory-clear-btn')?.addEventListener('click', () => {
      this.runProtectedMemoryAction('clear');
    });
    document.getElementById('memory-proof-btn')?.addEventListener('click', () => {
      this.openMemoryProof();
    });

    // Data Flows
    document.getElementById("view-data-flows-btn")?.addEventListener("click", () => {
      this.showDataFlowsModal();
    });

    document.getElementById("close-flows-modal-btn")?.addEventListener("click", () => {
      this.closeDataFlowsModal();
    });

    // Export Data
    document.getElementById("export-data-btn")?.addEventListener("click", () => {
      this.exportData();
    });

    // Delete Data — two stages rendered by the shared Confirmation Gate.
    document.getElementById("delete-data-btn")?.addEventListener("click", () => {
      this.showDeleteConfirmModal();
    });
  }

  async showDeleteConfirmModal() {
    const confirmed = await this.confirmProtectedAction({
      title: 'Reset configuration vault?',
      message: 'This clears vault-backed settings and privacy preferences. Activity Log and local database records are not deleted.',
      confirmLabel: 'I understand',
      secondMessage: 'Confirm the final configuration-vault reset.',
      finalConfirmLabel: 'Reset configuration vault',
      danger: true,
    });
    if (confirmed) await this.permanentlyDeleteData();
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
      this.notify('Failed to export configuration snapshot. See console for details.', 'error');
    }
  }

  async permanentlyDeleteData() {
    const url = this.apiUrl('/week13/privacy/delete');
    if (!url) return;

    try {
      const res = await fetch(url, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ confirmed: true }),
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);

      // Close modal
      this.notify(
        'Configuration vault reset. Activity Log and local database records were not deleted. Please restart the app.',
        'success',
      );
      window.location.reload();
    } catch (err) {
      console.error("Failed to delete data:", err);
      this.notify('Failed to reset configuration vault. See console for details.', 'error');
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
