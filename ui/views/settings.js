/**
 * Phase 3 Week 13 — Settings Controller
 * PB05-08 — Settings page: tabs, overlay bridge, banner test center.
 * Humanized copy applied in PB07.6-09.
 *
 * Three-tier customization:
 *  - Tier 1: Preset profiles (quick starts)
 *  - Tier 2: Pillar categories (enable/disable entire features)
 *  - Tier 3: Granular settings (per-feature fine-tuning)
 */

/* UI v3 containment Settings IA. Sources moved out to its own
   Sources & Diagnostics surface (#view-sources-diagnostics) per
   v2.0 UI/UX Blueprint §9.6. Banner Test Center moved to Developer/Test. */
const SETTINGS_TABS = [
  'appearance',
  'command-center',
  'overlay',
  'ai',
  'controls',
  'data-refresh',
  'accessibility',
  'developer',
];

const KNOWN_BANNER_TYPES = [
  'HULL_CRITICAL_10',
  'SHIELDS_DOWN',
  'HULL_CRITICAL_25',
  'FUEL_CRITICAL',
  'MODULE_CRITICAL',
  'FUEL_LOW',
  'HEAT_WARNING',
  'HEAT_DAMAGE',
  'OMNICOVAS_TEST',
];

class SettingsController {
  constructor() {
    this.currentSettings = {};
    this._primitivesPromise = import('../components/command-primitives.js').catch(e => {
      console.error('[Settings] Failed to load command primitives:', e);
      return null;
    });
    this._localContextPromise = import('../view-models/local-context.js').catch(e => {
      console.error('[Settings] Failed to load local context VM:', e);
      return null;
    });
    this._localSurfacesPromise = import('../components/local-context-surfaces.js').catch(e => {
      console.error('[Settings] Failed to load local context surfaces:', e);
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
    this.bindEvents();
    this.bindTabs();

    if (!this.apiBase) {
      console.warn('[Settings] Bridge not ready; showing waiting state.');
      this._showWaiting();
      return;
    }

    await this._loadAndRender();
  }

  bindTabs() {
    const tabButtons = document.querySelectorAll('#settings-tablist [role="tab"]');
    tabButtons.forEach(btn => {
      btn.addEventListener('click', () => {
        const tabId = btn.id.replace('tab-', '');
        this._activateTab(tabId);
      });
    });
  }

  _activateTab(tabId) {
    if (!SETTINGS_TABS.includes(tabId)) return;

    // Update buttons
    document.querySelectorAll('#settings-tablist [role="tab"]').forEach(btn => {
      const active = btn.id === `tab-${tabId}`;
      btn.setAttribute('aria-selected', active);
    });

    // Update panels
    document.querySelectorAll('#settings-container [role="tabpanel"], #view-settings [role="tabpanel"]').forEach(panel => {
      const active = panel.id === `panel-${tabId}`;
      if (active) {
        panel.removeAttribute('hidden');
      } else {
        panel.setAttribute('hidden', '');
      }
    });

    if (tabId === 'overlay') {
      this._loadOverlaySettings();
    }
    /* Sources tab removed in correction #12 — Sources & Diagnostics is
       a real Systems surface now. Source health lookup still available
       for legacy consumers but no Settings tab triggers it. */
  }

  // ── Source health registry ───────────────────────

  async _loadSourceHealth() {
    const url = this.apiUrl('/source/health');
    if (!url) {
      this._showSourceHealthStatus('Bridge not ready — source health unavailable.');
      return;
    }
    try {
      const res = await fetch(url);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      await this._renderSourceHealth(data);
      await this._loadLocalContextDiagnostics();
      const statusEl = document.getElementById('sources-health-status');
      if (statusEl) statusEl.setAttribute('hidden', '');
    } catch (e) {
      console.warn('[Settings] Failed to load source health:', e);
      this._showSourceHealthStatus('Source health currently unavailable.');
    }
  }

  _showSourceHealthStatus(msg) {
    const el = document.getElementById('sources-health-status');
    if (!el) return;
    el.textContent = msg;
    el.removeAttribute('hidden');
  }

  async _loadLocalContextDiagnostics() {
    const url = this.apiUrl('/intel/local-context/snapshot');
    const grid = document.getElementById('sources-health-grid');
    if (!url || !grid) return;
    const [LocalContext, Surfaces] = await Promise.all([
      this._localContextPromise,
      this._localSurfacesPromise,
    ]);
    if (!LocalContext || !Surfaces) return;

    let payload = null;
    try {
      const res = await fetch(url);
      payload = res.ok ? await res.json() : null;
    } catch {
      payload = null;
    }
    const model = LocalContext.deriveLocalContext(payload);
    grid.appendChild(Surfaces.createLocalContextDiagnosticsSurface(model.diagnostics, {
      id: 'sources-local-context-diagnostics',
    }));
  }

  async _renderSourceHealth(data) {
    const Primitives = await this._primitivesPromise;
    const grid = document.getElementById('sources-health-grid');
    if (!grid || !data.sources) return;

    grid.replaceChildren();

    data.sources.forEach(source => {
      if (Primitives) {
        // Map source state to allowed status badge variants
        let variant = source.state;
        if (variant === 'enabled') variant = 'available';
        if (variant === 'requires_auth') variant = 'requires-auth';
        if (variant === 'requires_consent') variant = 'needs-setup'; // or add variant

        const card = Primitives.createCommandCard({
          title: source.display_name,
          statusBadge: { variant: variant, label: source.state.replace('_', ' ') },
          detail: () => {
            const detailWrap = document.createElement('div');
            detailWrap.className = 'source-health-details-drawer';

            const typeRow = this._createSourceHealthRow('Posturing', source.is_local ? 'Local-only' : 'External locked');
            const authRow = this._createSourceHealthRow('Auth Gate', source.requires_auth ? 'Active' : 'None');
            const consentRow = this._createSourceHealthRow('Consent Gate', source.requires_consent ? 'Active' : 'None');
            const healthRow = this._createSourceHealthRow('Availability', this._sourceAvailabilityLabel(source));

            detailWrap.appendChild(typeRow);
            detailWrap.appendChild(authRow);
            detailWrap.appendChild(consentRow);
            detailWrap.appendChild(healthRow);

            const privacy = document.createElement('div');
            privacy.className = 'source-health-privacy-notice';
            if (source.is_local) {
              privacy.textContent = 'Local file source — data stays on this machine.';
            } else {
              privacy.textContent = (
                'External providers are locked in this build. No outbound traffic. Future enablement requires Commander approval.'
              );
            }
            detailWrap.appendChild(privacy);
            return detailWrap;
          }
        });
        grid.appendChild(card);
      } else {
        const card = document.createElement('article');
        card.className = 'source-health-card';

        // Header
        const header = document.createElement('div');
        header.className = 'source-health-header';

        const title = document.createElement('span');
        title.className = 'source-health-title';
        title.textContent = source.display_name;

        const badge = document.createElement('span');
        badge.className = `source-health-status-badge status-${source.state}`;
        badge.textContent = source.state.replace('_', ' ');

        header.appendChild(title);
        header.appendChild(badge);

        // Details
        const details = document.createElement('div');
        details.className = 'source-health-details';

        const typeRow = this._createSourceHealthRow('Posturing', source.is_local ? 'Local-only' : 'External locked');
        const authRow = this._createSourceHealthRow('Auth Gate', source.requires_auth ? 'Active' : 'None');
        const consentRow = this._createSourceHealthRow('Consent Gate', source.requires_consent ? 'Active' : 'None');
        const healthRow = this._createSourceHealthRow('Availability', this._sourceAvailabilityLabel(source));

        details.appendChild(typeRow);
        details.appendChild(authRow);
        details.appendChild(consentRow);
        details.appendChild(healthRow);

        // Privacy Notice
        const privacy = document.createElement('div');
        privacy.className = 'source-health-privacy-notice';
        if (source.is_local) {
          privacy.textContent = 'Local file source — data stays on this machine.';
        } else {
          privacy.textContent = (
            'External provider disabled for Phase 6 local-only baseline. ' +
            'Future enablement requires Commander approval.'
          );
        }

        card.appendChild(header);
        card.appendChild(details);
        card.appendChild(privacy);

        grid.appendChild(card);
      }
    });
  }

  _sourceAvailabilityLabel(source) {
    if (source.is_local) {
      return source.is_available ? 'Connected' : 'Not Loaded';
    }

    const state = String(source.state || '');
    if (state === 'requires_auth') return 'Requires Authorization';
    if (state === 'requires_consent') return 'Requires Consent';
    if (state === 'blocked') return 'Blocked';
    return 'Disabled';
  }

  _createSourceHealthRow(label, value) {
    const row = document.createElement('div');
    row.className = 'source-health-row';

    const labelSpan = document.createElement('span');
    labelSpan.className = 'field-label';
    labelSpan.textContent = label;

    const valueSpan = document.createElement('span');
    valueSpan.className = 'field-value';
    valueSpan.textContent = value;

    row.appendChild(labelSpan);
    row.appendChild(valueSpan);
    return row;
  }

  // ── Overlay settings bridge ───────────────────────

  async _loadOverlaySettings() {
    const url = this.apiUrl('/pillar1/overlay/settings');
    if (!url) {
      this._showOverlaySettingsStatus('Bridge not ready — overlay settings unavailable.');
      return;
    }
    try {
      const res = await fetch(url);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      this._renderOverlaySettings(data);
      const statusEl = document.getElementById('overlay-settings-status');
      if (statusEl) statusEl.setAttribute('hidden', '');
    } catch (e) {
      console.warn('[Settings] Failed to load overlay settings:', e);
      this._showOverlaySettingsStatus('Overlay settings currently unavailable.');
    }
  }

  _showOverlaySettingsStatus(msg) {
    const el = document.getElementById('overlay-settings-status');
    if (!el) return;
    el.textContent = msg;
    el.removeAttribute('hidden');
  }

  _renderOverlaySettings(data) {
    const opacitySlider = document.getElementById('overlay-opacity');
    const opacityDisplay = document.getElementById('opacity-display');
    if (opacitySlider && data.opacity != null) {
      opacitySlider.value = data.opacity;
      if (opacityDisplay) opacityDisplay.textContent = `${Math.round(data.opacity * 100)}%`;
    }

    const anchorSelect = document.getElementById('overlay-anchor');
    if (anchorSelect && data.anchor) {
      anchorSelect.value = data.anchor;
    }

    if (data.events) {
      this._renderEventToggles(data.events);
      document.getElementById('overlay-event-toggles')?.removeAttribute('hidden');
    }

    const clickthroughState = document.getElementById('overlay-clickthrough-state');
    if (clickthroughState && data.clickthrough_ready !== undefined) {
      clickthroughState.textContent = data.clickthrough_ready
        ? 'Click-through is supported on this platform.'
        : 'Click-through is not supported — window is always interactive.';
      document.getElementById('overlay-clickthrough-info')?.removeAttribute('hidden');
    }
  }

  _renderEventToggles(events) {
    const grid = document.getElementById('overlay-event-grid');
    if (!grid) return;

    grid.replaceChildren();

    for (const [eventType, enabled] of Object.entries(events)) {
      const id = `overlay-event-toggle-${eventType.toLowerCase().replace(/_/g, '-')}`;
      const item = document.createElement('label');
      item.className = 'overlay-event-item';
      item.setAttribute('for', id);

      const checkbox = document.createElement('input');
      checkbox.type = 'checkbox';
      checkbox.id = id;
      checkbox.name = id;
      checkbox.checked = Boolean(enabled);
      checkbox.setAttribute('aria-label', `Toggle ${eventType} event`);
      checkbox.dataset.eventType = eventType;

      const nameSpan = document.createElement('span');
      nameSpan.textContent = eventType;

      item.appendChild(checkbox);
      item.appendChild(nameSpan);
      grid.appendChild(item);
    }
  }

  async _saveOverlaySettings() {
    const url = this.apiUrl('/pillar1/overlay/settings');
    if (!url) return;

    const opacity = parseFloat(document.getElementById('overlay-opacity')?.value || 0.95);
    const anchor = document.getElementById('overlay-anchor')?.value || 'center';
    const payload = { opacity, anchor };

    const eventCheckboxes = document.querySelectorAll('#overlay-event-grid input[type="checkbox"]');
    if (eventCheckboxes.length > 0) {
      payload.events = {};
      eventCheckboxes.forEach(cb => {
        if (cb.dataset.eventType) payload.events[cb.dataset.eventType] = cb.checked;
      });
    }

    try {
      const res = await fetch(url, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      console.log('[Settings] Overlay settings saved.');
    } catch (e) {
      console.error('[Settings] Failed to save overlay settings:', e);
    }
  }

  // ── Banner Test Center ────────────────────────────

  async _testGenericBanner() {
    const invoke = window.__TAURI__?.core?.invoke;
    if (typeof invoke !== 'function') {
      console.warn('[Settings] Tauri not available; banner test requires desktop app.');
      return;
    }
    await invoke('show_overlay_test_banner').catch(e =>
      console.warn('[Settings] Generic banner test failed:', e)
    );
  }

  async _testSelectedBanner() {
    const select = document.getElementById('btc-banner-type');
    const eventType = select?.value;
    if (!eventType || !KNOWN_BANNER_TYPES.includes(eventType)) return;

    const invoke = window.__TAURI__?.core?.invoke;
    if (typeof invoke !== 'function') {
      console.warn('[Settings] Tauri not available; banner test requires desktop app.');
      return;
    }
    await invoke('show_overlay_named_test_banner', { eventType }).catch(e =>
      console.warn('[Settings] Named banner test failed:', e)
    );
  }

  async _testAllBanners() {
    const invoke = window.__TAURI__?.core?.invoke;
    if (typeof invoke !== 'function') {
      console.warn('[Settings] Tauri not available; banner test requires desktop app.');
      return;
    }
    for (const eventType of KNOWN_BANNER_TYPES) {
      await invoke('show_overlay_named_test_banner', { eventType }).catch(e =>
        console.warn(`[Settings] Named banner test failed for ${eventType}:`, e)
      );
    }
  }

  // ── Load / render ─────────────────────────────────

  async _loadAndRender() {
    await this.loadSettings();
    this.renderUI();
  }

  _showWaiting() {
    const grid = document.getElementById('preset-grid');
    if (!grid) return;
    const p = document.createElement('p');
    p.className = 'field-value unknown';
    p.textContent = 'Waiting for OmniCOVAS bridge…';
    grid.replaceChildren(p);
  }

  async loadSettings() {
    if (!this.apiBase) return;
    try {
      const res = await fetch(`${this.apiBase}/week13/settings`);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      this.currentSettings = await res.json();
    } catch (err) {
      console.error('Failed to load settings:', err);
      this.currentSettings = this.getDefaults();
    }
  }

  getDefaults() {
    return {
      preset: 'casual',
      pillar_categories: {
        pillar_1: { enabled: true, phase_ready: true },
        pillar_2: { enabled: true, phase_ready: true, phase: 4, locked_on: true },
        pillar_3: { enabled: false, phase_ready: false, phase: 5 },
        pillar_5: { enabled: false, phase_ready: false, phase: 6 },
        pillar_7: { enabled: false, phase_ready: false, phase: 7 },
        pillar_6: { enabled: false, phase_ready: false, phase: 8 },
        pillar_4: { enabled: false, phase_ready: false, phase: 9 },
      },
      ai_provider: 'null',
      overlay: { opacity: 0.95, anchor: 'center' },
    };
  }

  renderUI() {
    this.renderRouteHero();
    this.renderPresets();
    this.renderPillarToggles();
    this.renderGranularSettings();
  }

  async renderRouteHero() {
    const Primitives = await this._primitivesPromise;
    if (!Primitives) return;

    const container = document.getElementById('view-settings');
    if (!container) return;

    // Remove existing hero if any
    container.querySelector('.route-hero')?.remove();

    const hero = Primitives.createRouteHero({
      title: 'Settings',
      kicker: 'Configuration',
      statusText: this.apiBase ? 'Settings available' : 'Bridge not ready',
      statusVariant: this.apiBase ? 'available' : 'not-loaded',
      primaryValues: [
        { label: 'Capabilities', value: Object.keys(this.currentSettings.pillar_categories || {}).length },
        { label: 'Posture', value: 'Local configuration' }
      ]
    });

    container.prepend(hero);
  }

  renderPresets() {
    const grid = document.getElementById('preset-grid');
    if (!grid) return;

    const presets = [
      { key: 'casual',   name: 'Casual',   icon: '\u{1F60E}' },
      { key: 'combat',   name: 'Combat',   icon: '⚔️' },
      { key: 'explorer', name: 'Explorer', icon: '\u{1F52D}' },
      { key: 'trader',   name: 'Trader',   icon: '\u{1F4E6}' },
      { key: 'miner',    name: 'Miner',    icon: '⛏️' },
    ];

    grid.replaceChildren();
    for (const preset of presets) {
      const btn = document.createElement('button');
      btn.type = 'button';
      btn.className = 'preset-button';
      if (preset.key === this.currentSettings.preset) btn.classList.add('active');
      btn.setAttribute('aria-label', `Select ${preset.name} preset`);

      const iconDiv = document.createElement('div');
      iconDiv.className = 'preset-icon';
      iconDiv.textContent = preset.icon;

      const nameDiv = document.createElement('div');
      nameDiv.className = 'preset-name';
      nameDiv.textContent = preset.name;

      btn.appendChild(iconDiv);
      btn.appendChild(nameDiv);
      btn.addEventListener('click', () => this.setPreset(preset.key));
      grid.appendChild(btn);
    }
  }

  async renderPillarToggles() {
    const Primitives = await this._primitivesPromise;
    const container = document.getElementById('tier2-toggles');
    if (!container) return;

    const cats = this.currentSettings.pillar_categories || {};
    container.replaceChildren();

    const pillarLabels = {
      pillar_1: 'Ship Telemetry',
      pillar_2: 'Combat',
      pillar_3: 'Exploration',
      pillar_5: 'Trading & Mining',
      pillar_7: 'Squadron',
      pillar_6: 'Engineering',
      pillar_4: 'Powerplay 2.0',
    };

    for (const [key, info] of Object.entries(cats)) {
      const isCombatPhase4 = key === 'pillar_2';
      const isSquadronActive = key === 'pillar_7';
      const isPhaseReady = Boolean(info.phase_ready) || isCombatPhase4;
      const isRoadmapOnly = !isPhaseReady;

      if (isRoadmapOnly && Primitives) {
        const row = Primitives.createReservedFeatureRow({
          name: pillarLabels[key],
          badge: 'reserved',
          onInspect: () => {
             alert(`This capability is reserved and not active in this build.`);
          }
        });
        container.appendChild(row);
        continue;
      }

      const id = `pillar-toggle-${key}`;
      const item = document.createElement('label');
      item.className = 'toggle-item';
      item.setAttribute('for', id);
      if (isCombatPhase4) {
        item.classList.add('toggle-item--locked');
      }

      const checkbox = document.createElement('input');
      checkbox.type = 'checkbox';
      checkbox.id = id;
      checkbox.name = id;
      checkbox.checked = isCombatPhase4 ? true : Boolean(info.enabled);
      checkbox.disabled = isCombatPhase4;
      checkbox.setAttribute(
        'aria-label',
        isCombatPhase4
          ? `${pillarLabels[key]} is current`
          : `Toggle ${pillarLabels[key]}`,
      );

      const label = document.createElement('span');
      label.className = 'toggle-label';
      label.textContent = pillarLabels[key];

      const phase = document.createElement('span');
      phase.className = 'toggle-phase';
      if (isSquadronActive) {
        phase.textContent = 'Active route — local coordination';
      } else if (isCombatPhase4) {
        phase.textContent = 'Available';
      }

      item.appendChild(checkbox);
      item.appendChild(label);
      if (phase.textContent) item.appendChild(phase);

      container.appendChild(item);

      if (isSquadronActive) {
        const linkRow = document.createElement('div');
        linkRow.className = 'pillar-route-link';
        const link = document.createElement('a');
        link.href = '#/squadrons';
        link.textContent = 'Open Squadron Console →';
        link.setAttribute('aria-label', 'Navigate to Squadron Console');
        linkRow.appendChild(link);
        container.appendChild(linkRow);
      }
    }
  }

  renderGranularSettings() {
    const opacitySlider = document.getElementById('overlay-opacity');
    const opacityDisplay = document.getElementById('opacity-display');
    if (opacitySlider) {
      opacitySlider.value = this.currentSettings.overlay?.opacity || 0.95;
      opacitySlider.addEventListener('input', (e) => {
        const val = parseFloat(e.target.value);
        if (opacityDisplay) opacityDisplay.textContent = `${Math.round(val * 100)}%`;
      });
    }

    const anchorSelect = document.getElementById('overlay-anchor');
    if (anchorSelect) anchorSelect.value = this.currentSettings.overlay?.anchor || 'center';

    const aiSelect = document.getElementById('ai-provider');
    if (aiSelect) aiSelect.value = 'null';

    const outputRadios = document.querySelectorAll('input[name="output-mode"]');
    outputRadios.forEach((radio) => {
      if (radio.value === 'overlay') radio.checked = true;
    });
  }

  bindEvents() {
    document.getElementById('save-settings-btn')?.addEventListener('click', () => this.saveSettings());
    document.getElementById('reset-settings-btn')?.addEventListener('click', () => this.resetSettings());
    document.getElementById('export-settings-btn')?.addEventListener('click', () => this.exportSettings());
    document.getElementById('import-settings-btn')?.addEventListener('click', () => this.importSettings());
    document.getElementById('save-overlay-settings-btn')?.addEventListener('click', () => this._saveOverlaySettings());
    document.getElementById('btc-test-generic-btn')?.addEventListener('click', () => this._testGenericBanner());
    document.getElementById('btc-test-selected-btn')?.addEventListener('click', () => this._testSelectedBanner());
    document.getElementById('btc-test-all-btn')?.addEventListener('click', () => this._testAllBanners());
    document.getElementById('rerun-setup-btn')?.addEventListener('click', () => this.resetSetup());
    document.getElementById('reset-license-btn')?.addEventListener('click', () => this.resetLicenseAck());
  }

  setPreset(preset) {
    this.currentSettings.preset = preset;
    this.renderPresets();
  }

  async saveSettings() {
    const url = this.apiUrl('/week13/settings');
    if (!url) return;

    const overlay = {
      opacity: parseFloat(document.getElementById('overlay-opacity')?.value || 0.95),
      anchor: document.getElementById('overlay-anchor')?.value || 'center',
    };
    const aiProvider = 'null';
    const payload = { preset: this.currentSettings.preset, overlay, ai_provider: aiProvider };

    try {
      const res = await fetch(url, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      alert('Settings saved!');
      await this.loadSettings();
      this.renderUI();
    } catch (err) {
      console.error('Failed to save settings:', err);
      alert('Failed to save settings. See console for details.');
    }
  }

  async resetSettings() {
    if (!confirm('Reset all settings to defaults?')) return;
    const url = this.apiUrl('/week13/settings/reset');
    if (!url) return;
    try {
      const res = await fetch(url, { method: 'POST' });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      await this.loadSettings();
      this.renderUI();
      alert('Settings reset to defaults!');
    } catch (err) {
      console.error('Failed to reset settings:', err);
      alert('Failed to reset settings. See console for details.');
    }
  }

  async exportSettings() {
    const url = this.apiUrl('/week13/settings/export');
    if (!url) return;
    try {
      const res = await fetch(url, { method: 'POST' });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      const json = JSON.stringify(data, null, 2);
      const blob = new Blob([json], { type: 'application/json' });
      const blobUrl = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = blobUrl;
      a.download = `omnicovas-settings-${new Date().toISOString().slice(0, 10)}.json`;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(blobUrl);
    } catch (err) {
      console.error('Failed to export settings:', err);
      alert('Failed to export settings. See console for details.');
    }
  }

  async resetSetup() {
    if (!confirm('Re-run the first-time setup wizard? This will re-show the setup wizard on next launch. Your license acknowledgement and settings are not affected.')) return;
    const url = this.apiUrl('/week13/onboarding/reset');
    if (!url) return;
    try {
      const res = await fetch(url, { method: 'POST' });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      alert('Setup wizard will re-run on next launch.');
    } catch (err) {
      console.error('[Settings] Failed to reset setup:', err);
      alert('Failed to reset setup. See console for details.');
    }
  }

  async resetLicenseAck() {
    if (!confirm('Reset your license acknowledgement? You will need to re-read and agree to the OmniCOVAS license before using the app again.')) return;
    const url = this.apiUrl('/week13/license/reset');
    if (!url) return;
    try {
      const res = await fetch(url, { method: 'POST' });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      alert('License acknowledgement reset. The license screen will appear on next launch.');
    } catch (err) {
      console.error('[Settings] Failed to reset license acknowledgement:', err);
      alert('Failed to reset license acknowledgement. See console for details.');
    }
  }

  async importSettings() {
    const input = document.createElement('input');
    input.type = 'file';
    input.id = 'settings-import-file-input';
    input.name = 'settings-import-file-input';
    input.accept = '.json';
    input.addEventListener('change', async (e) => {
      const file = e.target.files?.[0];
      if (!file) return;
      try {
        const text = await file.text();
        const data = JSON.parse(text);
        if (!confirm('This will overwrite your current settings. Continue?')) return;
        const url = this.apiUrl('/week13/settings/import');
        if (!url) return;
        const res = await fetch(url, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(data),
        });
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        await this.loadSettings();
        this.renderUI();
        alert('Settings imported!');
      } catch (err) {
        console.error('Failed to import settings:', err);
        alert('Failed to import settings. See console for details.');
      }
    });
    input.click();
  }
}

// Initialize on page load
if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', () => new SettingsController());
} else {
  new SettingsController();
}

// Test hook for Vitest; keeps this browser-compatible without changing production module/script loading.
globalThis.__settingsExports = { SettingsController, SETTINGS_TABS, KNOWN_BANNER_TYPES };
