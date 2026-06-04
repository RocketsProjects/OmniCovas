/**
 * OmniCOVAS Operations — Workspace Surface (UI v3 target rebuild).
 *
 * Authority: authority_files/documents/02_ui_ux_authority/OmniCOVAS_UI_UX_Master_Blueprint_v2_0_Human_Reference.md §9.2, §11
 *
 * PB-UIV3-03: reshapes the Operations workspace into the UI v3 target layout:
 *   compact breadcrumb/hero header → mode selector bar → mode-specific body.
 *
 * Station mode: two-column card layout (Current Station card / right column
 *   with Cargo, Next Actions, Recent Activity cards).
 *
 * Non-station modes: all existing content preserved (watch strip, context
 *   spine, primary action, supports, quick tools, local context, detail,
 *   proof) — wrapped in the new v3 header + mode bar chrome.
 *
 * Operation modes: Mining, Trading, Combat, Exploration, Travel, Station,
 *   Squadron, Idle. No mode defaults to Station unless explicit state says so.
 *
 * Local-first. Reads:
 *   /pillar1/ship-state, /pillar1/cargo, /pillar1/heat, /pillar1/modules/summary
 *   /navigation/snapshot, /combat/snapshot
 *   /intel/local-context/snapshot
 *
 * Safe rendering: createElement + textContent only (ADR 0003).
 * Decision A LOCKED: first tab is Dashboard, never Pilot.
 */

(function () {
  'use strict';

  const STORAGE_KEY = 'omnicovas.manualOperation';

  /* Phase 9 workspace modes are session-only. writeManualOperation is never
     called for these modes; they cannot be auto-reopened from storage. */
  const PHASE9_SESSION_ONLY_MODES = new Set(['bgs', 'powerplay']);

  const PRIMITIVES_URL = '../components/command-primitives.js';
  const COMMANDER_VM_URL = '../view-models/commander-context.js';
  const WORKSPACE_VM_URL = '../view-models/operations-workspaces.js';
  const LOCAL_CONTEXT_VM_URL = '../view-models/local-context.js';
  const LOCAL_CONTEXT_SURFACES_URL = '../components/local-context-surfaces.js';

  let _primitives = null;
  let _commanderVM = null;
  let _workspaceVM = null;
  let _localContextVM = null;
  let _localSurfaces = null;

  const primitivesPromise = import(PRIMITIVES_URL)
    .then((m) => { _primitives = m; return m; })
    .catch((err) => { console.error('[operations] Failed to load command primitives:', err); return null; });

  const commanderPromise = import(COMMANDER_VM_URL)
    .then((m) => { _commanderVM = m; return m; })
    .catch((err) => { console.error('[operations] Failed to load commander VM:', err); return null; });

  const workspacePromise = import(WORKSPACE_VM_URL)
    .then((m) => { _workspaceVM = m; return m; })
    .catch((err) => { console.error('[operations] Failed to load workspace VM:', err); return null; });

  const localContextPromise = import(LOCAL_CONTEXT_VM_URL)
    .then((m) => { _localContextVM = m; return m; })
    .catch((err) => { console.error('[operations] Failed to load local context VM:', err); return null; });

  const localSurfacesPromise = import(LOCAL_CONTEXT_SURFACES_URL)
    .then((m) => { _localSurfaces = m; return m; })
    .catch((err) => { console.error('[operations] Failed to load local context surfaces:', err); return null; });

  function getRoot() {
    return document.getElementById('operations-root');
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

  /* Smoke R3: Operations default is selector-only. The Commander explicitly
     directed that legacy localStorage values must NOT reopen old operations
     automatically — only an explicit current-session click opens an
     operation. We never read manualOperation back from storage; on init we
     just clear any stale value so prior sessions cannot influence this one. */
  function readManualOperation() {
    try {
      window.localStorage?.removeItem(STORAGE_KEY);
    } catch { /* localStorage unavailable */ }
    return null;
  }

  function writeManualOperation(op) {
    // Phase 9 modes (bgs, powerplay) are session-only: never write to storage.
    if (PHASE9_SESSION_ONLY_MODES.has(op)) return;
    try {
      if (op === null || op === 'idle') window.sessionStorage?.removeItem(STORAGE_KEY);
      else window.sessionStorage?.setItem(STORAGE_KEY, op);
    } catch { /* ignore */ }
  }

  const inputs = {
    state: null,
    heat: null,
    cargo: null,
    mods: null,
    navSnap: null,
    combat: null,
    localContext: null,
  };

  let _manualOperation = readManualOperation();

  function safeEl(tag, className, text) {
    const el = document.createElement(tag);
    if (className) el.className = className;
    if (text !== undefined && text !== null) el.textContent = String(text);
    return el;
  }

  /* ──────────────────────────────────────────────
   * UI v3 Operations header helpers
   * ────────────────────────────────────────────── */

  /* Returns H1 text for the operation based on real local state only.
     Amendment 5: no auto-selection of Station; honest fallback per mode. */
  function deriveV3HeroTitle(operation, inputsObj) {
    const st = inputsObj?.state || null;
    const lc = inputsObj?.localContext || null;
    const nav = inputsObj?.navSnap || null;
    const cargo = inputsObj?.cargo || null;

    const stationName = lc?.stationBrief?.stationName || st?.current_station || null;
    const isDocked = st?.is_docked === true || lc?.stationBrief?.isDocked === true;
    const destination = nav?.active_route?.destination || null;
    const currentSystem = st?.current_system || lc?.systemBrief?.systemName || null;
    const cargoItems = Array.isArray(cargo?.inventory) ? cargo.inventory : [];
    const topItem = cargoItems[0]?.display || cargoItems[0]?.name_localised || cargoItems[0]?.name || null;

    switch (operation) {
      case 'station':
        if (isDocked && stationName) return `Docked at ${stationName}.`;
        if (isDocked) return 'Docked.';
        return 'Awaiting dock.';
      case 'mining':
        if (topItem) return `Mining ${topItem}.`;
        return 'Mining underway.';
      case 'trading':
        if (isDocked && stationName) return `Trading from ${stationName}.`;
        return 'Trading underway.';
      case 'combat':
        return 'Combat operations.';
      case 'exploration':
        if (currentSystem) return `Exploration in ${currentSystem}.`;
        if (destination) return `Plotted to ${destination}.`;
        return 'Exploration underway.';
      case 'travel':
        if (destination) return `Travelling to ${destination}.`;
        return 'Travelling.';
      case 'squadron':
        return 'Squadron coordination.';
      case 'bgs':
        return 'BGS campaign.';
      case 'powerplay':
        return 'Powerplay campaign.';
      default:
        return 'Operations';
    }
  }

  /* Returns compact one-line subtitle for the given operation.
     Amendment 3: no large hero slab — station card is the visual anchor. */
  function deriveV3Subtitle(operation, inputsObj) {
    const lc = inputsObj?.localContext || null;

    switch (operation) {
      case 'station': {
        const parts = [];
        const stationType = lc?.stationBrief?.stationType;
        const economy = lc?.stationBrief?.economySummary;
        if (stationType && stationType !== 'Unknown') parts.push(`${stationType} station`);
        if (economy && economy !== 'Unknown') parts.push(`${economy} economy`);
        const prefix = parts.join(', ');
        return prefix
          ? `${prefix}. Switch operation below, or use the quick links to dive deeper.`
          : 'Switch operation below, or use the quick links to dive deeper.';
      }
      case 'mining':
        return 'Track cargo, threat status, and market access from local state.';
      case 'trading':
        return 'Track cargo and market access from local state.';
      case 'combat':
        return 'Monitor threat status and ship readiness from local state.';
      case 'exploration':
        return 'Track discovery context and route from local state.';
      case 'travel':
        return 'Monitor route and safety from local state.';
      case 'squadron':
        return 'Local coordination only. No outbound transport in this build.';
      case 'bgs':
        return 'Local BGS campaign objectives. Intel owns facts. No outbound calls.';
      case 'powerplay':
        return 'Local Powerplay campaign objectives. Intel owns facts. No outbound calls.';
      default:
        return 'Manage active tasks, readiness, and next actions from local state.';
    }
  }

  /* Compact v3 header zone: breadcrumb + h1#operations-title + subtitle + alert pill.
     Amendment 3: the header stays compact; the station card is the visual anchor. */
  function buildOpsV3Header(operation, ctx, inputsObj) {
    const header = safeEl('div', 'ops-v3-header');

    /* Compact breadcrumb (mono, small, dim) */
    const breadcrumb = safeEl('p', 'ops-v3-breadcrumb');
    breadcrumb.appendChild(safeEl('span', 'ops-v3-breadcrumb-root', 'OPERATIONS'));
    const opName = _commanderVM?.operationLabel?.(operation);
    if (opName) {
      const sep = safeEl('span', 'ops-v3-breadcrumb-sep', '›');
      sep.setAttribute('aria-hidden', 'true');
      breadcrumb.appendChild(sep);
      breadcrumb.appendChild(safeEl('span', 'ops-v3-breadcrumb-leaf', opName.toUpperCase()));
    }
    header.appendChild(breadcrumb);

    /* Hero row: title left, alert pill right */
    const heroRow = safeEl('div', 'ops-v3-hero-row');

    const heroLeft = safeEl('div', 'ops-v3-hero-left');
    const h1 = safeEl('h1', 'ops-v3-title', deriveV3HeroTitle(operation, inputsObj));
    h1.id = 'operations-title';
    heroLeft.appendChild(h1);
    heroLeft.appendChild(safeEl('p', 'ops-v3-subtitle', deriveV3Subtitle(operation, inputsObj)));
    heroRow.appendChild(heroLeft);

    /* Alert pill — uses uiv3-status tokens (Amendment 2) */
    const interrupts = Array.isArray(ctx?.interrupts) ? ctx.interrupts : [];
    const pillMod = interrupts.length > 0 ? ' ops-v3-alert-pill--warn' : ' ops-v3-alert-pill--clear';
    const pill = safeEl('div', `ops-v3-alert-pill${pillMod}`);
    pill.textContent = interrupts.length > 0
      ? `${interrupts.length} ALERT${interrupts.length !== 1 ? 'S' : ''}`
      : '0 ALERTS \xB7 NOTHING URGENT';
    heroRow.appendChild(pill);

    header.appendChild(heroRow);
    return header;
  }

  function deriveSinceLabel(operation) {
    const labels = {
      station: 'SINCE LAST DOCK EVENT',
      mining: 'SINCE LAST CARGO EVENT',
      trading: 'SINCE LAST CARGO EVENT',
      combat: 'SINCE LAST COMBAT EVENT',
      exploration: 'SINCE LAST SCAN EVENT',
      travel: 'SINCE LAST JUMP EVENT',
      squadron: 'SINCE LAST SESSION EVENT',
    };
    return labels[operation] || '— SINCE LAST EVENT';
  }

  /* Mode selector bar: OPERATION label + 8 chips (reused createOperationSelector) + since label. */
  function buildOpsV3ModeBar(currentOperation, onSelect) {
    const bar = safeEl('div', 'ops-v3-mode-bar');
    bar.appendChild(safeEl('span', 'ops-v3-mode-label', 'OPERATION'));

    if (_primitives && _commanderVM) {
      const { createOperationSelector } = _primitives;
      const { PRIMARY_OPERATIONS, operationLabel } = _commanderVM;
      bar.appendChild(createOperationSelector({
        operations: PRIMARY_OPERATIONS.map(op => ({ id: op, label: operationLabel(op) })),
        current: currentOperation,
        onSelect,
      }));
    }

    bar.appendChild(safeEl('span', 'ops-v3-mode-since', deriveSinceLabel(currentOperation)));
    return bar;
  }

  /* ──────────────────────────────────────────────
   * Station mode body helpers
   * ────────────────────────────────────────────── */

  /* Two-column ops body: large station card (left) + right column (stacked cards). */
  function buildOpsV3StationBody(ctx, inputsObj) {
    const wrap = safeEl('div', 'ops-v3-station-body');

    /* PB-PHASE10-SUPER-03 #5: Station is not a true operation. It is shown here
       as a temporary docked-context surface; full station / local intelligence
       is planned to move to Intel (which already owns a Station briefing). This
       note demotes it honestly until that migration lands. */
    const demote = safeEl('p', 'ops-v3-station-demote-note',
      'Temporary docked context. Station and local intelligence will move to Intel in a future update.');
    wrap.appendChild(demote);

    const grid = safeEl('div', 'ops-v3-body-grid');
    grid.setAttribute('aria-label', 'Station operations workspace');
    grid.appendChild(buildOpsV3StationCard(inputsObj));

    const rightCol = safeEl('div', 'ops-v3-right-col');
    rightCol.appendChild(buildOpsV3CargoCard(inputsObj));
    rightCol.appendChild(buildOpsV3NextActionsCard());
    rightCol.appendChild(buildOpsV3RecentActivityCard(inputsObj));
    grid.appendChild(rightCol);

    wrap.appendChild(grid);
    return wrap;
  }

  /* Current Station card (~60% width). All fields from real local state or honest fallback. */
  function buildOpsV3StationCard(inputsObj) {
    const sb = inputsObj.localContext?.stationBrief || null;
    const st = inputsObj.state || null;

    const card = safeEl('article', 'ops-v3-station-card');
    card.setAttribute('aria-label', 'Current station');

    /* Eyebrow row */
    const eyebrowRow = safeEl('div', 'ops-v3-card-eyebrow-row');
    eyebrowRow.appendChild(safeEl('span', 'ops-v3-card-eyebrow', 'CURRENT STATION'));
    const rawTs = sb?.proof?.timestamp || null;
    let displayTs = '—';
    if (rawTs) {
      const timePart = rawTs.replace(/^[^T]+T/, '').replace(/\.\d+Z?$/, '');
      displayTs = timePart.slice(0, 5) + 'Z';
    }
    eyebrowRow.appendChild(safeEl('span', 'ops-v3-card-timestamp', `SNAPSHOT \xB7 ${displayTs}`));
    card.appendChild(eyebrowRow);

    /* Station name */
    const stationName = sb?.stationName || st?.current_station || 'Unknown station';
    card.appendChild(safeEl('h2', 'ops-v3-station-name', stationName));

    /* Description composed from real fields only — never hardcoded screenshot values */
    const descParts = [];
    if (sb?.stationType && sb.stationType !== 'Unknown') descParts.push(sb.stationType);
    if (sb?.economySummary && sb.economySummary !== 'Unknown') descParts.push(`${sb.economySummary} economy`);
    if (sb?.factionSummary && sb.factionSummary !== 'Unknown') descParts.push(sb.factionSummary);
    card.appendChild(safeEl('p', 'ops-v3-station-desc',
      descParts.length ? descParts.join(', ') + '.' : 'Station context not yet loaded.'));

    /* Fact grid — 6 self-contained visual units per RUNTIME_UI_REPAIR_DOCTRINE */
    const factGrid = safeEl('div', 'ops-v3-fact-grid');
    factGrid.setAttribute('role', 'list');

    function detailVal(rowLabel) {
      return sb?.detailRows?.find(r => r.label === rowLabel)?.value || '—';
    }

    const isDocked = st?.is_docked === true || sb?.isDocked === true;
    const dockingText = sb?.dockedLabel || (isDocked ? 'Docked' : '—');

    const facts = [
      { label: 'TYPE',              value: (sb?.stationType && sb.stationType !== 'Unknown') ? sb.stationType : '—' },
      { label: 'DISTANCE FROM STAR', value: detailVal('Distance from star') },
      { label: 'ECONOMY',           value: (sb?.economySummary && sb.economySummary !== 'Unknown') ? sb.economySummary : '—' },
      { label: 'DOCKING',           value: dockingText, ok: isDocked },
      { label: 'GOVERNMENT',        value: detailVal('Government') },
      { label: 'FACTION',           value: (sb?.factionSummary && sb.factionSummary !== 'Unknown') ? sb.factionSummary : '—' },
    ];

    facts.forEach(f => {
      const unit = safeEl('div', 'ops-v3-fact-unit');
      unit.setAttribute('role', 'listitem');
      unit.appendChild(safeEl('span', 'ops-v3-fact-label', f.label));
      unit.appendChild(safeEl('span', `ops-v3-fact-value${f.ok ? ' ops-v3-fact-value--ok' : ''}`, f.value));
      factGrid.appendChild(unit);
    });
    card.appendChild(factGrid);

    /* Services chip cloud */
    const services = Array.isArray(sb?.services) ? sb.services : [];
    if (services.length > 0) {
      card.appendChild(safeEl('p', 'ops-v3-services-head', 'SERVICES'));
      const cloud = safeEl('div', 'ops-v3-services-cloud');

      const CHIP_LIMIT = 11;
      services.slice(0, CHIP_LIMIT).forEach(svc => {
        cloud.appendChild(safeEl('span', 'ops-v3-service-chip', svc.label));
      });

      const overflow = services.slice(CHIP_LIMIT);
      if (overflow.length > 0) {
        const overflowWrap = safeEl('div', 'ops-v3-services-overflow');
        overflow.forEach(svc => {
          overflowWrap.appendChild(safeEl('span', 'ops-v3-service-chip', svc.label));
        });
        const moreChip = safeEl('button', 'ops-v3-service-chip ops-v3-service-chip--more',
          `+${overflow.length} more`);
        moreChip.setAttribute('type', 'button');
        moreChip.addEventListener('click', () => overflowWrap.classList.toggle('is-open'));
        cloud.appendChild(moreChip);
        cloud.appendChild(overflowWrap);
      }
      card.appendChild(cloud);
    }

    /* Footer: freshness summary | DETAILS | Open station brief (→ Intel) */
    const footer = safeEl('div', 'ops-v3-card-footer');

    const freshnessItems = [];
    if (sb?.marketAvailable) freshnessItems.push('Market fresh');
    if (sb?.outfittingAvailable) freshnessItems.push('Outfitting observed');
    if (sb?.shipyardAvailable) freshnessItems.push('Shipyard observed');
    footer.appendChild(safeEl('div', 'ops-v3-freshness',
      freshnessItems.length ? freshnessItems.join(' \xB7 ') : 'No freshness data'));

    const detailsBtn = safeEl('button', 'ops-v3-details-link', 'DETAILS');
    detailsBtn.setAttribute('type', 'button');
    detailsBtn.addEventListener('click', () => {
      const proofEl = card.closest('.operations-workspace')?.querySelector('.proof-toggle');
      if (proofEl) proofEl.setAttribute('open', '');
    });
    footer.appendChild(detailsBtn);

    /* Intel owns Station Brief — this is a link, not an embedded panel */
    const briefLink = safeEl('a', 'ops-v3-station-brief-btn', 'Open station brief ›');
    briefLink.setAttribute('href', '#/intel');
    footer.appendChild(briefLink);

    card.appendChild(footer);
    return card;
  }

  /* Cargo card (right column, top). */
  function buildOpsV3CargoCard(inputsObj) {
    const card = safeEl('article', 'ops-v3-cargo-card');
    card.setAttribute('aria-label', 'Cargo');
    card.appendChild(safeEl('p', 'ops-v3-card-title', 'CARGO'));

    const st = inputsObj.state || null;
    const cargo = inputsObj.cargo || null;
    const cargoItems = Array.isArray(cargo?.inventory) ? cargo.inventory : [];
    const count = st?.cargo_count ?? cargoItems.reduce((s, i) => s + (i?.count ?? 0), 0);
    const cap = st?.cargo_capacity ?? 0;

    if (cargoItems.length > 0) {
      card.appendChild(safeEl('p', 'ops-v3-card-body', `${count} / ${cap} t`));
      const first = cargoItems[0];
      const topLabel = first?.display || first?.name_localised || first?.name || 'Cargo on board';
      card.appendChild(safeEl('p', 'ops-v3-card-sub', topLabel));
    } else if (cap > 0) {
      card.appendChild(safeEl('p', 'ops-v3-card-body', 'Hold is empty.'));
      card.appendChild(safeEl('p', 'ops-v3-card-sub', `${cap} t free against capacity. Ready to load at this station.`));
    } else {
      card.appendChild(safeEl('p', 'ops-v3-card-body', 'No cargo detected.'));
      card.appendChild(safeEl('p', 'ops-v3-card-sub', '—'));
    }

    const openBtn = safeEl('button', 'ops-v3-card-link', 'Open cargo ›');
    openBtn.setAttribute('type', 'button');
    openBtn.addEventListener('click', () => {
      _manualOperation = 'trading';
      writeManualOperation('trading');
      renderWorkspace('trading');
    });
    card.appendChild(openBtn);

    return card;
  }

  /* Next Actions card (right column, middle). Amendment 4: plain route labels, no ownership copy. */
  function buildOpsV3NextActionsCard() {
    const card = safeEl('article', 'ops-v3-next-actions-card');
    card.setAttribute('aria-label', 'Next actions');
    card.appendChild(safeEl('p', 'ops-v3-card-title', 'NEXT ACTIONS'));

    const actions = [
      { label: 'Commodity Search', route: '#/intel',        chip: 'INTEL' },
      { label: 'Module Search',    route: '#/intel',        chip: 'INTEL' },
      { label: 'Plot route',       route: '#/navigation',   chip: 'NAVIGATION' },
      { label: 'Engineering plans', route: '#/engineering', chip: 'ENGINEERING' },
    ];

    actions.forEach(a => {
      const row = safeEl('div', 'ops-v3-next-action-row');
      const link = safeEl('a', 'ops-v3-next-action-label', a.label);
      link.setAttribute('href', a.route);
      row.appendChild(link);
      const chip = safeEl('a', 'ops-v3-route-chip', a.chip);
      chip.setAttribute('href', a.route);
      row.appendChild(chip);
      card.appendChild(row);
    });

    return card;
  }

  /* Recent Activity card (right column, bottom). Honest fallback — Activity Log owns proof. */
  function buildOpsV3RecentActivityCard(inputsObj) {
    const card = safeEl('article', 'ops-v3-recent-activity-card');
    card.setAttribute('aria-label', 'Recent activity');
    card.appendChild(safeEl('p', 'ops-v3-card-title', 'RECENT ACTIVITY'));

    /* Operations does not have a direct event-history feed in current inputs;
       honest empty state — Activity Log is the proof owner. */
    card.appendChild(safeEl('p', 'ops-v3-card-body', 'No recent activity.'));
    card.appendChild(safeEl('p', 'ops-v3-card-sub', 'Activity is captured in the Activity Log.'));

    const logLink = safeEl('a', 'ops-v3-card-footer-link', 'OPEN LOG ›');
    logLink.setAttribute('href', '#/activity-log');
    card.appendChild(logLink);

    return card;
  }

  /* ──────────────────────────────────────────────
   * Idle selector (Correction #7 — preserved exactly, now uses v3 chrome)
   * ────────────────────────────────────────────── */
  function renderIdleSelector() {
    const root = getRoot();
    if (!root || !_primitives || !_commanderVM) return;
    const { createOperationSelector } = _primitives;
    const { PRIMARY_OPERATIONS, operationLabel } = _commanderVM;

    const wrap = safeEl('section', 'operations-workspace operations-workspace--idle');
    wrap.setAttribute('aria-labelledby', 'operations-title');
    wrap.setAttribute('data-operation', 'idle');

    /* Compact v3 header — no hero slab (Amendment 3), honest idle copy (Amendment 5) */
    const hdr = safeEl('div', 'ops-v3-header');

    const breadcrumb = safeEl('p', 'ops-v3-breadcrumb');
    breadcrumb.appendChild(safeEl('span', 'ops-v3-breadcrumb-root', 'OPERATIONS'));
    hdr.appendChild(breadcrumb);

    const h1 = safeEl('h1', 'ops-v3-title', 'Operations');
    h1.id = 'operations-title';
    hdr.appendChild(h1);

    hdr.appendChild(safeEl('p', 'ops-v3-subtitle',
      'No active operation. Select an operation to focus the command deck.'));
    wrap.appendChild(hdr);

    /* Mode bar — wraps the operation selector (no watch-strip, no support-card, no quick-tools) */
    const bar = safeEl('div', 'ops-v3-mode-bar');
    bar.appendChild(safeEl('span', 'ops-v3-mode-label', 'OPERATION'));
    bar.appendChild(createOperationSelector({
      operations: PRIMARY_OPERATIONS.map(op => ({ id: op, label: operationLabel(op) })),
      current: null,
      onSelect: (id) => {
        _manualOperation = id;
        writeManualOperation(id);
        renderWorkspace(id);
      },
    }));
    wrap.appendChild(bar);

    root.replaceChildren(wrap);
    /* PB09-08: apply route-transfer arrival banner */
    if (typeof window.Shell?.applyRouteTransferArrival === 'function') {
      window.Shell.applyRouteTransferArrival('/operations', root);
    }
  }

  /* ──────────────────────────────────────────────
   * Main workspace renderer (UI v3 restructured)
   * ────────────────────────────────────────────── */
  function renderWorkspace(operation) {
    if (operation === null || operation === undefined || operation === 'idle') {
      renderIdleSelector();
      return;
    }

    const root = getRoot();
    if (!root || !_primitives || !_commanderVM || !_workspaceVM) return;

    /* Phase 9 campaign modes: async fetch then render. No localStorage persistence.
       Selector-first idle contract preserved — renders only on explicit selection. */
    if (PHASE9_SESSION_ONLY_MODES.has(operation)) {
      // Show loading placeholder immediately (synchronous)
      const placeholder = safeEl('section', 'operations-workspace operations-workspace--phase9-loading');
      placeholder.setAttribute('aria-labelledby', 'operations-title');
      const ph1 = safeEl('h1', 'ops-v3-title', operation === 'bgs' ? 'BGS Campaign' : 'Powerplay Campaign');
      ph1.id = 'operations-title';
      placeholder.appendChild(ph1);
      placeholder.appendChild(safeEl('p', 'ops-phase9-loading', 'Loading campaign…'));
      root.replaceChildren(placeholder);
      // PB09-08: read inbound route-transfer intent to optionally fetch a specific campaign by id
      const _inboundIntent = typeof window.Shell?.getRouteTransferIntent === 'function'
        ? window.Shell.getRouteTransferIntent('/operations')
        : null;
      const _requestedCampaignId = _inboundIntent?.targetEntityId || null;
      // Async: fetch and render
      fetchActivePhase9Campaign(operation, _requestedCampaignId).then(campaign => {
        if (getRoot() !== null && _manualOperation === operation) {
          renderPhase9CampaignWorkspace(getRoot(), operation, campaign);
        }
      });
      return;
    }

    const {
      createCommandContextSpine,
      createWatchStrip,
      createInterruptBanner,
      createSupportCard,
      createPrimaryActionBlock,
      createQuickToolStrip,
      createDetailDrawer,
      createProofToggle,
    } = _primitives;

    const { deriveCommanderContext } = _commanderVM;
    const { deriveWorkspace } = _workspaceVM;

    const ctx = deriveCommanderContext(inputs, operation);
    const ws  = deriveWorkspace(ctx.primaryOperation, inputs);

    const wrap = safeEl('section', 'operations-workspace');
    wrap.setAttribute('aria-labelledby', 'operations-title');
    wrap.setAttribute('data-operation', ctx.primaryOperation);

    /* 1. Interrupt banner (elevated over all content).
       ALERT_OWNERSHIP_01: critical alerts (e.g. fuel critical) are shared
       attention state, not owned by Operations. The banner shows them but no
       longer changes the selected operation; its detail affordance routes to
       the Activity Log (the proof layer), never a fabricated remediation. */
    const banner = createInterruptBanner(ctx.interrupts, {
      onResolveAction: { label: 'Open Activity Log', href: '#/activity-log' },
    });
    if (banner) wrap.appendChild(banner);

    /* 2. Compact v3 header (breadcrumb + h1#operations-title + subtitle + alert pill) */
    wrap.appendChild(buildOpsV3Header(ctx.primaryOperation, ctx, inputs));

    /* 3. Mode selector bar (OPERATION label + 8 chips + since label) */
    const onSelect = (id) => {
      _manualOperation = id;
      writeManualOperation(id);
      renderWorkspace(id);
    };
    wrap.appendChild(buildOpsV3ModeBar(ctx.primaryOperation, onSelect));

    /* 4. Mode-specific body */
    if (ctx.primaryOperation === 'station') {
      /* Station mode: two-column card layout */
      wrap.appendChild(buildOpsV3StationBody(ctx, inputs));

      /* Watch strip preserved in secondary position */
      wrap.appendChild(createWatchStrip(ctx.watch));

      /* Local context surfaces for station mode (existing behavior preserved) */
      const localWorkspace = buildLocalContextWorkspace('station');
      if (localWorkspace) wrap.appendChild(localWorkspace);

    } else {
      /* Non-station modes: all existing content preserved for test continuity */
      wrap.appendChild(createWatchStrip(ctx.watch));
      wrap.appendChild(createCommandContextSpine(ctx.contextSpine));

      const primaryAction = createPrimaryActionBlock(
        ws.action ? { label: ws.action.label, route: ws.action.route } : null);
      if (primaryAction) wrap.appendChild(primaryAction);

      const supportsRegion = safeEl('section', 'operations-supports');
      supportsRegion.setAttribute('role', 'region');
      supportsRegion.setAttribute('aria-label', 'Support systems');
      ws.supports.forEach(s => supportsRegion.appendChild(createSupportCard(s)));
      wrap.appendChild(supportsRegion);

      wrap.appendChild(createQuickToolStrip(ws.quickTools));

      const localWorkspace = buildLocalContextWorkspace(ctx.primaryOperation);
      if (localWorkspace) wrap.appendChild(localWorkspace);
    }

    /* 5. Detail drawer (collapsed by default) */
    wrap.appendChild(createDetailDrawer({
      summary: 'Operation detail',
      content: buildOperationDetail(ctx.primaryOperation),
    }));

    /* 6. Proof toggle (source posture, collapsed by default, never a default wall) */
    wrap.appendChild(createProofToggle(buildProofContent(ctx.primaryOperation), 'Sources & evidence'));

    /* 7. Back to selector */
    const footer = safeEl('footer', 'operations-workspace-footer');
    const back = safeEl('button', 'operations-selector-back', 'Back to Operations selector');
    back.type = 'button';
    back.addEventListener('click', () => {
      _manualOperation = null;
      writeManualOperation(null);
      renderIdleSelector();
    });
    footer.appendChild(back);
    wrap.appendChild(footer);

    root.replaceChildren(wrap);
    /* PB09-08: apply route-transfer arrival banner */
    if (typeof window.Shell?.applyRouteTransferArrival === 'function') {
      window.Shell.applyRouteTransferArrival('/operations', root);
    }
  }

  /* ──────────────────────────────────────────────
   * Phase 9 campaign workspace renderers (PB09-03)
   * ADR 0003: createElement + textContent only. No innerHTML.
   * No localStorage auto-reopen (PHASE9_SESSION_ONLY_MODES guard above).
   * Selector-first idle contract: these render only when mode is explicitly selected.
   * ────────────────────────────────────────────── */

  /* Fetch a Phase 9 campaign for a workflow type from the local API.
     If campaignId is provided, fetches that specific campaign (PB09-08 arrival handling).
     Falls back to first active campaign for the workflowType if not found or omitted.
     Returns a single campaign record or null. */
  async function fetchActivePhase9Campaign(workflowType, campaignId) {
    const base = apiBase();
    if (!base) return null;
    try {
      if (campaignId) {
        const r = await fetch(`${base}/operations/phase9/campaigns/${encodeURIComponent(String(campaignId))}`);
        if (r.ok) return await r.json();
      }
      const r = await fetch(
        `${base}/operations/phase9/campaigns?workflow_type=${workflowType}&state=active&limit=1`
      );
      if (!r.ok) return null;
      const data = await r.json();
      const campaigns = Array.isArray(data?.campaigns) ? data.campaigns : [];
      return campaigns[0] || null;
    } catch {
      return null;
    }
  }

  /* Render a Phase 9 campaign workspace body into root.
     campaign: single campaign record from API, or null if none active.
     All text rendered via textContent — no innerHTML anywhere.
     State pills use className only (no state text in innerHTML). */
  function renderPhase9CampaignWorkspace(root, workflowType, campaign) {
    const operation = workflowType;

    if (!root) return;

    const onSelect = (id) => {
      _manualOperation = id;
      writeManualOperation(id);
      renderWorkspace(id);
    };

    const wrap = safeEl('section', 'operations-workspace operations-workspace--phase9');
    wrap.setAttribute('aria-labelledby', 'operations-title');
    wrap.setAttribute('data-operation', operation);
    wrap.id = `operations-phase9-${operation}-workspace`;

    /* v3 header */
    wrap.appendChild(buildOpsV3Header(operation, {}, inputs));

    /* Mode bar */
    wrap.appendChild(buildOpsV3ModeBar(operation, onSelect));

    /* Campaign body section */
    const body = safeEl('section', 'ops-phase9-campaign-body');
    body.setAttribute('aria-label', `${operation} campaign workspace`);

    /* Workspace question */
    const questionText = _workspaceVM?.workspaceQuestion(operation) || '';
    body.appendChild(safeEl('p', 'ops-phase9-question', questionText));

    if (campaign) {
      /* Campaign title — textContent prevents XSS */
      body.appendChild(safeEl('h2', 'ops-phase9-campaign-title', campaign.title));

      /* State pill — class-based styling only, no innerHTML state value in class */
      const validStates = new Set(['proposed', 'active', 'blocked', 'completed', 'archived']);
      const safeState = validStates.has(campaign.state) ? campaign.state : 'unknown';
      const statePill = safeEl('span', `ops-phase9-state-pill ops-phase9-state-pill--${safeState}`);
      statePill.textContent = campaign.state;
      body.appendChild(statePill);

      /* Target subject / system */
      if (campaign.target_subject) {
        body.appendChild(safeEl('p', 'ops-phase9-target-subject', campaign.target_subject));
      }
      if (campaign.target_system) {
        body.appendChild(safeEl('p', 'ops-phase9-target-system', campaign.target_system));
      }

      /* Blockers */
      const blockers = Array.isArray(campaign.blockers) ? campaign.blockers : [];
      if (blockers.length > 0) {
        body.appendChild(safeEl('h3', 'ops-phase9-section-head', 'Blockers'));
        const bList = safeEl('ul', 'ops-phase9-blockers-list');
        blockers.forEach(b => bList.appendChild(safeEl('li', 'ops-phase9-blocker-item', b)));
        body.appendChild(bList);
      }

      /* Next actions */
      const nextActions = Array.isArray(campaign.next_actions) ? campaign.next_actions : [];
      if (nextActions.length > 0) {
        body.appendChild(safeEl('h3', 'ops-phase9-section-head', 'Next actions'));
        const nList = safeEl('ul', 'ops-phase9-next-actions-list');
        nextActions.forEach(a => nList.appendChild(safeEl('li', 'ops-phase9-action-item', a)));
        body.appendChild(nList);
      }

      /* Linked Intel facts (weak refs — IDs only, textContent each) */
      const linkedFacts = Array.isArray(campaign.linked_intel_facts) ? campaign.linked_intel_facts : [];
      const factsHead = safeEl('h3', 'ops-phase9-section-head');
      factsHead.textContent = `Linked Intel facts (${linkedFacts.length})`;
      body.appendChild(factsHead);
      const factList = safeEl('ul', 'ops-phase9-linked-facts-list');
      linkedFacts.forEach(fid => factList.appendChild(safeEl('li', 'ops-phase9-fact-id', fid)));
      body.appendChild(factList);

      /* Linked Navigation circuits (weak refs — IDs only, textContent each) */
      const linkedCircuits = Array.isArray(campaign.linked_navigation_circuits) ? campaign.linked_navigation_circuits : [];
      const circuitsHead = safeEl('h3', 'ops-phase9-section-head');
      circuitsHead.textContent = `Linked Navigation circuits (${linkedCircuits.length})`;
      body.appendChild(circuitsHead);
      const circuitList = safeEl('ul', 'ops-phase9-linked-circuits-list');
      linkedCircuits.forEach(cid => circuitList.appendChild(safeEl('li', 'ops-phase9-circuit-id', cid)));
      body.appendChild(circuitList);

      /* PB09-08 bridge affordances — route-transfer navigation only, no mutation */
      const bridgeNav = safeEl('nav', 'ops-phase9-bridge-links');
      bridgeNav.setAttribute('aria-label', 'Campaign bridge links');

      if (linkedFacts.length > 0) {
        const viewIntelBtn = safeEl('button', 'ops-phase9-bridge-btn ops-phase9-bridge-btn--intel', 'View Intel facts');
        viewIntelBtn.setAttribute('type', 'button');
        viewIntelBtn.addEventListener('click', () => {
          if (typeof window.Shell?.startRouteTransfer !== 'function') { window.location.hash = '#/intel'; return; }
          window.Shell.startRouteTransfer({
            originRoute: '/operations',
            originPackage: 'Operations',
            originSectionId: `operations-phase9-${operation}-workspace`,
            targetRoute: '/intel',
            targetSectionId: `intel-phase9-${operation}`,
            targetEntityId: linkedFacts[0] || '',
            targetLabel: `Intel ${operation === 'bgs' ? 'BGS' : 'Powerplay'} facts`,
            reason: 'Viewing linked Intel facts.',
            returnLabel: 'Return to Operations',
            returnTarget: { route: '/operations' },
          });
        });
        bridgeNav.appendChild(viewIntelBtn);
      }

      if (linkedCircuits.length > 0) {
        const viewCircuitBtn = safeEl('button', 'ops-phase9-bridge-btn ops-phase9-bridge-btn--navigation', 'View Navigation circuit');
        viewCircuitBtn.setAttribute('type', 'button');
        viewCircuitBtn.addEventListener('click', () => {
          if (typeof window.Shell?.startRouteTransfer !== 'function') { window.location.hash = '#/navigation'; return; }
          window.Shell.startRouteTransfer({
            originRoute: '/operations',
            originPackage: 'Operations',
            originSectionId: `operations-phase9-${operation}-workspace`,
            targetRoute: '/navigation',
            targetSectionId: 'navigation-campaign-circuits',
            targetEntityId: linkedCircuits[0] || '',
            targetLabel: 'Navigation campaign circuits',
            reason: 'Viewing linked Navigation circuit.',
            returnLabel: 'Return to Operations',
            returnTarget: { route: '/operations' },
          });
        });
        bridgeNav.appendChild(viewCircuitBtn);
      }

      const attachNoteBtn = safeEl('button', 'ops-phase9-bridge-btn ops-phase9-bridge-btn--squadrons', 'Attach Squadron note');
      attachNoteBtn.setAttribute('type', 'button');
      attachNoteBtn.addEventListener('click', () => {
        if (typeof window.Shell?.startRouteTransfer !== 'function') { window.location.hash = '#/squadrons'; return; }
        window.Shell.startRouteTransfer({
          originRoute: '/operations',
          originPackage: 'Operations',
          originSectionId: `operations-phase9-${operation}-workspace`,
          targetRoute: '/squadrons',
          targetSectionId: 'squadrons-phase9-campaign-coordination',
          targetEntityId: campaign.campaign_id || '',
          targetLabel: 'Squadron campaign coordination',
          reason: 'Attaching local-only squadron note.',
          returnLabel: 'Return to Operations',
          returnTarget: { route: '/operations' },
        });
      });
      bridgeNav.appendChild(attachNoteBtn);
      body.appendChild(bridgeNav);

      /* AI draft history cards */
      const draftHistory = Array.isArray(campaign.ai_draft_history) ? campaign.ai_draft_history : [];
      if (draftHistory.length > 0) {
        body.appendChild(safeEl('h3', 'ops-phase9-section-head', 'AI draft history'));
        draftHistory.forEach(entry => {
          body.appendChild(buildAiDraftHistoryCard(entry));
        });
      }
    } else {
      /* No active campaign — idle copy */
      const idleCopy = operation === 'bgs'
        ? 'No active BGS objective. Add one to focus the deck.'
        : 'No active Powerplay objective. Add one to focus the deck.';
      body.appendChild(safeEl('p', 'ops-phase9-idle-copy', idleCopy));
    }

    wrap.appendChild(body);

    /* Quick tools row */
    const quickTools = _workspaceVM?.workspaceQuickTools(operation) || [];
    if (quickTools.length > 0 && _primitives?.createQuickToolStrip) {
      wrap.appendChild(_primitives.createQuickToolStrip(quickTools));
    }

    /* PB09-08: Activity Log proof link (PB09-08 bridge) */
    const logLink = safeEl('a', 'ops-phase9-activity-log-link', 'View Proof ›');
    logLink.setAttribute('href', '#/activity-log');
    if (campaign?.campaign_id) {
      logLink.addEventListener('click', (e) => {
        if (typeof window.Shell?.startRouteTransfer !== 'function') return;
        e.preventDefault();
        window.Shell.startRouteTransfer({
          originRoute: '/operations',
          originPackage: 'Operations',
          originSectionId: `operations-phase9-${operation}-workspace`,
          targetRoute: '/activity-log',
          targetSectionId: 'log-body',
          targetEntityId: campaign.campaign_id,
          targetLabel: 'Activity Log proof',
          reason: 'Viewing campaign proof.',
          returnLabel: 'Return to Operations',
          returnTarget: { route: '/operations' },
        });
      });
    }
    wrap.appendChild(logLink);

    /* Back to selector */
    const footer = safeEl('footer', 'operations-workspace-footer');
    const back = safeEl('button', 'operations-selector-back', 'Back to Operations selector');
    back.type = 'button';
    back.addEventListener('click', () => {
      _manualOperation = null;
      writeManualOperation(null);
      renderIdleSelector();
    });
    footer.appendChild(back);
    wrap.appendChild(footer);

    root.replaceChildren(wrap);
    /* PB09-08: apply route-transfer arrival banner for inbound bridge handoffs */
    if (typeof window.Shell?.applyRouteTransferArrival === 'function') {
      window.Shell.applyRouteTransferArrival('/operations', root);
    }
  }

  /* ──────────────────────────────────────────────
   * PB09-06 AI draft rendering helpers
   * ADR 0003: createElement + textContent only. No innerHTML.
   * ────────────────────────────────────────────── */

  /* Build a single AI draft history card from a history entry dict.
     Renders: is_fact chip, confidence, timestamp, draft_text (non-fact label),
     source_chain (fact IDs), KB references with needs_review warning. */
  function buildAiDraftHistoryCard(entry) {
    const card = safeEl('article', 'ops-phase9-ai-draft-card');

    /* is_fact chip — always present, always "not a fact" per AI draft contract */
    card.appendChild(safeEl('span', 'ops-phase9-is-fact-chip', 'AI DRAFT — not a fact'));

    if (entry.confidence_label) {
      card.appendChild(safeEl('span', 'ops-phase9-confidence', entry.confidence_label));
    }
    if (entry.timestamp) {
      const ts = safeEl('time', 'ops-phase9-draft-timestamp');
      ts.setAttribute('datetime', entry.timestamp);
      ts.textContent = entry.timestamp;
      card.appendChild(ts);
    }

    /* draft_text — rendered as explicitly labeled non-fact text via textContent */
    if (entry.draft_text) {
      card.appendChild(safeEl('p', 'ops-phase9-draft-text', entry.draft_text));
    }

    /* source_chain — fact IDs only, textContent */
    const chain = Array.isArray(entry.source_chain) ? entry.source_chain : [];
    if (chain.length > 0) {
      const scHead = safeEl('p', 'ops-phase9-draft-sc-head', 'Sources');
      card.appendChild(scHead);
      const scList = safeEl('ul', 'ops-phase9-draft-source-chain');
      chain.forEach(sc => {
        scList.appendChild(safeEl('li', 'ops-phase9-draft-sc-item', sc.fact_id || sc.source || ''));
      });
      card.appendChild(scList);
    }

    /* KB references — metadata with needs_review warning (PB09-06) */
    const kbRefs = Array.isArray(entry.kb_references) ? entry.kb_references : [];
    if (kbRefs.length > 0) {
      card.appendChild(safeEl('p', 'ops-phase9-draft-kb-refs-head', 'KB References'));
      const kbList = safeEl('ul', 'ops-phase9-draft-kb-refs');
      kbRefs.forEach(ref => {
        const refItem = safeEl('li', 'ops-phase9-draft-kb-ref');
        refItem.appendChild(safeEl('span', 'ops-phase9-draft-kb-file', ref.kb_file || ''));
        refItem.appendChild(safeEl('span', 'ops-phase9-draft-kb-entry', ref.entry_id || ''));
        if (ref.needs_review) {
          refItem.appendChild(safeEl('span', 'ops-phase9-draft-kb-needs-review',
            'Under review — do not treat as fact'));
        }
        kbList.appendChild(refItem);
      });
      card.appendChild(kbList);
    }

    return card;
  }

  /* Render an AI draft response section (nullprovider or validation_failed) into
     the given container element. Safe DOM only — no innerHTML.
     Called by tests directly via __operationsExports.buildAiDraftResponseSection.
     In production, would be called after a fresh POST /ai-draft response.

     result shape expected:
       { status, nullprovider_message?, kb_references?, is_fact, draft_text? }
  */
  function buildAiDraftResponseSection(container, result) {
    if (!result || !container) return;

    const section = safeEl('div', 'ops-phase9-draft-response');

    if (result.status === 'nullprovider') {
      const msg = result.nullprovider_message ||
        'AI drafting disabled. Use the commander-entered notes and the linked Intel facts to plan your next step.';
      section.appendChild(safeEl('span', 'ops-phase9-is-fact-chip', 'AI DRAFT — not a fact'));
      section.appendChild(safeEl('p', 'ops-phase9-nullprovider-msg', msg));

      /* KB references disclosed on NullProvider path */
      const kbRefs = Array.isArray(result.kb_references) ? result.kb_references : [];
      if (kbRefs.length > 0) {
        section.appendChild(safeEl('p', 'ops-phase9-draft-kb-refs-head', 'KB References'));
        const kbList = safeEl('ul', 'ops-phase9-draft-kb-refs');
        kbRefs.forEach(ref => {
          const refItem = safeEl('li', 'ops-phase9-draft-kb-ref');
          refItem.appendChild(safeEl('span', 'ops-phase9-draft-kb-file', ref.kb_file || ''));
          refItem.appendChild(safeEl('span', 'ops-phase9-draft-kb-entry', ref.entry_id || ''));
          if (ref.needs_review) {
            refItem.appendChild(safeEl('span', 'ops-phase9-draft-kb-needs-review',
              'Under review — do not treat as fact'));
          }
          kbList.appendChild(refItem);
        });
        section.appendChild(kbList);
      }
    } else if (result.status === 'validation_failed') {
      section.appendChild(safeEl('span', 'ops-phase9-is-fact-chip', 'AI DRAFT — not a fact'));
      section.appendChild(safeEl('p', 'ops-phase9-validation-failed',
        'Draft validation failed. Refine the inputs and try again.'));
    }

    container.appendChild(section);
  }

  /* Public-facing renderer for BGS campaign workspace. Accepts a campaign record or null.
     Used by tests directly and by renderWorkspace async dispatch. */
  function renderBgsWorkspace(root, campaign) {
    renderPhase9CampaignWorkspace(root, 'bgs', campaign);
  }

  /* Public-facing renderer for Powerplay campaign workspace. */
  function renderPowerplayWorkspace(root, campaign) {
    renderPhase9CampaignWorkspace(root, 'powerplay', campaign);
  }

  function buildLocalContextWorkspace(operation) {
    if (!_localSurfaces || !inputs.localContext) return null;
    const {
      createCargoHoldSurface,
      createMarketSearchSurface,
      createStationBriefSurface,
    } = _localSurfaces;

    const handlers = {
      'search-sell-prices': () => stageIntelMarketFromCargo(),
      'open-market-search': () => stageIntelMarketFromCargo(),
      'compare-current-station': () => stageIntelMarketFromCargo(),
      'open-market-intel': () => stageIntelMarketFromCargo(),
      'open-cargo': () => renderWorkspace('trading'),
      'open-station': () => renderWorkspace('station'),
    };

    const grid = safeEl('section', 'operations-local-context-grid');
    grid.setAttribute('aria-label', 'Local context workspace');

    if (operation === 'station') {
      grid.appendChild(createStationBriefSurface(inputs.localContext.stationBrief, { handlers }));
      grid.appendChild(createMarketSearchSurface(inputs.localContext.marketSearch));
      return grid;
    }

    if (operation === 'mining' || operation === 'trading') {
      grid.appendChild(createCargoHoldSurface(inputs.localContext.cargoHold, { handlers }));
      grid.appendChild(createMarketSearchSurface(inputs.localContext.marketSearch));
      grid.appendChild(createStationBriefSurface(inputs.localContext.stationBrief, { handlers }));
      return grid;
    }

    return null;
  }

  function stageIntelMarketFromCargo() {
    /* PB-UIV3-RECOVERY-03: legacy Shell.stageSystem is retired (no-op shim).
       Operations links to Intel via the canonical route hash; Intel owns
       Commodity Search / Module Search and renders inside #view-intel. */
    window.location.hash = '#/intel';
  }

  function buildOperationDetail(operation) {
    const container = safeEl('div', 'operations-detail');

    const cargoItems = Array.isArray(inputs.cargo?.inventory) ? inputs.cargo.inventory : [];
    const cargoCount = inputs.state?.cargo_count;
    const cargoCap   = inputs.state?.cargo_capacity;
    const route      = inputs.navSnap?.active_route?.destination || null;
    const station    = inputs.state?.current_station || inputs.localContext?.stationBrief?.stationName || null;
    const market     = inputs.localContext?.marketSearch || null;

    const dl = document.createElement('dl');
    dl.className = 'operations-detail-dl';

    function row(label, value) {
      const dt = safeEl('dt', 'operations-detail-dt', label);
      const dd = safeEl('dd', 'operations-detail-dd', value);
      dl.appendChild(dt);
      dl.appendChild(dd);
    }

    row('Operation', operation);
    if (cargoCount != null && cargoCap != null) row('Cargo', `${cargoCount} / ${cargoCap} t`);
    else if (cargoItems.length > 0) row('Cargo types', `${cargoItems.length}`);
    else row('Cargo', 'No cargo detected');
    row('Route', route ? route : 'No route plotted');
    /* Smoke R1: derive station/docking via unified location state so
       Operations never says "Undocked" when station_context knows a station. */
    const sessionState = window.Shell?.eliteSessionState || null;
    const loc = _commanderVM?.deriveCommanderLocationState?.(
      inputs.localContext, inputs.state, inputs.navSnap, { sessionState }) || null;
    if (loc) {
      row('Station', loc.stationName || (loc.dockingState === 'in_space' ? 'In space' : 'Unknown'));
      row('Docking', `${loc.flightLabel}: ${loc.flightValue}`);
    } else {
      row('Station', station || 'Unknown');
    }
    row('Local market', market?.available ? `${market.itemCount} current local rows` : 'No local market snapshot loaded');

    container.appendChild(dl);

    if (cargoItems.length > 0) {
      const heading = safeEl('h4', 'operations-detail-subheading', 'Top cargo');
      const list = safeEl('ul', 'operations-detail-cargo-list');
      cargoItems.slice(0, 6).forEach((item) => {
        const li = safeEl('li', 'operations-detail-cargo-item');
        li.appendChild(safeEl('span', 'operations-detail-cargo-name', item?.name || 'Unknown'));
        li.appendChild(safeEl('span', 'operations-detail-cargo-count', String(item?.count ?? '—')));
        list.appendChild(li);
      });
      container.appendChild(heading);
      container.appendChild(list);
    }

    return container;
  }

  function buildProofContent(operation) {
    const container = safeEl('div', 'operations-proof');

    const lines = [
      'Operations reads only local Status, Loadout, Cargo, NavRoute, and combat session data.',
      'No outbound provider lookups happen by default; external integrations remain gated.',
      'See Activity Log for raw event history and Systems route for source posture detail.',
    ];

    lines.forEach((text) => {
      container.appendChild(safeEl('p', 'operations-proof-line', text));
    });

    container.appendChild(safeEl('p', 'operations-proof-note',
      `Operation context: ${operation}. Unknown remains unknown — no inferred facts are presented as observed.`));

    return container;
  }

  async function loadAndRender() {
    await Promise.all([primitivesPromise, commanderPromise, workspacePromise, localContextPromise, localSurfacesPromise]);
    if (!_primitives || !_commanderVM || !_workspaceVM) {
      renderUnavailable('Command primitives unavailable.');
      return;
    }

    const [ship, cargo, heat, mods, navSnap, combat, localContextSnap] = await Promise.all([
      fetchJson('/pillar1/ship-state'),
      fetchJson('/pillar1/cargo'),
      fetchJson('/pillar1/heat'),
      fetchJson('/pillar1/modules/summary'),
      fetchJson('/navigation/snapshot'),
      fetchJson('/combat/snapshot'),
      fetchJson('/intel/local-context/snapshot'),
    ]);

    inputs.state = ship;
    inputs.cargo = cargo;
    inputs.heat  = heat;
    inputs.mods  = mods;
    inputs.navSnap = navSnap;
    inputs.combat  = combat;
    inputs.localContext = _localContextVM?.deriveLocalContext(localContextSnap) || null;

    renderWorkspace(_manualOperation);
  }

  function renderUnavailable(message) {
    const root = getRoot();
    if (!root) return;
    root.replaceChildren();
    const note = safeEl('section', 'operations-unavailable');
    const h1 = safeEl('h1', 'operations-unavailable-title', 'Operations');
    h1.id = 'operations-title';
    const p = safeEl('p', 'operations-unavailable-message', message);
    note.appendChild(h1);
    note.appendChild(p);
    root.appendChild(note);
  }

  function renderOperations() {
    const root = getRoot();
    if (!root) return;
    if (!_primitives || !_commanderVM || !_workspaceVM) {
      const interim = safeEl('section', 'operations-loading');
      const h1 = safeEl('h1', 'operations-loading-title', 'Operations');
      h1.id = 'operations-title';
      const p = safeEl('p', 'operations-loading-message', 'Loading workspace…');
      interim.appendChild(h1);
      interim.appendChild(p);
      root.replaceChildren(interim);
      Promise.all([primitivesPromise, commanderPromise, workspacePromise, localContextPromise, localSurfacesPromise]).then(() => {
        renderWorkspace(_manualOperation);
      });
      return;
    }
    renderWorkspace(_manualOperation);
  }

  /* ──────────────────────────────────────────────
   * Event wiring
   * ────────────────────────────────────────────── */
  function bindEvents() {
    if (window.OmniEvents) {
      window.OmniEvents.addEventListener('bridge-connected', loadAndRender);
      window.OmniEvents.addEventListener('event', (ev) => {
        const detail = ev.detail || {};
        const type = detail.event_type || detail.event;
        if (!type) return;
        if (type === 'INTERDICTION_STARTED' || type === 'INTERDICTION_ENDED'
            || type === 'COMBAT_STATE_CHANGED' || type === 'COMBAT_SESSION_STATE_CHANGED') {
          fetchJson('/combat/snapshot').then((c) => { inputs.combat = c; renderWorkspace(_manualOperation); });
        }
        if (type === 'CARGO_CHANGED') {
          Promise.all([
            fetchJson('/pillar1/cargo'),
            fetchJson('/intel/local-context/snapshot'),
          ]).then(([c, localContextSnap]) => {
            inputs.cargo = c;
            inputs.localContext = _localContextVM?.deriveLocalContext(localContextSnap) || inputs.localContext;
            renderWorkspace(_manualOperation);
          });
        }
        if (type === 'SHIP_STATE_CHANGED' || type === 'LOADOUT_CHANGED') {
          loadAndRender();
        }
      });
    }
    window.addEventListener('hashchange', () => {
      if (window.location.hash === '#/operations') loadAndRender();
    });
  }

  function init() {
    bindEvents();
    if (apiBase()) {
      loadAndRender();
    } else {
      renderUnavailable('Waiting for OmniCOVAS bridge.');
    }
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }

  /* Test hooks — expose synchronous render entry points for vitest/JSDOM */
  globalThis.__operationsExports = {
    renderOperations,
    renderWorkspace,
    /* Phase 9 campaign workspace renderers — called directly in tests with mock data */
    renderBgsWorkspace,
    renderPowerplayWorkspace,
    /* PB09-06 AI draft rendering helpers */
    buildAiDraftHistoryCard,
    buildAiDraftResponseSection,
    setOperation(op) {
      _manualOperation = op;
      writeManualOperation(op);
    },
    setInputs(next) {
      Object.assign(inputs, next || {});
      if (next?.localContextSnap && _localContextVM) {
        inputs.localContext = _localContextVM.deriveLocalContext(next.localContextSnap);
      }
    },
    resetState() {
      Object.keys(inputs).forEach((k) => { inputs[k] = null; });
      _manualOperation = null;
      writeManualOperation(null);
    },
    async getCommandPrimitives() {
      const p = await primitivesPromise;
      await commanderPromise;
      await workspacePromise;
      await localContextPromise;
      await localSurfacesPromise;
      return p;
    },
    /* Compatibility shims for older tests. */
    openOperationsPackage() { renderOperations(); },
    resetTargetThreatForTests() { /* no-op in v2/v3 workspace model */ },
  };
})();
