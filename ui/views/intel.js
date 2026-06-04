/**
 * OmniCOVAS Intel - Briefing & Search Surface.
 *
 * Search-first / briefing-first. Default pilot view now consumes the local
 * context backplane for Station Brief, System Brief, current local Market
 * Search, and module/loadout status. Proof remains collapsed.
 */

(function () {
  'use strict';

  const INTEL_SNAPSHOT_PATH = '/intel/snapshot';
  const ECONOMIC_SNAPSHOT_PATH = '/intel/economic/snapshot';
  const LOCAL_CONTEXT_SNAPSHOT_PATH = '/intel/local-context/snapshot';
  const PHASE9_BGS_FACTS_PATH = '/intel/phase9/bgs-facts';
  const PHASE9_POWERPLAY_FACTS_PATH = '/intel/phase9/powerplay-facts';

  let _primitives = null;
  let _briefingVM = null;
  let _localContextVM = null;
  let _localSurfaces = null;
  let _sourceProof = null;

  const primitivesPromise = import('../components/command-primitives.js')
    .then((m) => { _primitives = m; return m; })
    .catch((err) => { console.error('[intel] Failed to load command primitives:', err); return null; });

  const briefingPromise = import('../view-models/intel-briefing.js')
    .then((m) => { _briefingVM = m; return m; })
    .catch((err) => { console.error('[intel] Failed to load intel briefing VM:', err); return null; });

  const localContextPromise = import('../view-models/local-context.js')
    .then((m) => { _localContextVM = m; return m; })
    .catch((err) => { console.error('[intel] Failed to load local context VM:', err); return null; });

  const localSurfacesPromise = import('../components/local-context-surfaces.js')
    .then((m) => { _localSurfaces = m; return m; })
    .catch((err) => { console.error('[intel] Failed to load local context surfaces:', err); return null; });

  const sourceProofPromise = import('../components/source-proof.js')
    .then((m) => { _sourceProof = m; return m; })
    .catch((err) => { console.error('[intel] Failed to load source proof primitives:', err); return null; });

  function getRoot() { return document.getElementById('intel-root'); }

  function safeEl(tag, className, text) {
    const el = document.createElement(tag);
    if (className) el.className = className;
    if (text !== undefined && text !== null) el.textContent = String(text);
    return el;
  }

  class IntelController {
    constructor() {
      this._lastSnapshot = null;
      this._lastEconomic = null;
      this._lastLocalContext = null;
      this._lastBgsFacts = null;
      this._lastPowerplayFacts = null;
      this._lastQuery = null;
      this._activeDomain = 'system';
      this._boundHandler = () => { this.fetchAndRender(); };
      this.init();
    }

    get apiBase() {
      if (window.Shell?.httpBase) return window.Shell.httpBase;
      if (window.OMNICOVAS_PORT) return `http://127.0.0.1:${window.OMNICOVAS_PORT}`;
      return null;
    }

    init() {
      if (window.OmniEvents) {
        window.OmniEvents.addEventListener('bridge-connected', this._boundHandler);
      }
      if (this.apiBase) this.fetchAndRender();
      else this.renderWaiting();
    }

    async fetchAndRender() {
      const base = this.apiBase;
      if (!base) { this.renderWaiting(); return; }

      const [
        snapshot,
        economicSnapshot,
        localContextSnapshot,
        bgsFacts,
        powerplayFacts,
      ] = await Promise.all([
        this.fetchJson(`${base}${INTEL_SNAPSHOT_PATH}`).catch((err) => {
          console.error('Intel snapshot unavailable:', err);
          return null;
        }),
        this.fetchJson(`${base}${ECONOMIC_SNAPSHOT_PATH}`).catch((err) => {
          console.warn('Economic snapshot unavailable:', err);
          return null;
        }),
        this.fetchJson(`${base}${LOCAL_CONTEXT_SNAPSHOT_PATH}`).catch((err) => {
          console.warn('Local context snapshot unavailable:', err);
          return null;
        }),
        this.fetchJson(`${base}${PHASE9_BGS_FACTS_PATH}`).catch((err) => {
          console.warn('Phase 9 BGS facts unavailable:', err);
          return null;
        }),
        this.fetchJson(`${base}${PHASE9_POWERPLAY_FACTS_PATH}`).catch((err) => {
          console.warn('Phase 9 Powerplay facts unavailable:', err);
          return null;
        }),
      ]);

      await Promise.all([
        primitivesPromise,
        briefingPromise,
        localContextPromise,
        localSurfacesPromise,
        sourceProofPromise,
      ]);
      if (!_primitives || !_briefingVM) {
        this.renderError('Command primitives unavailable.');
        return;
      }

      this._lastSnapshot = snapshot;
      this._lastEconomic = economicSnapshot;
      this._lastLocalContext = _localContextVM?.deriveLocalContext(localContextSnapshot) || null;
      this._lastBgsFacts = bgsFacts;
      this._lastPowerplayFacts = powerplayFacts;
      this.render();
    }

    async fetchJson(url) {
      const response = await fetch(url);
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      return response.json();
    }

    renderWaiting() {
      const root = getRoot();
      if (!root) return;
      root.replaceChildren();
      const wrap = safeEl('section', 'intel-waiting');
      const h1 = safeEl('h1', 'intel-waiting-title', 'Intel');
      h1.id = 'intel-title';
      const p = safeEl('p', 'intel-waiting-message', 'Waiting for OmniCOVAS bridge.');
      wrap.append(h1, p);
      root.appendChild(wrap);
    }

    renderError(message) {
      const root = getRoot();
      if (!root) return;
      root.replaceChildren();
      const wrap = safeEl('section', 'intel-waiting');
      const h1 = safeEl('h1', 'intel-waiting-title', 'Intel');
      h1.id = 'intel-title';
      const p = safeEl('p', 'intel-waiting-message', message);
      wrap.append(h1, p);
      root.appendChild(wrap);
    }

    render() {
      const root = getRoot();
      if (!root) return;

      const {
        createRouteHero,
        createSearchPanel,
        createCommandContextSpine,
        createDetailDrawer,
        createProofToggle,
      } = _primitives;

      const { deriveIntelBriefing, INTEL_SEARCH_MODES } = _briefingVM;
      const briefing = deriveIntelBriefing(this._lastSnapshot, this._lastEconomic, this._lastLocalContext);
      this._briefing = briefing;
      const wrap = safeEl('section', 'intel-surface');

      const heroLine = briefing.location?.primaryLine || 'No local location yet';
      const hero = createRouteHero({
        /* PB-UIV3-HARMONY §4·3: Intel is the local intelligence terminal, not a
           search box. The terminal leads with the commander's current context. */
        kicker: 'Intelligence Terminal',
        title: 'Intel',
        statusText: heroLine,
        statusVariant: briefing.location ? 'available' : 'not-loaded',
      });
      const titleNode = hero.querySelector('.route-hero-title');
      if (titleNode) titleNode.id = 'intel-title';
      wrap.appendChild(hero);

      const spineItems = [];
      if (briefing.location?.system) spineItems.push({ id: 'system', label: 'System', value: briefing.location.system });
      if (briefing.stationBrief?.stationName || briefing.station?.station) {
        spineItems.push({ id: 'station', label: 'Station', value: briefing.stationBrief?.stationName || briefing.station.station });
      }
      if (briefing.economic?.itemCount) spineItems.push({ id: 'local-market', label: 'Local market rows', value: String(briefing.economic.itemCount) });
      /* Shared Live Context Header — the persistent anchor for the terminal. */
      const contextHeader = createCommandContextSpine(spineItems);
      contextHeader.classList.add('intel-live-context-header');
      contextHeader.setAttribute('aria-label', 'Live context — current system and station');
      wrap.appendChild(contextHeader);

      /* §4·3 domain tab row — selecting a domain SWITCHES the visible workspace
         (a real terminal), instead of scrolling one long stacked page. */
      wrap.appendChild(this.buildDomainScaffold(briefing));

      /* The single domain workspace. Every domain renders its own command-deck
         card workspace; only the active one is visible. The default domain is
         System (current local context) so the terminal opens context-led, never
         on an empty search box. */
      const workspace = safeEl('div', 'intel-workspace');
      workspace.id = 'intel-workspace';
      workspace.append(
        this._domainPanel('system', this._buildSystemWorkspace(briefing)),
        this._domainPanel('station', this._buildStationWorkspace(briefing)),
        this._domainPanel('galaxy', this._buildGalaxyWorkspace(briefing)),
        this._domainPanel('search', this._buildSearchWorkspace(createSearchPanel, INTEL_SEARCH_MODES)),
        this._domainPanel('commodities', this._buildMarketWorkspace(briefing)),
        this._domainPanel('modules', this._buildModuleWorkspace(briefing)),
        this._domainPanel('bgs', this._buildBgsWorkspace()),
        this._domainPanel('powerplay', this._buildPowerplayWorkspace()),
        this._domainPanel('ships', this._reservedWorkspace('Ships / Shipyard', 'Phase 13',
          'Local shipyard snapshots and curated ship reference will land here.')),
        this._domainPanel('services', this._reservedWorkspace('Station Services', 'Phase 13',
          'Service discovery from local station observations will land here.')),
        this._domainPanel('campaign', this._reservedWorkspace('Campaign Facts', 'Operations',
          'Intel owns campaign facts; the campaign workflow runs in Operations. Open BGS or Powerplay for current local facts.')),
        this._domainPanel('reference', this._reservedWorkspace('Reference Library', 'Phase 13',
          'Workflow-scoped reference entries will land here — scoped to OmniCOVAS workflows, not an encyclopedia.')),
      );
      wrap.appendChild(workspace);

      /* Raw lineage stays available as deeper disclosure below the workspace —
         never the first impression. */
      wrap.appendChild(createDetailDrawer({
        summary: 'All known facts',
        content: this.buildKnownFactsDetail(briefing.sectionsSummary),
      }));

      wrap.appendChild(createProofToggle(this.buildProofPanel(briefing), 'Sources & evidence'));

      root.replaceChildren(wrap);
      this._setDomain(this._activeDomain || 'system');
    }

    /* One domain workspace panel. All panels live in the DOM; only the active
       one is shown so domain selection swaps the visible workspace. */
    _domainPanel(id, content) {
      const panel = safeEl('section', 'intel-domain-panel');
      panel.id = `intel-domain-${id}`;
      panel.setAttribute('data-intel-domain-panel', id);
      panel.setAttribute('role', 'tabpanel');
      if (content instanceof Node) panel.appendChild(content);
      return panel;
    }

    /* Switch the visible domain workspace + move the active tab indicator. */
    _setDomain(id) {
      this._activeDomain = id;
      const root = getRoot();
      if (!root) return;
      root.querySelectorAll('.intel-domain-panel').forEach((panel) => {
        const match = panel.getAttribute('data-intel-domain-panel') === id;
        panel.hidden = !match;
        panel.classList.toggle('is-active', match);
      });
      root.querySelectorAll('.intel-domain-tab').forEach((tab) => {
        if (tab.getAttribute('data-intel-domain') === id) tab.setAttribute('aria-current', 'true');
        else tab.removeAttribute('aria-current');
      });
    }

    /* PB-UIV3-HARMONY §4·3 domain tab row. Implemented domains switch their
       workspace; future domains are clickable too and open an honest, compact
       reserved workspace card (never a dead decorative label). No provider
       activation, no fabricated data. */
    buildDomainScaffold() {
      const nav = safeEl('nav', 'intel-domain-tabs');
      nav.setAttribute('role', 'tablist');
      nav.setAttribute('aria-label', 'Intel fact domains');

      const DOMAINS = [
        { id: 'system', label: 'System' },
        { id: 'station', label: 'Station' },
        { id: 'galaxy', label: 'Galaxy' },
        { id: 'search', label: 'Search' },
        { id: 'commodities', label: 'Commodities' },
        { id: 'modules', label: 'Modules' },
        { id: 'bgs', label: 'BGS' },
        { id: 'powerplay', label: 'Powerplay' },
        { id: 'ships', label: 'Ships', reserved: true },
        { id: 'services', label: 'Services', reserved: true },
        { id: 'campaign', label: 'Campaign', reserved: true },
        { id: 'reference', label: 'Reference', reserved: true },
      ];

      const active = this._activeDomain || 'system';
      DOMAINS.forEach((domain) => {
        const tab = safeEl('button', 'intel-domain-tab', domain.label);
        tab.setAttribute('type', 'button');
        tab.setAttribute('role', 'tab');
        tab.setAttribute('data-intel-domain', domain.id);
        if (domain.id === active) tab.setAttribute('aria-current', 'true');
        if (domain.reserved) {
          tab.classList.add('intel-domain-tab--reserved');
          tab.appendChild(safeEl('span', 'intel-domain-tab-badge', 'Reserved'));
        }
        tab.addEventListener('click', () => this._setDomain(domain.id));
        nav.appendChild(tab);
      });

      return nav;
    }

    /* ── Domain workspace builders ───────────────────────────────────── */

    _buildSystemWorkspace(briefing) {
      if (_localSurfaces && briefing.localContext) {
        return _localSurfaces.createSystemBriefSurface(briefing.systemBrief, { id: 'intel-system-brief' });
      }
      return this._fallbackBriefCard('System Brief',
        'No local system context loaded. Jump or load into a system to build a System Brief.',
        'intel-system-brief');
    }

    _buildStationWorkspace(briefing) {
      if (_localSurfaces && briefing.localContext) {
        return _localSurfaces.createStationBriefSurface(briefing.stationBrief, {
          id: 'intel-station-brief',
          handlers: this._localActionHandlers(),
          showAction: false,
        });
      }
      return this._fallbackBriefCard('Station Brief',
        'No local station context loaded. Dock at a station to build a Station Brief.',
        'intel-station-brief');
    }

    _buildGalaxyWorkspace(briefing) {
      return this._buildGalaxyBriefSurface(briefing);
    }

    _buildSearchWorkspace(createSearchPanel, INTEL_SEARCH_MODES) {
      const section = safeEl('section', 'intel-search-workspace');
      section.id = 'intel-domain-search';
      section.setAttribute('aria-label', 'Search');
      section.appendChild(safeEl('p', 'intel-workspace-lead',
        'Search local intelligence. Commodity and module results open in their domain workspace; system and station searches focus the matching brief.'));
      const search = createSearchPanel({
        modes: INTEL_SEARCH_MODES,
        initialMode: 'commodity',
        onSearch: (query, mode) => this.handleSearch(query, mode),
        ariaLabel: 'Intel search',
      });
      section.appendChild(search);
      return section;
    }

    _buildMarketWorkspace(briefing) {
      if (_localSurfaces && briefing.localContext) {
        const market = _localSurfaces.createMarketSearchSurface(briefing.marketSearch, {
          id: 'intel-market-search',
          suppressSearch: true,
          deferResults: true,
        });
        market.setAttribute('data-intel-search-owner', 'market');
        return market;
      }
      return this._fallbackWorkPanel(
        'intel-market-search',
        'Market Search',
        'Local station market data only. Search activates after Market.json is loaded.',
        'market',
      );
    }

    _buildModuleWorkspace(briefing) {
      if (_localSurfaces && briefing.localContext) {
        const module = _localSurfaces.createModuleSearchSurface(briefing.moduleSearch, {
          id: 'intel-module-search',
          showAction: false,
          deferResults: true,
        });
        module.setAttribute('data-intel-search-owner', 'module');
        /* Override initial prompt to reflect outfitting (station) not loadout. */
        const moduleResults = module.querySelector('.local-module-results');
        if (moduleResults) {
          const outfitting = _localContextVM?.deriveOutfittingModules?.(this._lastEconomic);
          const initMsg = outfitting?.available
            ? `Search station-available modules. ${outfitting.moduleCount} modules in local outfitting snapshot.`
            : 'Local outfitting snapshot not loaded. Open Outfitting at a station to populate local module availability.';
          moduleResults.replaceChildren(safeEl('p', 'local-module-deferred', initMsg));
        }
        return module;
      }
      return this._fallbackWorkPanel(
        'intel-module-search',
        'Module Search',
        'Local module loadout not loaded. Search activates after a Loadout event arrives.',
        'module',
      );
    }

    _buildBgsWorkspace() {
      const drawer = this._collapsedPhase9Drawer(
        'intel-phase9-bgs',
        'bgs',
        'BGS Facts',
        this._bgsSummaryText(),
        this._buildBgsFactSurface(),
      );
      /* In the BGS domain workspace the facts lead expanded, not collapsed. */
      drawer.open = true;
      return drawer;
    }

    _buildPowerplayWorkspace() {
      const drawer = this._collapsedPhase9Drawer(
        'intel-phase9-powerplay',
        'powerplay',
        'Powerplay Facts',
        this._powerplaySummaryText(),
        this._buildPowerplayFactSurface(),
      );
      drawer.open = true;
      return drawer;
    }

    /* Honest, compact reserved-domain workspace card — labelled, never a dead
       decorative label and never fake data. */
    _reservedWorkspace(title, phase, description) {
      const card = safeEl('section', 'intel-reserved-workspace');
      card.setAttribute('aria-label', `${title} — reserved`);
      card.appendChild(safeEl('p', 'intel-reserved-eyebrow', `Reserved — ${phase}`));
      card.appendChild(safeEl('h3', 'intel-reserved-title', title));
      card.appendChild(safeEl('p', 'intel-reserved-desc', description));
      return card;
    }

    _collapsedPhase9Drawer(id, kind, title, statusText, content) {
      const drawer = safeEl('details', `local-phase9-drawer local-phase9-drawer--${kind}`);
      drawer.id = id;
      drawer.setAttribute('data-local-surface', kind);
      const summary = safeEl('summary', 'local-phase9-summary');
      summary.appendChild(safeEl('span', 'local-phase9-summary-title', title));
      summary.appendChild(safeEl('span', 'local-phase9-summary-status', statusText));
      drawer.appendChild(summary);
      drawer.appendChild(content);
      return drawer;
    }

    _bgsSummaryText() {
      const system = this._lastBgsFacts?.system_bgs || {};
      return this._valueOrFallback(
        system.controlling_faction,
        system.controlling_faction_fallback || system.fallback,
      );
    }

    _powerplaySummaryText() {
      const pledge = this._lastPowerplayFacts?.pledge || {};
      const rank = this._lastPowerplayFacts?.rank || {};
      const pledgeValue = this._valueOrFallback(pledge.value, pledge.fallback);
      if (rank.value === null || rank.value === undefined || rank.value === '') {
        return pledgeValue;
      }
      return `${pledgeValue} / Rank ${rank.value}`;
    }

    _buildBgsFactSurface() {
      const facts = this._lastBgsFacts || {};
      const system = facts.system_bgs || {};
      const station = facts.station_bgs || {};
      const missionEffects = Array.isArray(facts.recent_mission_effects)
        ? facts.recent_mission_effects
        : [];
      const rewards = Array.isArray(facts.recent_reward_events)
        ? facts.recent_reward_events
        : [];
      const surface = this._briefShell(
        'bgs',
        'BGS Facts',
        'Local Journal observations only; no global BGS feed is loaded.',
      );
      surface.appendChild(this._factList([
        {
          label: 'System control',
          value: this._valueOrFallback(
            system.controlling_faction,
            system.controlling_faction_fallback || system.fallback,
          ),
        },
        {
          label: 'System factions',
          value: system.faction_count > 0
            ? `${system.faction_count} observed`
            : this._valueOrFallback(null, system.factions_fallback || system.fallback),
        },
        {
          label: 'Station control',
          value: this._valueOrFallback(
            station.controlling_faction,
            station.controlling_faction_fallback || station.fallback,
          ),
        },
        {
          label: 'Mission effects',
          value: missionEffects.length ? `${missionEffects.length} observed` : 'Not Loaded',
        },
        {
          label: 'Bounty / bond events',
          value: rewards.length ? `${rewards.length} observed` : 'Not Loaded',
        },
      ]));
      surface.appendChild(this._detailDrawer('BGS detail', this._buildBgsDetail(facts)));
      surface.appendChild(this._detailDrawer('BGS proof', this._buildBgsProof(facts), 'local-proof-drawer'));
      /* PB09-08: bridge link to Operations BGS campaign workspace */
      const opsBtn = safeEl('button', 'intel-phase9-bridge-btn', 'Open in Operations');
      opsBtn.setAttribute('type', 'button');
      opsBtn.addEventListener('click', () => {
        if (typeof window.Shell?.startRouteTransfer !== 'function') { window.location.hash = '#/operations'; return; }
        window.Shell.startRouteTransfer({
          originRoute: '/intel',
          originPackage: 'Intel',
          originSectionId: 'intel-phase9-bgs',
          targetRoute: '/operations',
          targetSectionId: 'operations-phase9-bgs-workspace',
          targetEntityId: '',
          targetLabel: 'Operations BGS campaign workspace',
          reason: 'Opening BGS campaign workspace.',
          returnLabel: 'Return to Intel',
          returnTarget: { route: '/intel' },
        });
      });
      surface.appendChild(opsBtn);
      return surface;
    }

    _buildPowerplayFactSurface() {
      const facts = this._lastPowerplayFacts || {};
      const pledge = facts.pledge || {};
      const rank = facts.rank || {};
      const system = facts.system_powerplay || {};
      const recentEvents = Array.isArray(facts.recent_events) ? facts.recent_events : [];
      const surface = this._briefShell(
        'powerplay',
        'Powerplay Facts',
        'Local Journal observations only; no global Powerplay state is loaded.',
      );
      surface.appendChild(this._factList([
        { label: 'Pledge', value: this._valueOrFallback(pledge.value, pledge.fallback) },
        { label: 'Rank', value: this._valueOrFallback(rank.value, rank.fallback) },
        {
          label: 'System powers',
          value: Array.isArray(system.powers) && system.powers.length
            ? system.powers.join(', ')
            : this._valueOrFallback(system.powerplay_state, system.fallback),
        },
        {
          label: 'Recent events',
          value: recentEvents.length ? `${recentEvents.length} observed` : 'Not Loaded',
        },
        { label: 'Merit values', value: 'Unsupported' },
      ]));
      surface.appendChild(this._detailDrawer('Powerplay detail', this._buildPowerplayDetail(facts)));
      surface.appendChild(this._detailDrawer('Powerplay proof', this._buildPowerplayProof(facts), 'local-proof-drawer'));
      /* PB09-08: bridge link to Operations Powerplay campaign workspace */
      const opsBtn = safeEl('button', 'intel-phase9-bridge-btn', 'Open in Operations');
      opsBtn.setAttribute('type', 'button');
      opsBtn.addEventListener('click', () => {
        if (typeof window.Shell?.startRouteTransfer !== 'function') { window.location.hash = '#/operations'; return; }
        window.Shell.startRouteTransfer({
          originRoute: '/intel',
          originPackage: 'Intel',
          originSectionId: 'intel-phase9-powerplay',
          targetRoute: '/operations',
          targetSectionId: 'operations-phase9-powerplay-workspace',
          targetEntityId: '',
          targetLabel: 'Operations Powerplay campaign workspace',
          reason: 'Opening Powerplay campaign workspace.',
          returnLabel: 'Return to Intel',
          returnTarget: { route: '/intel' },
        });
      });
      surface.appendChild(opsBtn);
      return surface;
    }

    _buildBgsDetail(facts) {
      const wrap = safeEl('div', 'local-detail-body');
      wrap.appendChild(this._factList([
        {
          label: 'System',
          value: this._valueOrFallback(facts?.system_bgs?.system_name, facts?.system_bgs?.fallback),
        },
        {
          label: 'Station',
          value: this._valueOrFallback(facts?.station_bgs?.station_name, facts?.station_bgs?.fallback),
        },
      ], 'local-detail-list'));
      wrap.appendChild(this._eventList(
        'MissionCompleted.FactionEffects',
        facts?.recent_mission_effects,
        (entry) => [
          this._valueOrFallback(entry.faction, 'Unknown'),
          Array.isArray(entry.effect_kinds) && entry.effect_kinds.length
            ? entry.effect_kinds.join(', ')
            : 'Observed',
          entry.event_timestamp || 'Unknown',
        ].join(' . '),
      ));
      wrap.appendChild(this._eventList(
        'Bounty / bond history',
        facts?.recent_reward_events,
        (entry) => [
          entry.event_type || 'Journal event',
          entry.reward_type || 'Observed',
          entry.amount != null ? `${Number(entry.amount).toLocaleString('en-US')} cr` : 'Amount unknown',
          entry.event_timestamp || 'Unknown',
        ].join(' . '),
      ));
      wrap.appendChild(this._eventList(
        'Reference material',
        facts?.knowledge_references,
        (entry) => `${entry.topic || 'Reference'} . ${entry.content || ''}`,
      ));
      return wrap;
    }

    _buildPowerplayDetail(facts) {
      const wrap = safeEl('div', 'local-detail-body');
      wrap.appendChild(this._factList([
        {
          label: 'Pledge source',
          value: this._valueOrFallback(facts?.pledge?.source_event, facts?.pledge?.fallback),
        },
        {
          label: 'Rank source',
          value: this._valueOrFallback(facts?.rank?.source_event, facts?.rank?.fallback),
        },
        {
          label: 'System',
          value: this._valueOrFallback(
            facts?.system_powerplay?.system_name,
            facts?.system_powerplay?.fallback,
          ),
        },
      ], 'local-detail-list'));
      wrap.appendChild(this._eventList(
        'Powerplay event history',
        facts?.recent_events,
        (entry) => {
          const fields = Object.keys(entry.observed_fields || {});
          const withheld = Array.isArray(entry.withheld_fields) && entry.withheld_fields.length
            ? `withheld: ${entry.withheld_fields.join(', ')}`
            : 'no withheld fields';
          return [
            entry.event_type || 'Powerplay event',
            entry.power || 'Power unknown',
            fields.length ? `fields: ${fields.join(', ')}` : 'event observed',
            withheld,
            entry.event_timestamp || 'Unknown',
          ].join(' . ');
        },
      ));
      wrap.appendChild(this._eventList(
        'Unsupported claims',
        facts?.unsupported_claims,
        (entry) => `${entry.label || 'Unsupported'} . ${entry.fallback || 'Unsupported'}`,
      ));
      return wrap;
    }

    _buildBgsProof(facts) {
      const wrap = safeEl('div', 'local-proof-panel');
      [
        facts?.system_bgs,
        facts?.station_bgs,
        ...(Array.isArray(facts?.knowledge_references) ? facts.knowledge_references : []),
      ].filter(Boolean).forEach((entry) => {
        wrap.appendChild(this._sourceProofDrawer(entry, entry.topic || entry.scope || 'Proof'));
      });
      if (!wrap.children.length) {
        wrap.appendChild(safeEl('p', 'local-proof-line', 'No BGS proof metadata loaded.'));
      }
      return wrap;
    }

    _buildPowerplayProof(facts) {
      const wrap = safeEl('div', 'local-proof-panel');
      [
        facts?.pledge,
        facts?.rank,
        facts?.system_powerplay,
        ...(Array.isArray(facts?.recent_events) ? facts.recent_events.slice(-3) : []),
      ].filter(Boolean).forEach((entry) => {
        wrap.appendChild(this._sourceProofDrawer(entry, entry.event_type || 'Proof'));
      });
      if (!wrap.children.length) {
        wrap.appendChild(safeEl('p', 'local-proof-line', 'No Powerplay proof metadata loaded.'));
      }
      return wrap;
    }

    buildKnownFactsDetail(sectionsSummary) {
      const wrap = safeEl('div', 'intel-known-facts-detail');

      const list = safeEl('ul', 'intel-known-facts-list');
      list.setAttribute('role', 'list');
      (sectionsSummary || []).forEach((entry) => {
        const li = safeEl('li', 'intel-known-facts-item');
        li.appendChild(safeEl('span', 'intel-known-facts-label', entry.label));
        li.appendChild(safeEl('span', 'intel-known-facts-count',
          entry.factCount === 0 ? 'No data' : `${entry.factCount} / ${entry.totalFacts}`));
        list.appendChild(li);
      });
      wrap.appendChild(list);

      wrap.appendChild(safeEl('p', 'intel-known-facts-note',
        this._lastSnapshot ? 'Open Activity Log for raw event history.' : 'No local intel snapshot. OmniCOVAS will not infer facts.'));
      return wrap;
    }

    buildProofPanel(briefing) {
      const wrap = safeEl('div', 'intel-proof-panel');
      wrap.appendChild(safeEl('p', 'intel-proof-line',
        'Intel facts derive from local Journal, Status, companion JSON, and approved local snapshots.'));
      wrap.appendChild(safeEl('p', 'intel-proof-line',
        'External providers remain gated. Provider posture and source health live in Systems / Diagnostics.'));
      if (briefing?.diagnostics) {
        wrap.appendChild(safeEl('p', 'intel-proof-line', briefing.diagnostics.summary));
      }
      const link = safeEl('a', 'intel-proof-link', 'Open Activity Log ->');
      link.setAttribute('href', '#/activity-log');
      wrap.appendChild(link);
      return wrap;
    }

    handleSearch(query, mode) {
      this._lastQuery = { query, mode };
      const trimmed = (query || '').trim();
      if (!trimmed) {
        this._resetMarketPrompt();
        this._resetModulePrompt();
        return;
      }

      /* Search is the unified launcher: results open in the domain that owns
         them, switching the visible workspace so the commander lands on the
         answer rather than scrolling. */
      if (mode === 'commodity') {
        this._setDomain('commodities');
        this._renderCommodityResults(trimmed);
        return;
      }
      if (mode === 'module') {
        this._setDomain('modules');
        this._renderModuleResults(trimmed);
        return;
      }

      this._setDomain(mode === 'station' ? 'station' : 'system');
      this._focusBriefForSearch(mode, trimmed);
    }

    _renderCommodityResults(query) {
      const panel = document.getElementById('intel-market-search');
      if (!panel) return;
      this._resetModulePrompt();
      if (_localSurfaces?.updateMarketSearchResults) {
        _localSurfaces.updateMarketSearchResults(panel, this._lastLocalContext?.marketSearch, query);
      } else {
        const results = panel.querySelector('.local-market-results');
        results?.replaceChildren(safeEl('p', 'local-market-empty',
          'Market Search uses local Market.json only. Local surface renderer unavailable.'));
      }
      this._focusPanel(panel);
    }

    _renderModuleResults(query) {
      const panel = document.getElementById('intel-module-search');
      const results = panel?.querySelector('.local-module-results');
      if (!panel || !results) return;
      this._resetMarketPrompt();
      results.replaceChildren();

      const expandedQuery = _localContextVM?.expandModuleQuery
        ? _localContextVM.expandModuleQuery(query)
        : query.toLowerCase();
      const q = expandedQuery.toLowerCase();

      /* Prefer station outfitting snapshot over current loadout. */
      const outfitting = _localContextVM?.deriveOutfittingModules
        ? _localContextVM.deriveOutfittingModules(this._lastEconomic)
        : null;

      if (outfitting?.available) {
        const rows = outfitting.modules.filter((entry) => entry.haystack.includes(q)).slice(0, 30);
        if (rows.length === 0) {
          results.appendChild(safeEl('p', 'local-module-deferred',
            `No match for "${query}" in the local station outfitting snapshot.`));
        } else {
          const scope = safeEl('p', 'local-module-scope', outfitting.summary);
          results.appendChild(scope);
          const table = safeEl('div', 'intel-module-results-table');
          const header = safeEl('div', 'intel-module-results-row intel-module-results-row--header');
          ['Module', 'Buy Price'].forEach((label) => {
            header.appendChild(safeEl('span', 'intel-module-results-cell', label));
          });
          table.appendChild(header);
          rows.forEach((entry) => {
            const row = safeEl('div', 'intel-module-results-row');
            row.appendChild(safeEl('span', 'intel-module-results-cell intel-module-results-name', entry.display));
            row.appendChild(safeEl('span', 'intel-module-results-cell',
              entry.buyPrice != null ? `${entry.buyPrice.toLocaleString('en-US')} cr` : 'Unknown'));
            table.appendChild(row);
          });
          results.appendChild(table);
        }
        this._focusPanel(panel);
        return;
      }

      /* No outfitting snapshot — show honest unavailable state. */
      results.appendChild(safeEl('p', 'local-module-deferred',
        'Local outfitting snapshot not loaded. Open Outfitting at a station to populate local module availability.'));
      this._focusPanel(panel);
    }

    _modeLabel(mode) {
      switch (mode) {
        case 'commodity': return 'Commodity';
        case 'module':    return 'Module';
        case 'station':   return 'Station';
        case 'system':    return 'System';
        default:          return 'Search';
      }
    }

    _matchSnapshot(query, mode) {
      const q = query.toLowerCase();
      const matches = [];

      if (mode === 'commodity' && this._lastLocalContext?.marketSearch) {
        const rows = _localContextVM.filterMarketItems(this._lastLocalContext.marketSearch, query).slice(0, 20);
        rows.forEach((item) => {
          matches.push({
            label: item.displayName,
            value: item.sellPrice != null ? `Sell ${item.sellPrice}` : (item.buyPrice != null ? `Buy ${item.buyPrice}` : 'Unknown'),
            context: this._lastLocalContext.marketSearch.stationName || 'Current local market snapshot',
          });
        });
      } else if (mode === 'commodity' && this._lastEconomic) {
        const items = Array.isArray(this._lastEconomic?.market?.items) ? this._lastEconomic.market.items : [];
        items.forEach((item) => {
          const name = (item?.name || '').toString();
          if (name.toLowerCase().includes(q)) {
            matches.push({
              label: name,
              value: item?.sell_price != null ? `Sell ${item.sell_price}` : (item?.buy_price != null ? `Buy ${item.buy_price}` : 'Unknown'),
              context: this._lastEconomic?.market?.station_name || null,
            });
          }
        });
      }

      const sections = Array.isArray(this._lastSnapshot?.sections) ? this._lastSnapshot.sections : [];
      sections.forEach((section) => {
        const facts = Array.isArray(section?.facts) ? section.facts : [];
        facts.forEach((fact) => {
          const value = fact?.value;
          if (value == null) return;
          const haystack = `${fact.label || ''} ${value}`.toLowerCase();
          if (haystack.includes(q)) {
            if (mode === 'system' && !section.id?.includes('system') && !section.id?.includes('galaxy')) return;
            if (mode === 'station' && !section.id?.includes('local') && !fact.field_key?.includes('station')) return;
            if (mode === 'module') return;
            matches.push({
              label: fact.label || fact.field_key || '',
              value: String(value),
              context: section.label || null,
            });
          }
        });
      });

      return matches.slice(0, 20);
    }

    _resetMarketPrompt() {
      const results = document.querySelector('#intel-market-search .local-market-results');
      if (!results) return;
      results.replaceChildren(safeEl('p', 'local-market-empty',
        'Search local commodities in the current station snapshot.'));
    }

    _resetModulePrompt() {
      const results = document.querySelector('#intel-module-search .local-module-results');
      if (!results) return;
      const outfitting = _localContextVM?.deriveOutfittingModules
        ? _localContextVM.deriveOutfittingModules(this._lastEconomic)
        : null;
      const message = outfitting?.available
        ? `Search station-available modules. ${outfitting.moduleCount} modules in local outfitting snapshot.`
        : 'Local outfitting snapshot not loaded. Open Outfitting at a station to populate local module availability.';
      results.replaceChildren(safeEl('p', 'local-module-deferred', message));
    }

    _focusPanel(panel) {
      panel.scrollIntoView?.({ block: 'nearest' });
      panel.setAttribute('tabindex', '-1');
      panel.focus?.({ preventScroll: true });
    }

    _focusBriefForSearch(mode, query) {
      const targetId = mode === 'station' ? 'intel-station-brief' : 'intel-system-brief';
      const target = document.getElementById(targetId);
      if (!target) return;
      const matches = this._matchSnapshot(query, mode);
      let note = target.querySelector('.intel-brief-focus-note');
      if (!note) {
        note = safeEl('p', 'intel-brief-focus-note');
        target.appendChild(note);
      }
      note.textContent = matches.length > 0
        ? `${this._modeLabel(mode)} search is local-only. ${matches.length} known local match${matches.length === 1 ? '' : 'es'} found in this brief.`
        : `${this._modeLabel(mode)} search is local-only. No matching local fact is loaded yet.`;
      this._focusPanel(target);
    }

    _briefShell(kind, title, subtitle) {
      const section = safeEl('section', `local-brief local-brief--${kind}`);
      section.setAttribute('data-local-surface', kind);
      const header = safeEl('header', 'local-brief-header');
      header.appendChild(safeEl('p', 'local-brief-kicker', title));
      header.appendChild(safeEl('h3', 'local-brief-title', title));
      if (subtitle) header.appendChild(safeEl('p', 'local-brief-subtitle', subtitle));
      section.appendChild(header);
      return section;
    }

    _detailDrawer(summary, content, className = 'local-detail-drawer') {
      const drawer = safeEl('details', className);
      drawer.appendChild(safeEl('summary', 'local-detail-summary', summary));
      const body = safeEl('div', 'local-detail-body');
      if (content instanceof Node) body.appendChild(content);
      else if (content !== undefined && content !== null) body.textContent = String(content);
      drawer.appendChild(body);
      return drawer;
    }

    _eventList(title, entries, formatter) {
      const wrap = safeEl('section', 'local-detail-section');
      wrap.appendChild(safeEl('h4', 'local-proof-title', title));
      const rows = Array.isArray(entries) ? entries : [];
      if (!rows.length) {
        wrap.appendChild(safeEl('p', 'local-empty-state', 'Not Loaded'));
        return wrap;
      }
      const list = safeEl('ul', 'local-missing-source-list');
      list.setAttribute('role', 'list');
      rows.forEach((entry) => {
        list.appendChild(safeEl('li', 'local-missing-source-item', formatter(entry)));
      });
      wrap.appendChild(list);
      return wrap;
    }

    _sourceProofDrawer(entry, summary) {
      const wrap = safeEl('section', 'local-proof-entry');
      const chipKey = _sourceProof?.mapSourceIdToChipLabel
        ? _sourceProof.mapSourceIdToChipLabel(entry?.source, entry?.freshness)
        : null;
      if (chipKey && _sourceProof?.createSourceChip) {
        try {
          wrap.appendChild(_sourceProof.createSourceChip(chipKey));
        } catch {
          wrap.appendChild(safeEl('span', 'intel-chip', entry?.source || 'Unknown'));
        }
      }
      if (_sourceProof?.createProofDrawer) {
        wrap.appendChild(_sourceProof.createProofDrawer({
          source: entry?.source,
          timestamp: entry?.event_timestamp,
          freshness: entry?.freshness,
          truthClass: entry?.truth_class,
          caveat: entry?.caveat,
          rawValue: entry?.value ?? entry?.topic ?? entry?.event_type ?? entry?.fallback,
        }, { summary }));
      } else {
        wrap.appendChild(this._factList([
          { label: 'Source', value: entry?.source || 'Unknown' },
          { label: 'Observed', value: entry?.event_timestamp || 'Unknown' },
          { label: 'Freshness', value: entry?.freshness || 'Unknown' },
          { label: 'Truth class', value: entry?.truth_class || 'Unknown' },
        ], 'local-proof-list'));
      }
      return wrap;
    }

    _valueOrFallback(value, fallback) {
      if (value === null || value === undefined || value === '') {
        return fallback || 'Unknown';
      }
      return String(value);
    }

    _buildGalaxyBriefSurface(briefing) {
      const galaxy = (briefing.sectionsSummary || []).find((entry) => entry.id === 'galaxy');
      const surface = safeEl('section', 'local-brief local-brief--galaxy');
      surface.id = 'intel-galaxy-brief';
      surface.setAttribute('data-local-surface', 'galaxy');
      const header = safeEl('header', 'local-brief-header');
      header.appendChild(safeEl('p', 'local-brief-kicker', 'Galaxy Brief'));
      header.appendChild(safeEl('h3', 'local-brief-title', 'Galaxy Brief'));
      header.appendChild(safeEl('p', 'local-brief-subtitle',
        'Local-only context; no galaxy-level provider is loaded.'));
      surface.appendChild(header);
      surface.appendChild(this._factList([
        { label: 'Scope', value: 'Current local context' },
        { label: 'Galaxy facts', value: galaxy?.factCount ? String(galaxy.factCount) : 'Not loaded' },
        { label: 'External intel', value: 'Disabled' },
      ]));
      return surface;
    }

    _factList(rows, className = 'local-pilot-list') {
      const list = safeEl('dl', className);
      (rows || []).forEach((entry) => {
        list.appendChild(safeEl('dt', `${className}-label`, entry.label));
        list.appendChild(safeEl('dd', `${className}-value`, entry.value));
      });
      return list;
    }

    _fallbackWorkPanel(id, title, summary, owner) {
      const panel = safeEl('section', `local-brief local-brief--${owner} intel-work-panel`);
      panel.id = id;
      panel.setAttribute('data-intel-search-owner', owner);
      panel.setAttribute('data-local-surface', owner);
      const header = safeEl('header', 'local-brief-header');
      header.appendChild(safeEl('p', 'local-brief-kicker', title));
      header.appendChild(safeEl('h3', 'local-brief-title', title));
      header.appendChild(safeEl('p', 'local-brief-subtitle', summary));
      panel.appendChild(header);
      const results = safeEl('section', owner === 'market' ? 'local-market-results' : 'local-module-results');
      results.setAttribute('aria-live', 'polite');
      results.appendChild(safeEl('p', owner === 'market' ? 'local-market-empty' : 'local-module-deferred', summary));
      panel.appendChild(results);
      return panel;
    }

    _localActionHandlers() {
      return {
        'open-cargo': () => this._stageOperations('trading'),
        'open-station': () => this._stageOperations('station'),
        'search-sell-prices': () => this._focusMarketSearchFromCargo(),
        'open-market-search': () => this._focusMarketSearch(),
        'compare-current-station': () => this._focusMarketSearchFromCargo(),
        'open-market-intel': () => this._focusMarketSearch(),
        'open-module-search': () => this._focusModuleSearch(),
      };
    }

    _stageOperations(operation) {
      try {
        window.localStorage?.setItem('omnicovas.manualOperation', operation);
      } catch { /* localStorage unavailable; route handoff still works */ }
      const operationsHash = '#/operations';
      if (window.location.hash !== operationsHash) {
        window.location.hash = operationsHash;
      }
      if (typeof window.Shell?.navigate === 'function') {
        window.Shell.navigate(operationsHash);
      }
    }

    _focusMarketSearch() {
      document.querySelector('.search-panel-mode[data-mode="commodity"]')?.click?.();
      document.querySelector('.search-panel')?.scrollIntoView?.({ block: 'start' });
      document.querySelector('.search-panel-input')?.focus?.();
    }

    _focusMarketSearchFromCargo() {
      const first = this._lastLocalContext?.cargoHold?.inventory?.find?.((item) => item.count > 0);
      document.querySelector('.search-panel-mode[data-mode="commodity"]')?.click?.();
      const input = document.querySelector('.search-panel-input');
      if (input && first?.searchQuery) input.value = first.searchQuery;
      document.querySelector('.search-panel-submit')?.click?.();
      document.querySelector('.search-panel')?.scrollIntoView?.({ block: 'start' });
      input?.focus?.();
    }

    _focusModuleSearch() {
      const moduleTab = document.querySelector('.search-panel-mode[data-mode="module"]');
      moduleTab?.click?.();
      const target = document.getElementById('intel-module-search');
      target?.scrollIntoView?.({ block: 'start' });
      document.querySelector('.search-panel-input')?.focus?.();
    }

    _fallbackBriefCard(title, summary, id) {
      const card = safeEl('article', 'support-card support-card--empty');
      if (id) card.id = id;
      card.appendChild(safeEl('h3', 'support-card-title', title));
      card.appendChild(safeEl('p', 'support-card-summary', summary));
      return card;
    }
  }

  function init() {
    new IntelController();
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }

  globalThis.__intelExports = { IntelController };
})();
