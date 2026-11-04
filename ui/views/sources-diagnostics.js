/**
 * OmniCOVAS Sources & Diagnostics - Systems surface.
 *
 * Organized proof surface for backend bridge, Elite session watcher, local
 * context endpoint, local source files, missing sources, freshness, caveats,
 * and disabled external dataset posture (Ardent). Safe DOM only.
 */
(function () {
  'use strict';

  let freshnessVocabulary = null;
  const freshnessVocabularyPromise = import('../utils/freshness.js').then((mod) => {
    freshnessVocabulary = mod;
    return mod;
  }).catch((err) => {
    console.error('[sources-diagnostics] Failed to load freshness vocabulary:', err);
    return null;
  });

  function safeEl(tag, className, text) {
    const el = document.createElement(tag);
    if (className) el.className = className;
    if (text != null) el.textContent = String(text);
    return el;
  }

  function apiBase() {
    if (window.Shell?.httpBase) return window.Shell.httpBase;
    if (window.OMNICOVAS_PORT) return `http://127.0.0.1:${window.OMNICOVAS_PORT}`;
    return null;
  }

  async function fetchJson(path) {
    const base = apiBase();
    if (!base) return null;
    try {
      const r = await fetch(`${base}${path}`);
      return r.ok ? await r.json() : null;
    } catch {
      return null;
    }
  }

  function getRoot() {
    return document.getElementById('sources-diagnostics-root');
  }

  function section(title, id) {
    const card = safeEl('section', 'sources-section');
    if (id) card.id = id;
    card.appendChild(safeEl('h2', 'sources-section-title section-title', title));
    return card;
  }

  function badge(label, state = 'unknown') {
    return safeEl('span', `sources-badge sources-badge--${state}`, label);
  }

  function appendRow(parent, label, value, state = null) {
    const row = safeEl('div', 'sources-row');
    row.appendChild(safeEl('span', 'sources-row-label', label));
    const valueWrap = safeEl('span', 'sources-row-value');
    if (state) valueWrap.appendChild(badge(value ?? 'Unknown', state));
    else valueWrap.textContent = value ?? 'Unknown';
    row.appendChild(valueWrap);
    parent.appendChild(row);
  }

  function freshness(node) {
    const input = node && typeof node === 'object'
      ? node
      : { freshness: node ? 'loaded' : 'not_loaded' };
    return freshnessVocabulary?.freshnessLabel(input) || 'Unknown';
  }

  function isLoaded(node, extra = false) {
    if (extra) return true;
    if (!node || typeof node !== 'object') return false;
    if (node.fallback) return false;
    return freshnessVocabulary?.describeFreshness(node).key !== 'not_loaded';
  }

  function statusFor(loaded) {
    return loaded ? ['Loaded', 'loaded'] : ['Not loaded', 'not-loaded'];
  }

  function buildBridgeSection() {
    const card = section('Backend Bridge', 'sources-backend-bridge');
    appendRow(card, 'Bridge state', window.Shell?.connected ? 'Connected' : 'Disconnected',
      window.Shell?.connected ? 'loaded' : 'not-loaded');
    appendRow(card, 'Backend port', window.Shell?.port ?? window.OMNICOVAS_PORT ?? 'Unknown');
    appendRow(card, 'HTTP base', window.Shell?.httpBase || 'Unknown');
    return card;
  }

  const STARTUP_STAGE_LABELS = Object.freeze({
    starting: 'Starting',
    local_sources_locating: 'Locating local sources',
    hydrating_local_state: 'Hydrating local state',
    ready_live: 'Ready — live local data',
    ready_limited: 'Ready — limited mode',
    blocked_local_setup: 'Local setup blocked',
  });

  function buildStartupOutcomeSection() {
    const card = section('Startup Outcome', 'sources-startup-outcome');
    const outcome = window.Shell?.startupOutcome || null;
    if (!outcome) {
      appendRow(card, 'Lifecycle outcome', 'Not recorded this app session', 'unknown');
      appendRow(card, 'Proof lifetime', 'Session only');
      appendRow(card, 'Next action', 'Re-open OmniCOVAS to capture a new startup outcome.');
      return card;
    }

    const stage = String(outcome.stage || 'unknown');
    const stageLabel = STARTUP_STAGE_LABELS[stage] || 'Unknown';
    const state = stage === 'ready_live' ? 'loaded'
      : (stage === 'ready_limited' || stage === 'blocked_local_setup' ? 'not-loaded' : 'unknown');
    appendRow(card, 'Lifecycle outcome', stageLabel, state);
    appendRow(card, 'Bridge', String(outcome.bridge || 'unknown').replace(/_/g, ' '));
    appendRow(card, 'Local sources', String(outcome.local_sources || 'unknown').replace(/_/g, ' '));
    appendRow(card, 'Session hydration', String(outcome.session_state || 'unknown').replace(/_/g, ' '));
    appendRow(card, 'Proof lifetime', 'Session only — not restart-persistent');
    const note = safeEl('p', 'sources-startup-note');
    note.textContent = (
      'This outcome records readiness classes only. It intentionally excludes Commander names, ' +
      'source filenames, file paths, and payload contents.'
    );
    card.appendChild(note);
    return card;
  }

  const LOCAL_PATH_POSTURE_LABELS = Object.freeze({
    present: ['Found', 'loaded'],
    missing: ['Not found', 'not-loaded'],
    unknown: ['Unknown', 'unknown'],
  });

  function buildSessionSection(snapshot) {
    const card = section('Elite Session / Journal Watcher', 'sources-elite-session');
    const activity = snapshot?.session_activity || {};
    const rawState = activity.state || activity.elite_session_state || 'unknown';
    const stateLabel = String(rawState).replace(/_/g, ' ').replace(/^\w/, (c) => c.toUpperCase());
    appendRow(card, 'Elite session', stateLabel, rawState === 'active' ? 'loaded' : 'unknown');
    /* Startup exit criterion 3: an absent Elite folder and an empty one both
       produce zero files, but only one of them is worth waiting on. */
    const [postureLabel, postureState] = LOCAL_PATH_POSTURE_LABELS[
      String(activity.local_path_posture || 'unknown')
    ] || LOCAL_PATH_POSTURE_LABELS.unknown;
    appendRow(card, 'Elite folder', postureLabel, postureState);
    appendRow(card, 'Last journal event', activity.last_journal_event_type || 'Unknown');
    appendRow(card, 'Last journal file', activity.last_journal_file || 'Unknown');
    appendRow(card, 'Last game activity', activity.last_game_activity_at || 'Unknown');
    appendRow(card, 'Journal files scanned',
      Array.isArray(activity.journal_files_scanned) ? String(activity.journal_files_scanned.length) : 'Unknown');
    if (activity.caveat) appendRow(card, 'Caveat', activity.caveat);
    return card;
  }

  function buildEndpointSection(snapshot) {
    const card = section('Local Context Endpoint', 'sources-local-context-endpoint');
    appendRow(card, 'Endpoint', '/intel/local-context/snapshot', snapshot ? 'loaded' : 'not-loaded');
    appendRow(card, 'Generated at', snapshot?.generated_at || 'Unknown');
    appendRow(card, 'NullProvider safe', snapshot?.nullprovider_safe === true ? 'Yes' : 'Unknown');
    return card;
  }

  function buildSourceFilesSection(snapshot, navSnapshot) {
    const card = section('Local Source Files', 'sources-source-files');
    const services = Array.isArray(snapshot?.station_services?.services)
      ? snapshot.station_services.services.map((entry) => String(entry).toLowerCase())
      : [];
    const rows = [
      ['Status.json', isLoaded(snapshot?.system_context) || isLoaded(snapshot?.session_activity)],
      ['Market.json', isLoaded(snapshot?.market_snapshot, Array.isArray(snapshot?.market_snapshot?.items))],
      ['Cargo.json', isLoaded(snapshot?.cargo_hold, Array.isArray(snapshot?.cargo_hold?.inventory))],
      ['Outfitting.json', isLoaded(snapshot?.module_loadout) || services.includes('outfitting')],
      ['Shipyard.json', services.includes('shipyard')],
      ['NavRoute.json', navSnapshot?.active_route?.route_state
        ? navSnapshot.active_route.route_state !== 'not_loaded'
        : false],
      ['ModulesInfo.json', isLoaded(snapshot?.module_loadout, Array.isArray(snapshot?.module_loadout?.modules))],
    ];
    rows.forEach(([label, loaded]) => {
      const [text, state] = statusFor(Boolean(loaded));
      appendRow(card, label, text, state);
    });
    return card;
  }

  function buildMissingSourcesSection(snapshot) {
    const card = section('Missing Sources', 'sources-missing-sources');
    const missing = [
      ...(Array.isArray(snapshot?.missing_sources) ? snapshot.missing_sources : []),
      ...(Array.isArray(snapshot?.wallet_snapshot?.missing_sources) ? snapshot.wallet_snapshot.missing_sources : []),
    ];
    if (missing.length === 0) {
      appendRow(card, 'Reported gaps', 'No missing local sources reported.', 'loaded');
      return card;
    }
    missing.forEach((entry) => appendRow(card, String(entry), 'Missing', 'not-loaded'));
    return card;
  }

  function buildFreshnessSection(snapshot, navSnapshot) {
    const card = section('Freshness', 'sources-freshness');
    appendRow(card, 'Station context', freshness(snapshot?.station_context));
    appendRow(card, 'System context', freshness(snapshot?.system_context));
    appendRow(card, 'Market snapshot', freshness(snapshot?.market_snapshot));
    appendRow(card, 'Cargo hold', freshness(snapshot?.cargo_hold));
    appendRow(card, 'Module loadout', freshness(snapshot?.module_loadout));
    appendRow(card, 'Nav route', freshnessVocabulary?.freshnessLabel({
      freshness: navSnapshot?.active_route?.freshness_label || 'not_loaded',
      source: navSnapshot?.active_route?.source_id,
      truthClass: navSnapshot?.active_route?.truth_class,
    }) || 'Unknown');
    return card;
  }

  function buildArdentSection(ardentSource) {
    const card = section('Ardent Imported Dataset', 'sources-ardent-dataset');
    const meta = ardentSource?.metadata || {};

    appendRow(card, 'Provider', ardentSource?.display_name || 'Ardent imported dataset');
    appendRow(card, 'Source class', meta.source_class || 'LOCAL_EXTERNAL_DATASET');
    appendRow(card, 'Provider status', ardentSource?.state || 'disabled', 'not-loaded');
    appendRow(card, 'Dataset status', meta.dataset_status || 'dataset_missing', 'not-loaded');
    appendRow(card, 'Implementation posture',
      meta.implementation_posture_composite || meta.implementation_status || 'fixture_only');

    const designAvail = meta.manual_import_design_available === true;
    const execAvail = meta.manual_import_execution_available === true;
    appendRow(card, 'Manual import design', designAvail ? 'Available (not yet executable)' : 'Not available');
    appendRow(card, 'Manual import execution', execAvail ? 'Available' : 'Unavailable — blocked', execAvail ? 'loaded' : 'not-loaded');

    appendRow(card, 'HTTPS API', meta.https_api_enabled ? 'Enabled' : 'Disabled', 'not-loaded');
    appendRow(card, 'Downloader', meta.downloader_enabled ? 'Enabled' : 'Disabled', 'not-loaded');
    appendRow(card, 'Query engine', meta.query_engine_enabled ? 'Enabled' : 'Disabled', 'not-loaded');
    appendRow(card, 'Credentials required', 'None at this stage');
    appendRow(card, 'Storage root contract', meta.dataset_root_contract || '%APPDATA%\\OmniCOVAS\\ardent (planned — not created)');
    appendRow(card, 'Outbound calls', 'None — no network path exists for this provider');

    const note = safeEl('p', 'sources-ardent-note');
    note.textContent = (
      'Community-observed data. Not live. Not guaranteed complete. ' +
      'Not official Frontier Developments data. ' +
      'Local Journal, Status.json, and companion JSON always take precedence. ' +
      'Future download or import requires explicit Commander action and compliance gate.'
    );
    card.appendChild(note);

    const gate = safeEl('p', 'sources-ardent-gate');
    gate.textContent = 'Next required gate: maintainer/license confirmation open. Compliance review required before real import.';
    card.appendChild(gate);

    return card;
  }

  function buildProofSection(snapshot) {
    const card = section('Proof / Caveats', 'sources-proof-caveats');
    const sources = [
      ['Session source file', snapshot?.session_activity?.last_journal_file],
      ['Station source file', snapshot?.station_context?.source_file],
      ['System source file', snapshot?.system_context?.source_file],
      ['Market source file', snapshot?.market_snapshot?.source_file],
      ['Cargo source file', snapshot?.cargo_hold?.source_file],
      ['Module source file', snapshot?.module_loadout?.source_file],
    ];
    sources.forEach(([label, value]) => appendRow(card, label, value || 'Unknown'));
    [
      snapshot?.station_context?.caveat,
      snapshot?.system_context?.caveat,
      snapshot?.market_snapshot?.caveat,
      snapshot?.cargo_hold?.caveat,
      snapshot?.module_loadout?.caveat,
    ].filter(Boolean).forEach((text, index) => appendRow(card, `Caveat ${index + 1}`, text));
    return card;
  }

  function buildProviderPostureSection(sourceHealth) {
    const card = section('External Provider Posture', 'sources-provider-posture');
    const sources = Array.isArray(sourceHealth?.sources) ? sourceHealth.sources : [];
    const external = sources.filter((s) => s && s.is_local === false);
    const enabledCount = sourceHealth?.enabled_count ?? 0;

    appendRow(
      card,
      'External providers enabled',
      enabledCount === 0 ? 'None — no external provider enabled' : String(enabledCount),
      'not-loaded',
    );
    appendRow(card, 'Consent default', 'Off for every external provider', 'not-loaded');
    appendRow(card, 'Outbound flows', 'None active by default', 'not-loaded');

    if (external.length === 0) {
      appendRow(card, 'Provider registry', 'No external providers registered', 'unknown');
    } else {
      external.forEach((s) => {
        const stateRaw = String(s.state || 'unknown');
        const stateLabel = stateRaw.replace(/_/g, ' ').replace(/^\w/, (c) => c.toUpperCase());
        const authNote = s.requires_auth ? ' · requires authorization' : '';
        appendRow(card, s.display_name || s.source_id || 'Unknown provider', `${stateLabel}${authNote}`, 'not-loaded');
      });
    }

    const note = safeEl('p', 'sources-provider-note');
    note.textContent = (
      'External community data providers are disabled or require authorization by default. ' +
      'Enabling any provider is a future Commander-approved, per-provider step routed through the ' +
      'Confirmation Gate and recorded in the Activity Log. OmniCOVAS is not affiliated with or ' +
      'endorsed by Frontier Developments or any community provider. Local Journal, Status.json, ' +
      'and companion JSON always take precedence.'
    );
    card.appendChild(note);

    const redaction = safeEl('p', 'sources-provider-redaction');
    redaction.textContent = (
      'Privacy: OmniCOVAS is local-first; no telemetry is sent to maintainers. The Activity Log ' +
      'redacts raw commander payloads, credentials, and tokens. The DPAPI vault stores key names ' +
      'and status only, never credential values.'
    );
    card.appendChild(redaction);

    return card;
  }

  async function render() {
    const root = getRoot();
    if (!root) return;
    root.replaceChildren(safeEl('p', 'sources-loading', 'Loading source diagnostics...'));

    const [snapshot, navSnapshot, sourceHealth] = await Promise.all([
      fetchJson('/intel/local-context/snapshot'),
      fetchJson('/navigation/snapshot'),
      fetchJson('/source/health'),
      freshnessVocabularyPromise,
    ]);

    const ardentSource = Array.isArray(sourceHealth?.sources)
      ? sourceHealth.sources.find((s) => s.source_id === 'ardent') || null
      : null;

    const layout = safeEl('section', 'sources-diagnostics-grid');
    layout.setAttribute('aria-label', 'Sources and diagnostics summary');
    layout.appendChild(buildBridgeSection());
    layout.appendChild(buildStartupOutcomeSection());
    layout.appendChild(buildSessionSection(snapshot));
    layout.appendChild(buildEndpointSection(snapshot));
    layout.appendChild(buildSourceFilesSection(snapshot, navSnapshot));
    layout.appendChild(buildMissingSourcesSection(snapshot));
    layout.appendChild(buildFreshnessSection(snapshot, navSnapshot));
    layout.appendChild(buildProofSection(snapshot));
    layout.appendChild(buildProviderPostureSection(sourceHealth));
    layout.appendChild(buildArdentSection(ardentSource));

    root.replaceChildren(layout);
  }

  function shouldRenderForHash() {
    return window.location.hash === '#/sources' || window.location.hash === '#/diagnostics';
  }

  function init() {
    if (shouldRenderForHash()) render();

    if (window.OmniEvents) {
      window.OmniEvents.addEventListener('bridge-connected', () => render());
      window.OmniEvents.addEventListener('elite-session-state', () => {
        if (getRoot()?.children.length) render();
      });
      window.OmniEvents.addEventListener('systems-surface-mounted', (ev) => {
        if (ev?.detail?.topic === 'sources') render();
      });
    }

    window.addEventListener('hashchange', () => {
      if (shouldRenderForHash()) render();
    });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }

  globalThis.__sourcesDiagnosticsExports = {
    renderSourcesDiagnostics: render,
    buildStartupOutcomeSection,
  };
})();
