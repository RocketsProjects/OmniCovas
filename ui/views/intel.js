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
  /* Phase 13 Intel terminal core — local flight-recorder history. */
  const JOURNAL_SEARCH_PATH = '/intel/journal/search';
  const JOURNAL_EVENT_TYPES_PATH = '/intel/journal/event-types';
  const SESSIONS_PATH = '/intel/sessions';
  const SYSTEM_NOTES_PATH = '/system-notes';
  const KNOWLEDGE_ENTITY_PATH = '/knowledge/entity';
  const HISTORY_SYSTEMS_PATH = '/intel/history/systems';
  const HISTORY_STATIONS_PATH = '/intel/history/stations';
  const EXPLORATION_SYSTEMS_PATH = '/intel/history/exploration/systems';
  const EXPLORATION_EARNINGS_PATH = '/intel/history/exploration/earnings';
  const EXPLORATION_BIOLOGY_PATH = '/intel/history/exploration/biology';
  const EXPLORATION_TRIPS_PATH = '/intel/history/exploration/trips';
  const REFERENCE_LIBRARY_PATH = '/intel/reference';
  const CAMPAIGN_FACTS_PATH = '/intel/campaign/facts';
  const MEMORY_STATUS_PATH = '/memory/status';
  const MEMORY_OBSERVED_PATH = '/memory/observed';
  /* GKI-04: Commander Context and what is documented there. */
  const INTELLIGENCE_CONTEXT_PATH = '/knowledge/intelligence/context';

  let _primitives = null;
  let _briefingVM = null;
  let _localContextVM = null;
  let _localSurfaces = null;
  let _sourceProof = null;
  let _displayNames = null;

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

  const displayNamesPromise = import('../utils/display-names.js')
    .then((m) => { _displayNames = m; return m; })
    .catch((err) => { console.error('[intel] Failed to load display names:', err); return null; });

  /* GKI-03 Galactic Atlas. Loaded and fetched only when the Atlas domain is
     opened. Its state lives at module scope, like inbound handoffs, so a
     re-render or a return from Navigation restores the same entry. */
  let _atlas = null;
  let atlasInstance = null;
  let atlasActivator = null;
  const atlasState = {};
  const atlasPromise = import('../components/galactic-atlas.js')
    .then((m) => { _atlas = m; return m; })
    .catch((err) => { console.error('[intel] Failed to load Galactic Atlas:', err); return null; });
  import('../view-models/galactic-atlas.js')
    .then((m) => {
      const saved = m.rememberedAtlas();
      if (saved && !atlasState.selected) {
        Object.assign(atlasState, {
          selected: saved.selected || null,
          category: saved.category || 'all',
          search: saved.search || '',
        });
      }
    })
    .catch(() => {});

  /* GKI-07 Living Galactic Historian and Commander Chronicle: the Chronicle
     domain, and the "Your record" card in the Atlas inspector. Module-scope
     state, like the Atlas, so a re-render or a handoff keeps the same view. */
  let _historian = null;
  let chronicleInstance = null;
  let chronicleActivator = null;
  const chronicleState = {};
  /* Atlas record cards, by entity id. Dropped whenever the Chronicle changes
     or the commander does, so a card never shows another commander's record. */
  const recordCache = {};
  const historianPromise = import('../components/galactic-historian.js')
    .then((m) => { _historian = m; return m; })
    .catch((err) => { console.error('[intel] Failed to load the Historian:', err); return null; });
  const CHRONICLE_EVENTS = ['CHRONICLE_RECORDED', 'CHRONICLE_CLEARED', 'Commander', 'LoadGame', 'NewCommander'];

  /* GKI-04 Galactic Intelligence: "Documented here" in the System and Station
     briefs. The records open in the Atlas through a route handoff, so the
     return link leads back to the brief the Commander was reading. */
  let _intelligence = null;
  const intelligencePromise = import('../components/galactic-intelligence.js')
    .then((m) => { _intelligence = m; return m; })
    .catch((err) => { console.error('[intel] Failed to load Galactic Intelligence:', err); return null; });

  let _sourceClass = null;
  const sourceClassPromise = import('../utils/source-class.js')
    .then((m) => { _sourceClass = m; return m; })
    .catch((err) => { console.error('[intel] Failed to load source classes:', err); return null; });

  function getRoot() { return document.getElementById('intel-root'); }

  /* Escape a value for safe interpolation into an attribute selector. Handoff
     payloads are commander/route-derived text, so they never reach a selector
     unescaped. */
  function cssAttrValue(value) {
    const text = String(value == null ? '' : value);
    return typeof CSS !== 'undefined' && typeof CSS.escape === 'function'
      ? CSS.escape(text)
      : text.replace(/["\\]/g, '\\$&');
  }

  /* Switch the visible Intel domain purely from the DOM contract, without
     needing a controller instance. Mirrors IntelController._setDomain so both
     entry points produce identical state. */
  function setDomainOnRoot(domain) {
    const root = getRoot();
    if (!root) return;
    root.querySelectorAll('.intel-domain-panel').forEach((panel) => {
      const match = panel.getAttribute('data-intel-domain-panel') === domain;
      panel.hidden = !match;
      panel.classList.toggle('is-active', match);
    });
    const nav = root.querySelector('.intel-domain-tabs');
    window.Uiv3Frame?.setUiv3TabSelection(nav, domain, {
      selector: '.intel-domain-tab',
      valueAttribute: 'data-intel-domain',
    });
    if (domain === 'atlas') atlasActivator?.();
    if (domain === 'chronicle') chronicleActivator?.();
  }

  /* Apply a RouteTransferIntent addressed to /intel: select the named domain
     workspace and, for the search workspace, the named search mode.
     `switchDomain` is injected so a controller can keep its own
     `_activeDomain` in sync when one is available. */
  /* The domain requested by the most recent inbound handoff.
     A handoff can land before, during or after the controller's async render.
     Without this, a render completing after the switch would call
     `_setDomain(this._activeDomain || 'system')` and silently undo it — which
     is exactly what the live Commander journey showed while the unit tests
     passed. Cleared once a render has honoured it. */
  let pendingTransferDomain = null;

  function applyIntelTransferIntent(root, intent, switchDomain) {
    const sectionId = String(intent.targetSectionId || '');
    const domain = sectionId.startsWith('intel-domain-')
      ? sectionId.slice('intel-domain-'.length)
      : '';

    if (!domain) return false;
    if (!root.querySelector(`[data-intel-domain-panel="${cssAttrValue(domain)}"]`)) {
      return false;
    }

    pendingTransferDomain = domain;
    /* A return from Navigation or Materials names the Atlas entry it left. */
    if (domain === 'atlas' && intent.targetEntityId) {
      atlasState.selected = String(intent.targetEntityId);
    }
    /* A Chronicle handoff (from the Atlas, a briefing or a return) names the
       entry to bring into view once the Chronicle has rendered. */
    if (domain === 'chronicle') {
      chronicleState.focusEntity = intent.targetEntityId ? String(intent.targetEntityId) : null;
    }
    switchDomain(domain);
    if (domain === 'atlas' && intent.targetEntityId) {
      atlasInstance?.select(atlasState.selected);
    }
    if (domain === 'chronicle' && intent.targetEntityId) {
      chronicleInstance?.focus(String(intent.targetEntityId));
    }

    const mode = String(intent.targetEntityId || '');
    if (domain === 'search' && mode) {
      root.querySelector(`.search-panel-mode[data-mode="${cssAttrValue(mode)}"]`)?.click?.();

      /* Phase 14 R2-4: Operations no longer runs its own commodity search, so
         a cargo-aware lookup arrives here as a handoff carrying the commodity
         in `targetQuery`. Running it means the Commander lands on the answer
         they asked for instead of an empty search box — the capability the
         removed Operations search box used to provide. `targetLabel` is NOT
         used for this: it is already the human label for the target. */
      const query = String(intent.targetQuery || '').trim();
      if (query) {
        const input = root.querySelector('.search-panel-input');
        if (input) {
          input.value = query;
          root.querySelector('.search-panel-submit')?.click?.();
        }
      }
    }

    return true;
  }

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
      this._lastLocalContextRaw = null;
      this._lastBgsFacts = null;
      this._lastPowerplayFacts = null;
      this._lastJournalSearch = null;
      this._lastEventTypes = null;
      this._lastVisitedSystems = null;
      this._lastVisitedStations = null;
      this._lastMemoryStatus = null;
      this._lastMemoryRecords = null;
      this._memoryQuery = { category: '', profile_key: '', q: '', limit: 50, offset: 0 };
      this._memorySearchBusy = false;
      this._lastQuery = null;
      this._activeDomain = 'system';
      this._boundHandler = () => { this.fetchAndRender(); };
      /* Commander Memory is owned by Privacy but displayed here. Pausing or
         deleting there left Observed Galaxy asserting "Remembering locally"
         over records that no longer described the truth, so re-entering Intel
         re-reads the Memory slice. */
      this._boundRouteHandler = (event) => {
        if (event?.detail?.route !== '/intel') return;
        this.refreshMemorySlice();
      };
      /* Inbound handoffs are handled at module scope (see the
         `route-transfer-started` listener below), not per instance: the
         instance that owns the rendered DOM is not reliably the instance that
         would receive an instance-bound listener. */
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
        window.OmniEvents.addEventListener('route-changed', this._boundRouteHandler);
      }
      if (this.apiBase) {
        /* Paint an immediate honest loading state so the route root is
           never an empty zero-height surface while the first local fetch
           batch is in flight (PB11-01 startup honesty; also removes the
           cold-load render race seen in runtime smoke). */
        this.renderLoading();
        this.fetchAndRender();
      } else {
        this.renderWaiting();
      }
    }

    renderLoading() {
      const root = getRoot();
      if (!root) return;
      root.replaceChildren();
      const wrap = safeEl('section', 'intel-waiting');
      const h1 = safeEl('h1', 'intel-waiting-title', 'Intel');
      h1.id = 'intel-title';
      wrap.append(h1, safeEl('p', 'intel-waiting-message',
        'Loading local intelligence…'));
      root.appendChild(wrap);
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
        journalSearch,
        eventTypes,
        visitedSystems,
        visitedStations,
        sessions,
        explorationSystems,
        explorationEarnings,
        biologicalSignals,
        referenceLibrary,
        campaignFacts,
        explorationTrips,
        intelligenceContext,
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
        this.fetchJson(`${base}${JOURNAL_SEARCH_PATH}?limit=20`).catch((err) => {
          console.warn('Recorded event search unavailable:', err);
          return null;
        }),
        this.fetchJson(`${base}${JOURNAL_EVENT_TYPES_PATH}?limit=24`).catch((err) => {
          console.warn('Recorded event-type catalog unavailable:', err);
          return null;
        }),
        this.fetchJson(`${base}${HISTORY_SYSTEMS_PATH}?limit=25`).catch((err) => {
          console.warn('Observed systems catalog unavailable:', err);
          return null;
        }),
        this.fetchJson(`${base}${HISTORY_STATIONS_PATH}?limit=25`).catch((err) => {
          console.warn('Observed stations catalog unavailable:', err);
          return null;
        }),
        this.fetchJson(`${base}${SESSIONS_PATH}?limit=25`).catch((err) => {
          console.warn('Session timeline unavailable:', err);
          return null;
        }),
        this.fetchJson(`${base}${EXPLORATION_SYSTEMS_PATH}?limit=50`).catch((err) => {
          console.warn('Exploration history unavailable:', err);
          return null;
        }),
        this.fetchJson(`${base}${EXPLORATION_EARNINGS_PATH}`).catch((err) => {
          console.warn('Exploration earnings unavailable:', err);
          return null;
        }),
        this.fetchJson(`${base}${EXPLORATION_BIOLOGY_PATH}?limit=50`).catch((err) => {
          console.warn('Biological signals unavailable:', err);
          return null;
        }),
        this.fetchJson(`${base}${REFERENCE_LIBRARY_PATH}`).catch((err) => {
          console.warn('Reference library unavailable:', err);
          return null;
        }),
        this.fetchJson(`${base}${CAMPAIGN_FACTS_PATH}?limit=25`).catch((err) => {
          console.warn('Campaign facts unavailable:', err);
          return null;
        }),
        this.fetchJson(`${base}${EXPLORATION_TRIPS_PATH}?limit=25`).catch((err) => {
          console.warn('Exploration trips unavailable:', err);
          return null;
        }),
        this.fetchJson(`${base}${INTELLIGENCE_CONTEXT_PATH}`).catch((err) => {
          console.warn('Galactic Intelligence context unavailable:', err);
          return null;
        }),
      ]);

      /* Local-context observation is one input to Commander Memory. Fetch
         Memory after that request settles so the initial Observed Galaxy can
         include the snapshot just observed by the backend instead of racing it. */
      const [memoryStatus, memoryRecords] = await Promise.all([
        this.fetchJson(`${base}${MEMORY_STATUS_PATH}`).catch((err) => {
          console.warn('Commander Memory status unavailable:', err);
          return null;
        }),
        this.fetchJson(`${base}${MEMORY_OBSERVED_PATH}?limit=50&offset=0`).catch((err) => {
          console.warn('Observed Galaxy unavailable:', err);
          return null;
        }),
      ]);

      await Promise.all([
        primitivesPromise,
        briefingPromise,
        localContextPromise,
        localSurfacesPromise,
        sourceProofPromise,
        displayNamesPromise,
        sourceClassPromise,
        intelligencePromise,
      ]);
      if (!_primitives || !_briefingVM) {
        this.renderError('Command primitives unavailable.');
        return;
      }

      this._lastSnapshot = snapshot;
      this._lastEconomic = economicSnapshot;
      this._lastLocalContext = _localContextVM?.deriveLocalContext(localContextSnapshot) || null;
      /* Raw payload kept alongside the derived VM so provenance-bearing
         snapshot nodes (shipyard, station services) render with their own
         freshness/caveat fields intact. */
      this._lastLocalContextRaw = localContextSnapshot || null;
      this._lastBgsFacts = bgsFacts;
      this._lastPowerplayFacts = powerplayFacts;
      this._lastJournalSearch = journalSearch;
      this._lastEventTypes = eventTypes;
      this._lastVisitedSystems = visitedSystems;
      this._lastVisitedStations = visitedStations;
      this._lastSessions = sessions;
      this._lastExploration = explorationSystems;
      this._lastExplorationEarnings = explorationEarnings;
      this._lastBiologicalSignals = biologicalSignals;
      this._lastReference = referenceLibrary;
      this._lastCampaignFacts = campaignFacts;
      this._lastExplorationTrips = explorationTrips;
      this._lastIntelligence = intelligenceContext;
      this._lastMemoryStatus = memoryStatus;
      this._lastMemoryRecords = memoryRecords;
      this.render();
    }

    /* Re-read only Commander Memory. A full fetchAndRender would refetch every
       Intel domain and discard the Commander's current search on arrival. */
    async refreshMemorySlice() {
      const base = this.apiBase;
      if (!base || !this._lastSnapshot) return;
      const query = this._memoryQuery || {};
      const params = new URLSearchParams({
        limit: String(query.limit || 50),
        offset: String(query.offset || 0),
      });
      if (query.category) params.set('category', query.category);
      if (query.profile_key) params.set('profile_key', query.profile_key);
      if (query.q) params.set('q', query.q);
      const [status, records] = await Promise.all([
        this.fetchJson(`${base}${MEMORY_STATUS_PATH}`).catch(() => null),
        this.fetchJson(`${base}${MEMORY_OBSERVED_PATH}?${params.toString()}`)
          .catch(() => null),
      ]);
      this._lastMemoryStatus = status;
      this._lastMemoryRecords = records;
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
      /* R0-1: a bare count beside the current station read as that station's
         market. Name the snapshot's station whenever it is historical. */
      if (briefing.economic?.itemCount) {
        spineItems.push({
          id: 'local-market',
          label: briefing.economic.isStale
            ? `Market rows (${briefing.economic.stationName || 'station unknown'}, historical)`
            : 'Local market rows',
          value: String(briefing.economic.itemCount),
        });
      }
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
        this._domainPanel('atlas', this._buildAtlasWorkspace()),
        this._domainPanel('chronicle', this._buildChronicleWorkspace()),
        this._domainPanel('search', this._buildSearchWorkspace(createSearchPanel, INTEL_SEARCH_MODES)),
        this._domainPanel('history', this._buildHistoryWorkspace()),
        this._domainPanel('memory', this._buildObservedGalaxyWorkspace()),
        this._domainPanel('exploration', this._buildExplorationWorkspace()),
        this._domainPanel('commodities', this._buildMarketWorkspace(briefing)),
        this._domainPanel('modules', this._buildModuleWorkspace(briefing)),
        this._domainPanel('bgs', this._buildBgsWorkspace()),
        this._domainPanel('powerplay', this._buildPowerplayWorkspace()),
        this._domainPanel('ships', this._buildShipsWorkspace()),
        this._domainPanel('services', this._buildServicesWorkspace()),
        this._domainPanel('campaign', this._buildCampaignWorkspace()),
        this._domainPanel('reference', this._buildReferenceWorkspace()),
      );
      wrap.appendChild(workspace);

      /* Raw lineage stays available as deeper disclosure below the workspace —
         never the first impression. */
      wrap.appendChild(createDetailDrawer({
        summary: 'Details',
        content: this.buildKnownFactsDetail(briefing.sectionsSummary),
      }));

      wrap.appendChild(createProofToggle(this.buildProofPanel(briefing), 'Source'));

      /* The Shell's arrival banner belongs to the handoff, not to this render:
         a refresh (Commander Memory on route entry, a bridge reconnect) must
         not erase it and its return link. A newer handoff replaces it below. */
      const arrival = root.querySelector(':scope > .route-arrival-banner');
      root.replaceChildren(wrap);
      if (arrival) root.prepend(arrival);
      /* A handoff that arrived while this render was in flight wins over the
         controller's previous domain, otherwise the render undoes it. */
      this._setDomain(pendingTransferDomain || this._activeDomain || 'system');
      this._applyInboundRouteTransfer(root);
      pendingTransferDomain = null;
    }

    /* PB10-R5 (Phase 10 reconciliation): consume an inbound RouteTransferIntent
       so a Dashboard handoff arrives at the workspace it was labelled for
       instead of the default System brief.

       `targetSectionId` names the domain panel (`intel-domain-<domain>`) and
       `targetEntityId` optionally names the search mode. After applying the
       domain, `applyRouteTransferArrival` renders the arrival banner and the
       return link back to the originating route. */
    _applyInboundRouteTransfer(rootOrNull, intentOverride) {
      const root = rootOrNull || getRoot();
      if (!root) return;

      const intent = intentOverride
        || (typeof window.Shell?.getRouteTransferIntent === 'function'
          ? window.Shell.getRouteTransferIntent('/intel')
          : null);
      if (!intent) return;

      applyIntelTransferIntent(root, intent, (domain) => this._setDomain(domain));

      if (typeof window.Shell?.applyRouteTransferArrival === 'function') {
        window.Shell.applyRouteTransferArrival('/intel', root);
      }
    }

    /* One domain workspace panel. All panels live in the DOM; only the active
       one is shown so domain selection swaps the visible workspace. */
    _domainPanel(id, content) {
      const panel = safeEl('section', 'intel-domain-panel');
      panel.id = `intel-domain-${id}`;
      panel.setAttribute('data-intel-domain-panel', id);
      panel.setAttribute('role', 'tabpanel');
      panel.setAttribute('aria-labelledby', `intel-domain-tab-${id}`);
      /* Every domain now owns a tab, so the labelledby above resolves. The
         aria-label stays as the fallback for any future panel added ahead of
         its tab — an unresolvable labelledby leaves a panel unnamed. */
      panel.setAttribute(
        'aria-label',
        String(id).replace(/[-_]/g, ' ').replace(/^\w/, (c) => c.toUpperCase()),
      );
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
      const nav = root.querySelector('.intel-domain-tabs');
      window.Uiv3Frame?.setUiv3TabSelection(nav, id, {
        selector: '.intel-domain-tab',
        valueAttribute: 'data-intel-domain',
      });
      if (id === 'atlas') this._ensureAtlas();
      if (id === 'chronicle') this._ensureChronicle();
    }

    /* JSON writes for the Chronicle (GKI-07): the Commander's own confirmations
       and saved stories. */
    async sendJson(method, path, body) {
      const base = this.apiBase;
      if (!base) throw new Error('bridge unavailable');
      const response = await fetch(`${base}${path}`, {
        method,
        headers: body === undefined ? {} : { 'Content-Type': 'application/json' },
        body: body === undefined ? undefined : JSON.stringify(body),
      });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      return response.json();
    }

    /* GKI-07 Commander Chronicle: where the Commander has been, by evidence
       class, with the Historian's "Here and now". Mounted the first time it is
       shown and re-read every time it is opened. */
    _buildChronicleWorkspace() {
      const section = safeEl('section', 'intel-chronicle-workspace');
      section.setAttribute('aria-label', 'Commander Chronicle');
      section.appendChild(safeEl('p', 'intel-workspace-lead',
        'Your own record of the galaxy: where the Journal showed you, what you confirmed, your Codex discoveries and journeys. Kept on this machine, per commander.'));
      this._chronicleSection = section;
      chronicleActivator = () => this._ensureChronicle();
      return section;
    }

    _ensureChronicle() {
      const section = this._chronicleSection;
      const base = this.apiBase;
      if (!section || !base) return;
      const mount = () => {
        if (!_historian) return;
        if (!chronicleInstance) {
          chronicleInstance = _historian.createChronicle({
            state: chronicleState,
            fetchJson: (path) => this.fetchJson(`${base}${path}`),
            sendJson: (method, path, body) => this.sendJson(method, path, body),
            startTransfer: (intent) => window.Shell?.startRouteTransfer?.(intent),
            events: window.OmniEvents,
          });
        }
        if (chronicleInstance.element.parentNode !== section) section.appendChild(chronicleInstance.element);
        chronicleInstance.load();
      };
      if (_historian) mount();
      else historianPromise.then(mount);
    }

    /* GKI-03 Galactic Atlas: places, people, organizations and events from the
       bundled knowledge packs. The panel is mounted the first time it is shown;
       a later Intel re-render remounts it from the same module-scope state. */
    _buildAtlasWorkspace() {
      const section = safeEl('section', 'intel-atlas-workspace');
      section.setAttribute('aria-label', 'Galactic Atlas');
      section.appendChild(safeEl('p', 'intel-workspace-lead',
        'Documented places, people and events of the galaxy, with their sources. Works offline.'));
      this._atlasSection = section;
      atlasActivator = () => this._ensureAtlas();
      return section;
    }

    _ensureAtlas() {
      const section = this._atlasSection;
      const base = this.apiBase;
      if (!section || !base || section.querySelector('.atlas')) return;
      const fetchJson = (path) => this.fetchJson(`${base}${path}`);
      const startTransfer = (intent) => window.Shell?.startRouteTransfer?.(intent);
      const mount = () => {
        if (!_atlas || section.querySelector('.atlas')) return;
        atlasInstance = _atlas.createGalacticAtlas({
          state: atlasState,
          fetchJson,
          startTransfer,
          /* GKI-07: the Commander's own record beside each entry. */
          recordCard: (entry) => (_historian && entry?.entity?.id
            ? _historian.createRecordCard({
              entityId: entry.entity.id,
              name: entry.entity.name,
              fetchJson,
              sendJson: (method, path, body) => this.sendJson(method, path, body),
              startTransfer,
              cache: recordCache,
            }).element
            : null),
        });
        section.appendChild(atlasInstance.element);
      };
      if (_atlas && _historian) mount();
      else Promise.all([atlasPromise, historianPromise]).then(mount);
    }

    /* PB-UIV3-HARMONY §4·3 domain tab row. Implemented domains switch their
       workspace; future domains are clickable too and open an honest, compact
       reserved workspace card (never a dead decorative label). No provider
       activation, no fabricated data. */
    buildDomainScaffold() {
      const nav = safeEl('nav', 'intel-domain-tabs route-subnav');
      nav.setAttribute('role', 'tablist');
      nav.setAttribute('aria-label', 'Intel fact domains');

      const DOMAINS = [
        { id: 'system', label: 'System' },
        { id: 'station', label: 'Station' },
        { id: 'galaxy', label: 'Galaxy' },
        { id: 'atlas', label: 'Atlas' },
        { id: 'chronicle', label: 'Chronicle' },
        { id: 'search', label: 'Search' },
        { id: 'history', label: 'History' },
        { id: 'memory', label: 'Observed Galaxy' },
        { id: 'exploration', label: 'Exploration' },
        { id: 'commodities', label: 'Commodities' },
        { id: 'modules', label: 'Modules' },
        { id: 'ships', label: 'Ships' },
        { id: 'services', label: 'Services' },
        { id: 'bgs', label: 'BGS' },
        { id: 'powerplay', label: 'Powerplay' },
        { id: 'campaign', label: 'Campaign' },
        { id: 'reference', label: 'Reference' },
      ];

      const active = this._activeDomain || 'system';
      DOMAINS.forEach((domain) => {
        const tab = safeEl('button', 'intel-domain-tab', domain.label);
        tab.setAttribute('type', 'button');
        tab.setAttribute('role', 'tab');
        tab.setAttribute('data-intel-domain', domain.id);
        tab.id = `intel-domain-tab-${domain.id}`;
        tab.setAttribute('aria-controls', `intel-domain-${domain.id}`);
        nav.appendChild(tab);
      });
      window.Uiv3Frame.bindUiv3TabList(nav, {
        selector: '.intel-domain-tab',
        valueAttribute: 'data-intel-domain',
        activeValue: active,
        onActivate: (id) => this._setDomain(id),
      });

      return nav;
    }

    /* ── Domain workspace builders ───────────────────────────────────── */

    _buildSystemWorkspace(briefing) {
      const brief = _localSurfaces && briefing.localContext
        ? _localSurfaces.createSystemBriefSurface(briefing.systemBrief, { id: 'intel-system-brief' })
        : this._fallbackBriefCard('System Brief',
          'No local system context loaded. Jump or load into a system to build a System Brief.',
          'intel-system-brief');
      return this._withDocumentedHere(brief, 'system');
    }

    _buildStationWorkspace(briefing) {
      const brief = _localSurfaces && briefing.localContext
        ? _localSurfaces.createStationBriefSurface(briefing.stationBrief, {
          id: 'intel-station-brief',
          handlers: this._localActionHandlers(),
          showAction: false,
        })
        : this._fallbackBriefCard('Station Brief',
          'No local station context loaded. Dock at a station to build a Station Brief.',
          'intel-station-brief');
      return this._withDocumentedHere(brief, 'station');
    }

    /* GKI-04: the brief plus its "Documented here" section, only when the
       knowledge packs document something here. Nothing is added otherwise, and
       an unavailable pack leaves the brief exactly as it was. */
    _withDocumentedHere(brief, scope) {
      const documented = this._lastIntelligence?.documented;
      const section = _intelligence?.createDocumentedHere(documented, {
        scope,
        onOpen: (row) => this._openDocumented(row, scope),
        /* GKI-07: the Historian and the Commander's own record for this place. */
        onChronicle: () => window.Shell?.startRouteTransfer?.({
          originRoute: '/intel',
          originPackage: scope === 'station' ? 'Station Brief' : 'System Brief',
          originSectionId: `intel-domain-${scope}`,
          originSectionLabel: 'Documented here',
          targetRoute: '/intel',
          targetSectionId: 'intel-domain-chronicle',
          targetEntityId: '',
          targetLabel: 'Commander Chronicle',
          reason: 'What is documented here, who and what is connected, and your own record.',
          returnLabel: scope === 'station' ? 'Back to Station Brief' : 'Back to System Brief',
        }),
      });
      if (!section) return brief;
      const wrap = safeEl('div', 'intel-brief-with-knowledge');
      wrap.append(brief, section);
      return wrap;
    }

    _openDocumented(row, scope) {
      if (!window.Shell?.startRouteTransfer) return;
      window.Shell.startRouteTransfer({
        originRoute: '/intel',
        originPackage: scope === 'station' ? 'Station Brief' : 'System Brief',
        originSectionId: `intel-domain-${scope}`,
        originSectionLabel: 'Documented here',
        targetRoute: '/intel',
        targetSectionId: 'intel-domain-atlas',
        targetEntityId: row.id,
        targetLabel: row.name,
        reason: 'Read the documented record for this place.',
        returnLabel: scope === 'station' ? 'Back to Station Brief' : 'Back to System Brief',
      });
    }

    _buildGalaxyWorkspace(briefing) {
      return this._buildGalaxyBriefSurface(briefing);
    }

    _buildSearchWorkspace(createSearchPanel, INTEL_SEARCH_MODES) {
      const section = safeEl('section', 'intel-search-workspace');
      /* No id here: the enclosing domain panel already owns `intel-domain-search`,
         which is the route-handoff target. Setting it on both produced a
         duplicate id, so every aria and label lookup for it was ambiguous.
         Handoffs still resolve — querySelector finds the panel. */
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

    /* ── Ships domain (PB13-01; LNA-016/020 first slice) ────────────────
       Known shipyard from the local Shipyard.json snapshot. Commander-
       observed local screen snapshot only — never global ship availability,
       and a missing snapshot is never proof no ships are sold. */
    _buildShipsWorkspace() {
      const snap = this._lastLocalContextRaw?.shipyard_snapshot || null;
      const section = safeEl('section', 'intel-ships-workspace');
      section.setAttribute('aria-label', 'Known shipyard');

      if (!snap || snap.freshness === 'not_loaded') {
        section.appendChild(this._fallbackBriefCard(
          'Known Shipyard',
          'No verified local shipyard snapshot. Open a station Shipyard '
          + 'screen in-game to record one — a missing snapshot is not proof '
          + 'no ships are sold.',
          'intel-ships-card',
        ));
        return section;
      }

      const card = safeEl('article', 'support-card intel-ships-card');
      card.id = 'intel-ships-card';
      card.appendChild(safeEl('h3', 'support-card-title', 'Known Shipyard'));
      const where = [snap.station_name, snap.star_system].filter(Boolean).join(' · ');
      const count = snap.ship_count;
      card.appendChild(safeEl('p', 'intel-workspace-lead',
        `${count == null ? 'Unknown' : count} ship${count === 1 ? '' : 's'} observed`
        + `${where ? ` at ${where}` : ''} — commander-observed local snapshot.`));

      const ships = Array.isArray(snap.ships) ? snap.ships : [];
      if (ships.length === 0) {
        card.appendChild(safeEl('p', 'intel-history-caveat',
          'No ship rows recorded in this local snapshot.'));
      } else {
        const list = safeEl('ul', 'intel-ships-list');
        ships.forEach((ship) => {
          const row = safeEl('li', 'intel-ships-row');
          const named = _primitives?.normalizeShipName?.(ship.ship_type);
          row.append(
            safeEl('span', 'intel-ships-name',
              named?.display || ship.ship_type || 'Unknown'),
            safeEl('span', 'intel-ships-price',
              ship.ship_price != null && _primitives?.formatCredits
                ? _primitives.formatCredits(ship.ship_price)
                : (ship.ship_price != null ? String(ship.ship_price) : 'Unknown')),
          );
          list.appendChild(row);
        });
        card.appendChild(list);
      }

      if (snap.freshness === 'stale' && Array.isArray(snap.stale_reasons) && snap.stale_reasons.length) {
        card.appendChild(safeEl('p', 'intel-history-caveat',
          `Stale: ${snap.stale_reasons.join('; ')}.`));
      }
      if (snap.caveat) card.appendChild(safeEl('p', 'intel-history-caveat', snap.caveat));
      section.appendChild(card);
      return section;
    }

    /* ── Services domain (PB13-01; LNA-007 first slice) ─────────────────
       Last-known station services from the local station context. The
       derived VM supplies pretty labels when loaded; raw service keys
       render verbatim otherwise. Availability flags hand off to the
       owning Intel domains — no duplicate search owners. */
    _buildServicesWorkspace() {
      const raw = this._lastLocalContextRaw?.station_services || null;
      const derived = this._lastLocalContext?.stationServices || null;
      const section = safeEl('section', 'intel-services-workspace');
      section.setAttribute('aria-label', 'Known station services');

      const rawServices = Array.isArray(raw?.services) ? raw.services : null;
      const hasAny = (derived?.services?.length || 0) > 0 || (rawServices?.length || 0) > 0;
      if (!hasAny) {
        section.appendChild(this._fallbackBriefCard(
          'Station Services',
          'No station services observed yet. Dock at a station to record its '
          + 'services — a missing observation is not proof of missing services.',
          'intel-services-card',
        ));
        return section;
      }

      const card = safeEl('article', 'support-card intel-services-card');
      card.id = 'intel-services-card';
      card.appendChild(safeEl('h3', 'support-card-title', 'Station Services'));
      const station = this._lastLocalContextRaw?.station_context?.station_name || null;
      card.appendChild(safeEl('p', 'intel-workspace-lead',
        `Last-known services${station ? ` at ${station}` : ''} — from the local `
        + 'station context, not live station truth.'));

      const chips = safeEl('ul', 'intel-services-chips');
      const items = derived?.services?.length
        ? derived.services.map((service) => service.label || service.raw || service.key)
        : rawServices;
      items.forEach((label) => {
        chips.appendChild(safeEl('li', 'intel-services-chip', label || 'Unknown'));
      });
      card.appendChild(chips);

      /* Handoffs to the owning domains when the service was observed. */
      const actions = safeEl('div', 'intel-services-actions');
      const addAction = (label, domain) => {
        const btn = safeEl('button', 'cmd-btn cmd-btn--quiet intel-services-action', label);
        btn.type = 'button';
        btn.addEventListener('click', () => this._setDomain(domain));
        actions.appendChild(btn);
      };
      if (derived?.marketAvailable) addAction('Open Commodities', 'commodities');
      if (derived?.outfittingAvailable) addAction('Open Modules', 'modules');
      if (derived?.shipyardAvailable) addAction('Open Ships', 'ships');
      if (actions.childNodes.length) card.appendChild(actions);

      if (raw?.caveat) card.appendChild(safeEl('p', 'intel-history-caveat', raw.caveat));
      section.appendChild(card);
      return section;
    }

    /* ── Exploration domain (PB13-01; LNA-034 / LNA-035) ────────────────
       A survey record, not a body tally. Elite reports how many bodies a
       system holds (FSSDiscoveryScan.BodyCount) separately from the ones the
       Commander scanned, so coverage is a fact this surface can state:
       "2 of 4 bodies scanned". Where no honk was recorded the total is
       genuinely unknown and is said so — the scanned count is never promoted
       into a total, which would render a barely-touched system as complete
       (the LNA-027 partial-data failure shape). */
    _buildExplorationWorkspace() {
      const payload = this._lastExploration || null;
      const systems = Array.isArray(payload?.systems) ? payload.systems : [];
      const section = safeEl('section', 'intel-exploration-workspace');
      section.setAttribute('aria-label', 'Exploration history');

      if (!systems.length) {
        section.appendChild(this._fallbackBriefCard(
          'Exploration History',
          'No body scans recorded yet. Honk a system and scan a body to build '
          + 'a survey record — nothing recorded here is not proof that nothing '
          + 'was explored before recording began.',
          'intel-exploration-card',
        ));
        return section;
      }

      const trips = this._buildExplorationTripsCard();
      if (trips) section.appendChild(trips);
      section.appendChild(this._buildExplorationEarningsCard());
      const biology = this._buildBiologicalSignalsCard();
      if (biology) section.appendChild(biology);

      const card = safeEl('article', 'support-card intel-exploration-card');
      card.id = 'intel-exploration-card';
      card.appendChild(this._cardHeading('Exploration History', payload?.truth_class));
      card.appendChild(safeEl('p', 'intel-workspace-lead',
        `${systems.length} surveyed system${systems.length === 1 ? '' : 's'} `
        + 'from recorded scans — Commander-observed, newest first.'));

      const list = safeEl('ul', 'intel-exploration-list');
      systems.forEach((row) => {
        const item = safeEl('li', 'intel-exploration-row');
        item.appendChild(safeEl('span', 'intel-exploration-system',
          row.star_system || 'Unknown system'));

        /* Coverage leads, because it is the fact that distinguishes a survey
           from a tally. Unknown total renders as unknown, never as complete. */
        const scanned = Number(row.bodies_scanned ?? 0);
        const total = row.body_count_known ? Number(row.bodies_in_system) : null;
        item.appendChild(safeEl('span', 'intel-exploration-coverage',
          total != null
            ? `${scanned} of ${total} bodies scanned`
            : `${scanned} bodies scanned · system total unknown`));

        const facts = [];
        /* First footfall leads when the evidence is complete — it is the fact
           a commander most wants on arrival. Claimed only when every scanned
           body carried the flag and every one came back undiscovered. */
        if (row.no_prior_discovery_recorded) {
          const flag = safeEl('span', 'intel-exploration-untouched',
            'No prior discovery recorded — first footfall on every scanned body');
          item.appendChild(flag);
        }
        if (row.survey_complete) facts.push('all bodies found');
        if (Number(row.first_discoveries) > 0) {
          facts.push(`${row.first_discoveries} first discovery`
            + (Number(row.first_discoveries) === 1 ? '' : 'ies'));
        }
        if (Number(row.bodies_surface_mapped) > 0) {
          facts.push(`${row.bodies_surface_mapped} surface mapped`);
        }
        if (facts.length) {
          item.appendChild(safeEl('span', 'intel-exploration-facts', facts.join(' · ')));
        }
        if (row.last_scan_at) {
          item.appendChild(safeEl('span', 'intel-exploration-time',
            `Last scan ${row.last_scan_at}`));
        }
        list.appendChild(item);
      });
      card.appendChild(list);

      if (payload?.caveat) {
        card.appendChild(safeEl('p', 'intel-history-caveat', payload.caveat));
      }
      section.appendChild(card);
      return section;
    }

    /* LNA-034 trip timeline. Grouped by recorded session, and the card says
       so in as many words: a session is the only trip boundary the recorder
       knows, and a real expedition may span several rows.

       Credits read "sold on this trip", never "earned" — Frontier's sale
       events do not say which trip gathered the data, so a survey trip that
       banked nothing shows no credits rather than being handed the figure
       from the trip that sold its haul. */
    _buildExplorationTripsCard() {
      const payload = this._lastExplorationTrips || null;
      const trips = Array.isArray(payload?.trips) ? payload.trips : [];
      if (!payload) return null;

      const card = safeEl('article', 'support-card intel-trips-card');
      card.id = 'intel-trips-card';
      card.appendChild(this._cardHeading('Exploration Trips', payload.truth_class));

      if (!trips.length) {
        card.appendChild(safeEl('p', 'intel-workspace-lead',
          'No recorded session has exploration activity yet.'));
        return card;
      }

      card.appendChild(safeEl('p', 'intel-workspace-lead',
        `${trips.length} recorded session${trips.length === 1 ? '' : 's'} with `
        + 'exploration activity — newest first. One row is one session, not '
        + 'necessarily one expedition.'));

      const list = safeEl('ul', 'intel-trips-list');
      trips.forEach((trip) => {
        const item = safeEl('li', 'intel-trip-row');

        const when = trip.started_at ? String(trip.started_at).slice(0, 16).replace('T', ' ') : 'Unknown start';
        const head = safeEl('span', 'intel-trip-when', when);
        /* An unclosed session is reported as unclosed, never as ongoing. */
        if (trip.end_recorded === false) {
          head.appendChild(safeEl('span', 'intel-trip-open', ' · session end not recorded'));
        }
        item.appendChild(head);

        const facts = [];
        const bodies = Number(trip.bodies_scanned || 0);
        if (bodies) facts.push(`${bodies} bod${bodies === 1 ? 'y' : 'ies'} scanned`);
        const firsts = Number(trip.first_discoveries || 0);
        if (firsts) facts.push(`${firsts} first discover${firsts === 1 ? 'y' : 'ies'}`);
        const maps = Number(trip.surface_maps || 0);
        if (maps) facts.push(`${maps} surface map${maps === 1 ? '' : 's'}`);
        const organics = Number(trip.organic_scans || 0);
        if (organics) facts.push(`${organics} organic scan${organics === 1 ? '' : 's'}`);
        if (facts.length) {
          item.appendChild(safeEl('span', 'intel-trip-facts', facts.join(' · ')));
        }

        const travel = [];
        const jumps = Number(trip.jumps || 0);
        if (jumps) travel.push(`${jumps} jump${jumps === 1 ? '' : 's'}`);
        if (trip.jump_distance_ly != null) travel.push(`${trip.jump_distance_ly} ly`);
        const visited = Number(trip.systems_visited || 0);
        if (visited) travel.push(`${visited} system${visited === 1 ? '' : 's'}`);
        if (travel.length) {
          item.appendChild(safeEl('span', 'intel-trip-travel', travel.join(' · ')));
        }

        if (trip.credits_sold_during_trip != null) {
          const credits = _primitives?.formatCredits
            ? _primitives.formatCredits(trip.credits_sold_during_trip)
            : String(trip.credits_sold_during_trip);
          item.appendChild(safeEl('span', 'intel-trip-sold',
            `${credits} sold on this trip — the data may have been gathered on earlier ones`));
        }

        /* Discovery notes: the Commander's own words beside what they found. */
        (trip.notes || []).forEach((note) => {
          item.appendChild(safeEl('span', 'intel-trip-note',
            `${note.star_system}: ${note.note}`));
        });

        list.appendChild(item);
      });
      card.appendChild(list);

      /* Excluded sessions are disclosed so this never reads as the whole
         recorded history. */
      const skipped = Number(payload.sessions_without_exploration || 0);
      if (skipped > 0) {
        card.appendChild(safeEl('p', 'intel-trips-excluded',
          `${skipped} recorded session${skipped === 1 ? '' : 's'} had no `
          + 'exploration activity and are not listed here.'));
      }
      if (payload.caveat) {
        card.appendChild(safeEl('p', 'intel-history-caveat', payload.caveat));
      }
      return card;
    }

    /* Credits actually received — never an estimate of unsold data. The two
       are different claims and are never summed: one is money the Commander
       has, the other is a guess from formulas Frontier rebalances. */
    _buildExplorationEarningsCard() {
      const payload = this._lastExplorationEarnings || null;
      const card = safeEl('article', 'support-card intel-exploration-earnings');
      card.id = 'intel-exploration-earnings';
      card.appendChild(this._cardHeading('Data Sold', payload?.truth_class));

      if (!payload) {
        card.appendChild(safeEl('p', 'intel-workspace-lead',
          'Exploration earnings unavailable — the local flight recorder did not answer.'));
        return card;
      }

      const credits = (value) => (
        value == null
          ? null
          : (_primitives?.formatCredits ? _primitives.formatCredits(value) : String(value))
      );
      const row = (label, slice, extra) => {
        const line = safeEl('div', 'intel-earnings-row');
        line.appendChild(safeEl('span', 'intel-earnings-label', label));
        const amount = credits(slice?.credits_earned);
        line.appendChild(safeEl('span', 'intel-earnings-value',
          /* Never sold is not zero earned. */
          amount === null ? 'None sold yet' : amount));
        const sales = Number(slice?.sales_recorded || 0);
        const detail = [];
        if (sales > 0) detail.push(`${sales} sale${sales === 1 ? '' : 's'}`);
        if (extra) detail.push(extra);
        if (detail.length) {
          line.appendChild(safeEl('span', 'intel-earnings-detail', detail.join(' · ')));
        }
        card.appendChild(line);
      };

      row('Exploration data', payload.exploration);
      const bio = payload.exobiology || {};
      const samples = Number(bio.samples_recorded || 0);
      row('Exobiology data', bio,
        samples > 0
          ? `${samples} sample${samples === 1 ? '' : 's'} · `
            + `${bio.distinct_species_sampled} species`
          : null);

      if (payload.caveat) {
        card.appendChild(safeEl('p', 'intel-history-caveat', payload.caveat));
      }
      return card;
    }

    /* Biological signals. Observed facts lead; candidates are visually and
       textually separated and always say what they are. Where the journal
       named the genera, no candidate is shown at all. */
    _buildBiologicalSignalsCard() {
      const payload = this._lastBiologicalSignals || null;
      const rows = Array.isArray(payload?.bodies) ? payload.bodies : [];
      if (!rows.length) return null;

      const card = safeEl('article', 'support-card intel-biology-card');
      card.id = 'intel-biology-card';
      card.appendChild(this._cardHeading('Biological Signals', payload?.truth_class));
      card.appendChild(safeEl('p', 'intel-workspace-lead',
        `${rows.length} surface-mapped bod${rows.length === 1 ? 'y' : 'ies'} with `
        + 'recorded biological signals.'));

      const list = safeEl('ul', 'intel-biology-list');
      rows.forEach((row) => {
        const item = safeEl('li', 'intel-biology-row');
        item.appendChild(safeEl('span', 'intel-biology-body',
          row.body_name || 'Unknown body'));

        /* Observed count is a fact and leads. */
        const count = Number(row.biological_signal_count ?? 0);
        item.appendChild(safeEl('span', 'intel-biology-count',
          `${count} biological signal${count === 1 ? '' : 's'} · reported by scan`));

        if (row.genera_observed && row.observed_genera?.length) {
          item.appendChild(safeEl('span', 'intel-biology-observed',
            `Genera reported: ${row.observed_genera.join(', ')}`));
        } else if (row.candidate_genera?.length) {
          /* Clearly marked as an estimate, with its basis named. */
          const genera = row.candidate_genera.map((c) => c.genus).join(', ');
          item.appendChild(safeEl('span', 'intel-biology-candidates',
            `Candidate genera (estimate, not confirmed): ${genera}`));
        }

        if (row.genera_never_logged_by_commander?.length) {
          item.appendChild(safeEl('span', 'intel-biology-unlogged',
            'Never logged by you: '
            + `${row.genera_never_logged_by_commander.join(', ')}`));
        }

        const sampled = row.sampling_progress || [];
        if (sampled.length) {
          const done = sampled.filter((s) => s.analysed).length;
          item.appendChild(safeEl('span', 'intel-biology-progress',
            `${done} of ${sampled.length} sampled species analysed here`));
        }
        list.appendChild(item);
      });
      card.appendChild(list);

      const basis = payload?.candidate_basis;
      if (basis?.needs_review) {
        card.appendChild(safeEl('p', 'intel-history-caveat',
          `Candidate matching uses reference bands from ${basis.kb_entry}, which `
          + 'are community-derived and still awaiting review.'));
      }
      if (payload?.caveat) {
        card.appendChild(safeEl('p', 'intel-history-caveat', payload.caveat));
      }
      return card;
    }

    /* PB13-03 Campaign facts. Intel presents what the objective says and how
       old that record is, plus recorded activity matching its declared target.

       Two things this surface must never do. It must not act: there is no
       create, advance, or complete control anywhere in it, because Operations
       owns execution. And it must not call a name match "progress" — the
       journal records that an event happened in a system or named a faction,
       never that the event moved an objective, so the match basis is stated
       on every row and the two bases are shown separately rather than summed. */
    _buildCampaignWorkspace() {
      const payload = this._lastCampaignFacts || null;
      const rows = Array.isArray(payload?.campaigns) ? payload.campaigns : [];
      const section = safeEl('section', 'intel-campaign-workspace');
      section.setAttribute('aria-label', 'Campaign facts');

      if (!payload) {
        section.appendChild(this._fallbackBriefCard(
          'Campaign Facts',
          'Campaign facts unavailable — the local campaign store did not answer.',
          'intel-campaign-card',
        ));
        return section;
      }

      const card = safeEl('article', 'support-card intel-campaign-card');
      card.id = 'intel-campaign-card';
      card.appendChild(this._cardHeading('Campaign Facts', payload?.truth_class));

      if (!rows.length) {
        /* No objectives is not an error and not an empty database — it means
           none have been entered. Say which. */
        card.appendChild(safeEl('p', 'intel-workspace-lead',
          'No campaign objectives entered. Objectives are created in '
          + 'Operations; Intel shows them here with their local evidence.'));
        section.appendChild(card);
        return section;
      }

      card.appendChild(safeEl('p', 'intel-workspace-lead',
        `${rows.length} campaign objective${rows.length === 1 ? '' : 's'} `
        + '— Commander-entered, newest first.'));

      const list = safeEl('ul', 'intel-campaign-list');
      rows.forEach((row) => {
        const item = safeEl('li', 'intel-campaign-row');
        item.appendChild(safeEl('span', 'intel-campaign-title',
          row.title || 'Untitled objective'));

        const meta = [];
        if (row.workflow_type) meta.push(row.workflow_type.toUpperCase());
        if (row.state) meta.push(row.state);
        const target = row.target_subject || row.target_system;
        if (target) meta.push(`target ${target}`);
        if (meta.length) {
          item.appendChild(safeEl('span', 'intel-campaign-meta', meta.join(' · ')));
        }

        /* PB13-03: source age travels with the fact. */
        item.appendChild(safeEl('span', 'intel-campaign-age',
          `Commander-entered · ${this._campaignAgeText(row.record_age_seconds)}`));

        const evidence = row.evidence || {};
        if (!evidence.available) {
          item.appendChild(safeEl('span', 'intel-campaign-evidence-none',
            evidence.unavailable_reason
            || 'No target declared, so no activity can be matched.'));
        } else {
          const matched = [evidence.system_activity, evidence.subject_activity]
            .filter(Boolean)
            .some((a) => Number(a.events_recorded || 0) > 0
              || Number(a.events_before_window || 0) > 0);
          [
            [evidence.system_activity, 'system'],
            [evidence.subject_activity, 'name'],
          ].forEach(([activity, basis]) => {
            if (!activity) return;
            const count = Number(activity.events_recorded || 0);
            const line = safeEl('span', 'intel-campaign-evidence');
            line.textContent = count === 0
              ? `No recorded activity matching ${basis} ${activity.target} since this objective was entered`
              : `${count} recorded event${count === 1 ? '' : 's'} matching ${basis} ${activity.target}`;
            item.appendChild(line);

            /* Activity that predates the objective is context, not credit.
               It renders as its own line so it can never be read as part of
               the count above it. */
            const before = Number(activity.events_before_window || 0);
            if (before > 0) {
              item.appendChild(safeEl('span', 'intel-campaign-evidence-prior',
                `${before} more matched ${basis} ${activity.target} before this `
                + 'objective was entered'));
            }
          });
          /* The disclaimer rides with the numbers, not in a footnote the
             reader reaches after they have already drawn a conclusion — and
             only where there is a match to qualify. Printing it against a
             row that matched nothing describes something that never
             happened. */
          if (matched) {
            item.appendChild(safeEl('span', 'intel-campaign-match-note',
              'Matched by name within the window — not proof the objective advanced.'));
          }
        }

        list.appendChild(item);
      });
      card.appendChild(list);

      card.appendChild(safeEl('p', 'intel-campaign-owner-note',
        'Intel shows campaign facts. Campaign execution stays in Operations, '
        + 'circuits stay in Navigation, and proof stays in Activity Log.'));

      if (payload.caveat) {
        card.appendChild(safeEl('p', 'intel-history-caveat', payload.caveat));
      }
      section.appendChild(card);
      return section;
    }

    /* Age as elapsed time, never as a freshness verdict — deciding when a
       Commander's own objective has gone stale is the Commander's call. */
    _campaignAgeText(seconds) {
      if (seconds == null) return 'age unknown';
      const value = Number(seconds);
      if (!Number.isFinite(value)) return 'age unknown';
      if (value < 3600) return `updated ${Math.max(1, Math.round(value / 60))} min ago`;
      if (value < 86400) return `updated ${Math.round(value / 3600)} h ago`;
      return `updated ${Math.round(value / 86400)} d ago`;
    }

    /* PB13-02 Reference Library. Curated local knowledge, workflow-scoped —
       never a wiki clone, never live game data, never an authority-RAG result
       dressed as a game fact.

       Two rules drive the layout. Every card cites the patch it was verified
       against and where it came from, because reference material without a
       version is a claim without a date. And an entry flagged needs_review
       shows its topic with the content withheld: listing the topic keeps the
       gap visible, withholding the body keeps unreviewed material off a
       surface a Commander would otherwise read as settled. */
    _buildReferenceWorkspace() {
      const payload = this._lastReference || null;
      const categories = Array.isArray(payload?.categories) ? payload.categories : [];
      const section = safeEl('section', 'intel-reference-workspace');
      section.setAttribute('aria-label', 'Reference library');

      if (!categories.length) {
        section.appendChild(this._fallbackBriefCard(
          'Reference Library',
          'Curated reference unavailable — the local knowledge base did not load.',
          'intel-reference-card',
        ));
        return section;
      }

      const card = safeEl('article', 'support-card intel-reference-card');
      card.id = 'intel-reference-card';
      card.appendChild(this._cardHeading('Reference Library', payload?.truth_class));

      const total = Number(payload.total_entries || 0);
      const withheld = Number(payload.withheld_count || 0);
      const lead = `${total} curated entr${total === 1 ? 'y' : 'ies'} across `
        + `${categories.length} workflow categor${categories.length === 1 ? 'y' : 'ies'}.`;
      card.appendChild(safeEl('p', 'intel-workspace-lead', lead));

      /* The withheld count leads rather than hiding at the bottom: how much of
         the reference is unreviewed is itself reference information. */
      if (withheld > 0) {
        card.appendChild(safeEl('p', 'intel-reference-withheld-note',
          `${withheld} entr${withheld === 1 ? 'y is' : 'ies are'} withheld pending `
          + 'knowledge-base review and show topic only.'));
      }

      categories.forEach((category) => {
        const entries = Array.isArray(category.entries) ? category.entries : [];
        const group = safeEl('details', 'intel-reference-category');
        const summary = safeEl('summary', 'intel-reference-category-summary');
        summary.appendChild(safeEl('span', 'intel-reference-category-label',
          category.label || category.category || 'Reference'));
        summary.appendChild(safeEl('span', 'intel-reference-category-count',
          `${entries.length} entr${entries.length === 1 ? 'y' : 'ies'}`));
        group.appendChild(summary);

        const list = safeEl('ul', 'intel-reference-list');
        entries.forEach((entry) => {
          const withheldEntry = entry.status !== 'available';
          const item = safeEl('li',
            `intel-reference-entry${withheldEntry ? ' intel-reference-entry--withheld' : ''}`);
          item.appendChild(safeEl('span', 'intel-reference-topic',
            entry.topic || entry.id || 'Reference entry'));

          if (withheldEntry) {
            item.appendChild(safeEl('span', 'intel-reference-status',
              'Withheld pending review'));
            item.appendChild(safeEl('span', 'intel-reference-withheld-reason',
              entry.withheld_reason || 'Flagged for knowledge-base review.'));
          } else {
            item.appendChild(safeEl('span', 'intel-reference-content',
              entry.content || ''));
          }

          /* Citation line. Patch version and source are the whole point of a
             reference card, so they render for withheld entries too where the
             backend still supplies them.

             An entry whose patch is literally recorded as "unknown" must not
             render as "Verified for unknown" — that asserts a verification
             that never happened against a patch of that name. */
          const cites = [];
          const patch = String(entry.patch_verified || '').trim();
          if (patch && patch.toLowerCase() !== 'unknown') {
            cites.push(`Verified for ${patch}`);
          } else if (entry.patch_verified) {
            cites.push('Patch not recorded');
          }
          if (entry.reference_source) cites.push(entry.reference_source);
          if (entry.confidence) cites.push(`${entry.confidence} confidence`);
          if (entry.last_updated) cites.push(`updated ${entry.last_updated}`);
          if (cites.length) {
            item.appendChild(safeEl('span', 'intel-reference-cite', cites.join(' · ')));
          }
          list.appendChild(item);
        });
        group.appendChild(list);
        card.appendChild(group);
      });

      if (payload.caveat) {
        card.appendChild(safeEl('p', 'intel-history-caveat', payload.caveat));
      }
      section.appendChild(card);
      return section;
    }

    /* PB13-02: a known-facts result must identify its source class. The chip
       carries the label; the class's meaning — which states the limit, not
       just the origin — goes on `title` so proof detail is one hover away
       without dominating the card.

       An unresolvable class renders no chip rather than a wrong one. A
       result whose provenance the vocabulary cannot name is better shown
       unlabelled than mislabelled, and `test_source_class.py` fails the
       build when that happens, so it never reaches a Commander silently. */
    _sourceClassChip(truthClass) {
      if (!_sourceClass) return null;
      const key = _sourceClass.resolveSourceClass(truthClass);
      if (!key) return null;
      const entry = _sourceClass.SOURCE_CLASS[key];
      const chip = safeEl('span', 'intel-source-class-chip', entry.label);
      chip.setAttribute('data-source-class', key);
      chip.setAttribute('title', entry.meaning);
      return chip;
    }

    /* Card heading with its source-class chip beside it. */
    _cardHeading(title, truthClass) {
      const head = safeEl('div', 'intel-card-heading');
      head.appendChild(safeEl('h3', 'support-card-title', title));
      const chip = this._sourceClassChip(truthClass);
      if (chip) head.appendChild(chip);
      return head;
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
      surface.appendChild(this._detailDrawer('Details', this._buildBgsDetail(facts)));
      surface.appendChild(this._detailDrawer('Proof', this._buildBgsProof(facts), 'local-proof-drawer'));
      /* PB09-08: bridge link to Operations BGS campaign workspace */
      const opsBtn = safeEl('button', 'intel-phase9-bridge-btn cmd-btn cmd-btn--quiet', 'Open in Operations');
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
      surface.appendChild(this._detailDrawer('Details', this._buildPowerplayDetail(facts)));
      surface.appendChild(this._detailDrawer('Proof', this._buildPowerplayProof(facts), 'local-proof-drawer'));
      /* PB09-08: bridge link to Operations Powerplay campaign workspace */
      const opsBtn = safeEl('button', 'intel-phase9-bridge-btn cmd-btn cmd-btn--quiet', 'Open in Operations');
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
      const link = safeEl('a', 'intel-proof-link cmd-btn cmd-btn--quiet', 'View in Log');
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
            context: this._lastLocalContext.marketSearch.provenanceLabel || 'Local market snapshot (station unknown)',
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
      drawer.appendChild(safeEl('summary', 'local-detail-summary', this._canonicalDisclosureLabel(summary)));
      const body = safeEl('div', 'local-detail-body');
      if (content instanceof Node) body.appendChild(content);
      else if (content !== undefined && content !== null) body.textContent = String(content);
      drawer.appendChild(body);
      return drawer;
    }

    _canonicalDisclosureLabel(summary) {
      const value = String(summary || '').toLowerCase();
      if (value.includes('proof') || value.includes('raw')) return 'Proof';
      if (value.includes('source') || value.includes('evidence')) return 'Source';
      if (value.includes('why')) return 'Why?';
      return 'Details';
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
        }, { summary: 'Proof' }));
      } else {
        wrap.appendChild(this._factList([
          { label: 'Source', value: entry?.source || 'Unknown' },
          { label: 'Observed', value: entry?.event_timestamp || 'Unknown' },
          { label: 'Freshness', value: _sourceProof?.freshnessLabel
            ? _sourceProof.freshnessLabel(entry || {})
            : 'Unknown' },
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
      const label = `${String(operation || 'operations').replace(/^./, (letter) => letter.toUpperCase())} workspace`;
      if (typeof window.Shell?.startRouteTransfer === 'function') {
        const intent = window.Shell.startRouteTransfer({
          originRoute: '/intel',
          originPackage: 'Intel',
          originSectionId: 'intel-workspace',
          targetRoute: '/operations',
          targetSectionId: `operations-${operation}-workspace`,
          targetEntityId: operation,
          targetLabel: label,
          reason: `Opening the Commander-selected ${label.toLowerCase()}.`,
          returnLabel: 'Return to Intel',
          returnTarget: { route: '/intel', sectionId: 'intel-workspace' },
        });
        if (intent) return;
      }

      /* Shell route-transfer is the primary path. Keep a one-shot,
         current-session fallback for stripped test/dev shells only. */
      try {
        window.sessionStorage?.setItem('omnicovas.operationHandoff', operation);
      } catch { /* sessionStorage unavailable; selector remains available */ }
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

    /* ── Observed Galaxy / Commander Memory (Phase 11) ─────────────────
       Derived, local-private observed history. It is deliberately separate
       from the raw flight-recorder History domain and never presented as
       live/current state. */

    _buildObservedGalaxyWorkspace() {
      const section = safeEl('section', 'intel-memory-workspace');
      section.setAttribute('aria-label', 'Observed Galaxy — Commander Memory');

      const heading = safeEl('div', 'intel-memory-heading');
      const headingText = safeEl('div');
      headingText.append(
        safeEl('h3', 'support-card-title', 'Observed Galaxy'),
        safeEl(
          'p',
          'intel-workspace-lead',
          'Search private remembered systems, stations, and station snapshots. '
            + 'Remembered facts may be incomplete or stale and never outrank current local state.',
        ),
      );
      const ownerActions = safeEl('div', 'intel-memory-owner-actions');
      ownerActions.append(
        this._memoryRouteButton('Privacy controls', () => this._openMemoryPrivacy()),
        this._memoryRouteButton('Memory action proof', () => this._openMemoryActionProof()),
      );
      heading.append(headingText, ownerActions);
      section.appendChild(heading);

      const status = this._lastMemoryStatus;
      if (!status) {
        const unavailable = this._fallbackBriefCard(
          'Observed Galaxy unavailable',
          'The local Commander Memory service did not answer. Current Intel remains available; no remembered data was changed.',
          'intel-memory-unavailable',
        );
        unavailable.appendChild(
          this._memoryRouteButton('Open Privacy controls', () => this._openMemoryPrivacy()),
        );
        section.appendChild(unavailable);
        return section;
      }

      section.appendChild(this._buildMemoryStatusSummary(status));
      section.appendChild(this._buildMemorySearchControls(status));
      const results = safeEl('div', 'intel-memory-results');
      results.id = 'intel-memory-results';
      results.setAttribute('aria-live', 'polite');
      results.setAttribute('aria-busy', 'false');
      this._renderMemoryResults(results, this._lastMemoryRecords);
      section.appendChild(results);
      return section;
    }

    _memoryRouteButton(label, handler, variant = 'quiet') {
      const button = safeEl('button', `cmd-btn cmd-btn--${variant}`, label);
      button.type = 'button';
      button.addEventListener('click', handler);
      return button;
    }

    _buildMemoryStatusSummary(status) {
      const wrap = safeEl('section', 'intel-memory-status');
      wrap.setAttribute('aria-label', 'Commander Memory status');
      const state = status.rebuilding
        ? 'Rebuilding'
        : status.paused
          ? 'Paused'
          : Number(status.total_records || 0) > 0
            ? 'Remembering locally'
            : 'Ready — empty';
      const stateBadge = safeEl(
        'span',
        `status-badge status-badge--${
          status.rebuilding ? 'stale' : status.paused ? 'disabled' : 'local-only'
        }`,
        state,
      );
      wrap.appendChild(stateBadge);

      const summaries = safeEl('div', 'intel-memory-summary-grid');
      summaries.append(
        this._memorySummaryItem('All records', status.total_records || 0, ''),
        this._memorySummaryItem('Systems', status.categories?.systems || 0, 'systems'),
        this._memorySummaryItem('Stations', status.categories?.stations || 0, 'stations'),
        this._memorySummaryItem('Markets', status.categories?.market || 0, 'market'),
        this._memorySummaryItem('Outfitting', status.categories?.outfitting || 0, 'outfitting'),
        this._memorySummaryItem('Shipyards', status.categories?.shipyard || 0, 'shipyard'),
      );
      wrap.appendChild(summaries);

      const note = status.rebuilding
        ? 'A local rebuild is in progress. Results can change until it finishes.'
        : status.paused
          ? 'New acquisition is paused. Existing remembered facts remain searchable.'
          : status.caveat;
      if (note) wrap.appendChild(safeEl('p', 'intel-memory-caveat', note));
      return wrap;
    }

    _memorySummaryItem(label, count, category) {
      const button = safeEl('button', 'intel-memory-summary-item');
      button.type = 'button';
      button.dataset.memoryCategory = category;
      button.append(
        safeEl('span', 'intel-memory-summary-label', label),
        safeEl('strong', 'intel-memory-summary-count', Number(count || 0).toLocaleString()),
      );
      button.addEventListener('click', () => {
        const select = document.getElementById('intel-memory-category');
        if (select) select.value = category;
        this._runMemorySearch({ category, offset: 0 });
      });
      return button;
    }

    _buildMemorySearchControls(status) {
      const form = safeEl('form', 'intel-memory-filter');
      form.setAttribute('aria-label', 'Search Observed Galaxy');

      const query = safeEl('input', 'intel-memory-input');
      query.id = 'intel-memory-query';
      query.type = 'search';
      query.placeholder = 'System, station, or remembered snapshot';
      query.setAttribute('aria-label', 'Observed Galaxy search text');
      query.value = this._memoryQuery.q || '';

      const category = safeEl('select', 'intel-memory-select');
      category.id = 'intel-memory-category';
      category.setAttribute('aria-label', 'Remembered category');
      [
        ['', 'All categories'],
        ['systems', 'Systems'],
        ['stations', 'Stations'],
        ['market', 'Market snapshots'],
        ['outfitting', 'Outfitting snapshots'],
        ['shipyard', 'Shipyard snapshots'],
      ].forEach(([value, label]) => {
        const option = safeEl('option', '', label);
        option.value = value;
        category.appendChild(option);
      });
      category.value = this._memoryQuery.category || '';

      const profile = safeEl('select', 'intel-memory-select');
      profile.id = 'intel-memory-profile';
      profile.setAttribute('aria-label', 'Commander Memory profile');
      const allProfiles = safeEl('option', '', 'All local profiles');
      allProfiles.value = '';
      profile.appendChild(allProfiles);
      (Array.isArray(status.profiles) ? status.profiles : []).forEach((row) => {
        const option = safeEl(
          'option',
          '',
          row.forgotten
            ? 'Forgotten profile (paused)'
            : String(row.display_name || 'Local Commander profile'),
        );
        option.value = String(row.profile_key || '');
        profile.appendChild(option);
      });
      profile.value = this._memoryQuery.profile_key || '';

      const submit = this._memoryRouteButton('Search Memory', () => {}, 'primary');
      submit.type = 'submit';
      const reset = this._memoryRouteButton('Reset', () => {
        query.value = '';
        category.value = '';
        profile.value = '';
        this._runMemorySearch({ category: '', profile_key: '', q: '', offset: 0 });
      });
      form.append(query, category, profile, submit, reset);
      form.addEventListener('submit', (event) => {
        event.preventDefault();
        this._runMemorySearch({
          category: category.value,
          profile_key: profile.value,
          q: query.value.trim(),
          offset: 0,
        });
      });
      return form;
    }

    async _runMemorySearch(changes = {}) {
      const base = this.apiBase;
      const results = document.getElementById('intel-memory-results');
      if (!results) return;
      if (!base) {
        results.replaceChildren(
          safeEl('p', 'intel-memory-caveat', 'Bridge not ready — Observed Galaxy search is unavailable.'),
        );
        return;
      }
      if (this._memorySearchBusy) return;
      this._memoryQuery = { ...this._memoryQuery, ...changes };
      const params = new URLSearchParams({
        limit: String(this._memoryQuery.limit),
        offset: String(this._memoryQuery.offset),
      });
      if (this._memoryQuery.category) params.set('category', this._memoryQuery.category);
      if (this._memoryQuery.profile_key) {
        params.set('profile_key', this._memoryQuery.profile_key);
      }
      if (this._memoryQuery.q) params.set('q', this._memoryQuery.q);

      this._memorySearchBusy = true;
      results.setAttribute('aria-busy', 'true');
      results.replaceChildren(safeEl('p', 'intel-memory-caveat', 'Searching local Memory…'));
      try {
        const payload = await this.fetchJson(
          `${base}${MEMORY_OBSERVED_PATH}?${params.toString()}`,
        );
        this._lastMemoryRecords = payload;
        this._renderMemoryResults(results, payload);
      } catch (err) {
        results.replaceChildren(
          safeEl(
            'p',
            'intel-memory-caveat',
            `Observed Galaxy search unavailable: ${err?.message || 'request failed'}`,
          ),
        );
      } finally {
        this._memorySearchBusy = false;
        results.setAttribute('aria-busy', 'false');
      }
    }

    _renderMemoryResults(container, payload) {
      container.replaceChildren();
      if (!payload || !Array.isArray(payload.records)) {
        container.appendChild(
          safeEl(
            'p',
            'intel-memory-caveat',
            'Remembered facts are not loaded. Current Intel remains available.',
          ),
        );
        return;
      }
      const total = Number(payload.total || 0);
      const offset = Number(payload.offset || 0);
      const returned = Number(payload.returned || payload.records.length || 0);
      container.appendChild(
        safeEl(
          'p',
          'intel-memory-meta',
          `${returned.toLocaleString()} shown · ${total.toLocaleString()} remembered matches`,
        ),
      );
      if (payload.records.length === 0) {
        container.appendChild(
          safeEl(
            'p',
            'intel-memory-caveat',
            'No remembered facts match these filters. That is not proof the place or item does not exist.',
          ),
        );
        return;
      }
      const list = safeEl('div', 'intel-memory-records');
      payload.records.forEach((record) => list.appendChild(this._buildMemoryRecord(record)));
      container.appendChild(list);
      container.appendChild(this._buildMemoryPagination(offset, returned, total));
      if (payload.caveat) {
        container.appendChild(safeEl('p', 'intel-memory-caveat', payload.caveat));
      }
    }

    _buildMemoryPagination(offset, returned, total) {
      const controls = safeEl('div', 'intel-memory-pagination');
      const previous = this._memoryRouteButton('Previous', () => {
        this._runMemorySearch({ offset: Math.max(0, offset - this._memoryQuery.limit) });
      });
      previous.disabled = offset <= 0;
      const position = safeEl(
        'span',
        'intel-memory-page-position',
        total > 0
          ? `${(offset + 1).toLocaleString()}–${Math.min(offset + returned, total).toLocaleString()} of ${total.toLocaleString()}`
          : '0 results',
      );
      const next = this._memoryRouteButton('Next', () => {
        this._runMemorySearch({ offset: offset + this._memoryQuery.limit });
      });
      next.disabled = offset + returned >= total;
      controls.append(previous, position, next);
      return controls;
    }

    _buildMemoryRecord(record) {
      const card = safeEl('article', 'support-card intel-memory-record');
      card.dataset.memoryCategory = String(record.category || 'unknown');
      card.dataset.memoryRecordId = String(record.id || '');
      const header = safeEl('div', 'intel-memory-record-header');
      const identity = safeEl('div');
      identity.append(
        safeEl('h4', 'intel-memory-record-title', record.display_name || 'Remembered fact'),
        safeEl(
          'p',
          'intel-memory-record-location',
          record.parent_name || this._memoryCategoryLabel(record.category),
        ),
      );
      header.append(
        identity,
        safeEl('span', 'status-badge status-badge--cached', 'Remembered'),
      );
      card.appendChild(header);

      const metrics = safeEl('dl', 'intel-memory-record-metrics');
      this._appendMemoryMetric(metrics, 'Familiarity', record.familiarity || 'Observed');
      this._appendMemoryMetric(metrics, 'Visits', record.visit_count === null ? 'Not established' : record.visit_count ?? 0);
      this._appendMemoryMetric(metrics, 'Observations', record.observation_count ?? 0);
      this._appendMemoryMetric(metrics, 'First seen', this._historyTimeLabel(record.first_seen_at));
      this._appendMemoryMetric(
        metrics,
        'Last seen',
        `${this._historyTimeLabel(record.last_seen_at)} · ${this._memoryAgeLabel(record.last_seen_at)}`,
      );
      card.appendChild(metrics);

      const snapshot = this._buildRememberedSnapshotSummary(record);
      if (snapshot) card.appendChild(snapshot);

      const proof = safeEl('details', 'intel-memory-proof');
      proof.appendChild(safeEl('summary', 'intel-memory-proof-summary', 'Source and caveat'));
      const proofBody = safeEl('div', 'intel-memory-proof-body');
      proofBody.append(
        safeEl('p', '', `Source type: ${record.source_type || 'Unknown'}`),
        safeEl('p', '', `Source event: ${record.source_event || 'Not recorded'}`),
        safeEl('p', '', `Source file class: ${record.source_file || 'Not recorded'}`),
        safeEl('p', '', record.caveat || 'Remembered local history may be incomplete or stale.'),
      );
      proof.appendChild(proofBody);
      card.appendChild(proof);

      const actions = safeEl('div', 'intel-memory-record-actions');
      if (record.source_type === 'local_journal') {
        actions.appendChild(
          this._memoryRouteButton('Search Flight Recorder', () => this._openMemoryInHistory(record)),
        );
      } else {
        actions.appendChild(
          this._memoryRouteButton('Sources & Diagnostics', () => this._openMemorySources(record)),
        );
      }
      card.appendChild(actions);
      return card;
    }

    _appendMemoryMetric(list, label, value) {
      const group = safeEl('div', 'intel-memory-metric');
      group.append(
        safeEl('dt', 'intel-memory-metric-label', label),
        safeEl('dd', 'intel-memory-metric-value', value),
      );
      list.appendChild(group);
    }

    _memoryCategoryLabel(category) {
      return {
        systems: 'Remembered system',
        stations: 'Remembered station',
        market: 'Remembered market snapshot',
        outfitting: 'Remembered outfitting snapshot',
        shipyard: 'Remembered shipyard snapshot',
      }[category] || 'Remembered local fact';
    }

    _memoryAgeLabel(value) {
      const timestamp = new Date(value || '').getTime();
      if (!Number.isFinite(timestamp)) return 'Unknown age';
      const seconds = Math.max(0, Math.floor((Date.now() - timestamp) / 1000));
      if (seconds < 60) return 'Just now';
      if (seconds < 3600) return `${Math.floor(seconds / 60)} min ago`;
      if (seconds < 86400) return `${Math.floor(seconds / 3600)} hr ago`;
      return `${Math.floor(seconds / 86400)} days ago`;
    }

    _buildRememberedSnapshotSummary(record) {
      if (!['market', 'outfitting', 'shipyard'].includes(record.category)) return null;
      const payload = record.payload && typeof record.payload === 'object' ? record.payload : {};
      const items = Array.isArray(payload.items) ? payload.items : [];
      const wrap = safeEl('div', 'intel-memory-snapshot-summary');
      wrap.appendChild(
        safeEl(
          'p',
          'intel-memory-snapshot-count',
          `${Number(payload.item_count ?? items.length).toLocaleString()} items in remembered snapshot`,
        ),
      );
      if (items.length > 0) {
        const list = safeEl('ul', 'intel-memory-snapshot-items');
        items.slice(0, 5).forEach((item) => {
          const name = item.name || item.ship_type || 'Unnamed item';
          const price = item.buy_price ?? item.ship_price;
          const numericPrice = Number(price);
          const detail = price == null || !Number.isFinite(numericPrice)
            ? String(name)
            : `${name} · ${numericPrice.toLocaleString()} CR when observed`;
          list.appendChild(safeEl('li', '', detail));
        });
        wrap.appendChild(list);
      }
      return wrap;
    }

    _openMemoryInHistory(record) {
      this._setDomain('history');
      const typeInput = document.querySelector(
        '#intel-event-history input[name="event_type"]',
      );
      const containsInput = document.querySelector(
        '#intel-event-history input[name="contains"]',
      );
      if (typeInput) typeInput.value = String(record.source_event || '');
      if (containsInput) containsInput.value = String(record.display_name || '');
      this._runJournalSearch(typeInput?.value || '', containsInput?.value || '');
    }

    _openMemoryPrivacy() {
      this._startMemoryTransfer({
        targetRoute: '/privacy',
        targetSectionId: 'commander-memory-section',
        targetLabel: 'Commander Memory controls',
        reason: 'Review privacy, pause, export, rebuild, and deletion controls.',
      });
    }

    _openMemoryActionProof() {
      this._startMemoryTransfer({
        targetRoute: '/activity-log',
        targetSectionId: 'log-search',
        targetEntityId: 'commander-memory',
        targetLabel: 'Commander Memory proof',
        reason: 'Review protected Memory actions and Commander decisions.',
      });
    }

    _openMemorySources(record) {
      this._startMemoryTransfer({
        targetRoute: '/sources-diagnostics',
        targetSectionId: 'sources-diagnostics-root',
        targetEntityId: String(record.category || ''),
        targetLabel: 'Local source diagnostics',
        reason: 'Review the current local source posture for this remembered snapshot.',
      });
    }

    _startMemoryTransfer(target) {
      if (typeof window.Shell?.startRouteTransfer !== 'function') {
        window.location.hash = `#${target.targetRoute}`;
        return;
      }
      window.Shell.startRouteTransfer({
        originRoute: '/intel',
        originPackage: 'Observed Galaxy',
        originSectionId: 'intel-domain-memory',
        ...target,
        returnLabel: 'Return to Observed Galaxy',
        returnTarget: { route: '/intel', sectionId: 'intel-domain-memory' },
      });
    }

    /* ── History domain (Phase 13 Intel terminal core) ──────────────────
       Commander-observed history over the local flight recorder
       (LNA-001/002/003/004/005). Truth class local_event_history: recorded
       sessions on this machine only; absence is never proof of absence.
       Raw event lines are proof-on-demand inside collapsed details and are
       rendered with textContent only (ADR 0003 Tier 1). */

    _buildHistoryWorkspace() {
      const section = safeEl('section', 'intel-history-workspace');
      section.setAttribute('aria-label', 'Observed history');
      section.appendChild(safeEl('p', 'intel-workspace-lead',
        'Commander-observed history from the local flight recorder. Recorded '
        + 'sessions on this machine only — absence here is never proof it did '
        + 'not happen.'));
      section.appendChild(this._buildSessionTimelineCard());
      /* One shared connections panel: the graph is a walk, so a single
         destination that re-renders beats a panel per row. */
      const connections = safeEl('aside', 'support-card intel-history-card');
      connections.id = 'intel-connections';
      connections.appendChild(safeEl('h3', 'support-card-title', 'Connections'));
      const panel = safeEl('div', 'intel-connections-body');
      panel.id = 'intel-connections-panel';
      panel.appendChild(safeEl('p', 'intel-history-caveat',
        'Choose Connections on a session or system to walk what was recorded '
        + 'around it.'));
      connections.appendChild(panel);
      section.appendChild(connections);
      section.appendChild(this._buildEventHistoryCard());
      const catalogs = safeEl('div', 'intel-history-catalogs');
      catalogs.append(
        this._buildVisitedSystemsCard(),
        this._buildVisitedStationsCard(),
      );
      section.appendChild(catalogs);
      return section;
    }

    _historyTimeLabel(value) {
      if (!value) return 'Unknown';
      return String(value).replace('T', ' ').slice(0, 16);
    }

    _historyEventLabel(value) {
      const raw = value == null ? '' : String(value);
      if (!raw) return 'Unknown';
      if (/[<>]/.test(raw)) return raw;
      return _displayNames?.formatActivityEventType?.(raw) || raw;
    }

    /* LNA-001 session timeline. The Activity Log is a proof/event feed and the
       search terminal answers "which events match"; neither answers "which
       sittings happened". Sessions are also what makes the search terminal's
       session_id filter reachable — an id nothing enumerates cannot be used. */
    _buildSessionTimelineCard() {
      const card = safeEl('article', 'support-card intel-history-card');
      card.id = 'intel-session-timeline';
      card.appendChild(this._cardHeading('Session Timeline', this._lastSessions?.truth_class));

      const payload = this._lastSessions;
      if (!payload) {
        card.appendChild(safeEl('p', 'intel-history-caveat',
          'Session timeline unavailable — the local flight recorder did not '
          + 'answer. Recorded events elsewhere on this route are unaffected.'));
        return card;
      }

      const classes = Array.isArray(payload.operation_classes)
        ? payload.operation_classes : [];
      if (classes.length > 0) {
        const filters = safeEl('div', 'intel-session-filters');
        filters.setAttribute('role', 'group');
        filters.setAttribute('aria-label', 'Session operation filter');
        filters.appendChild(safeEl('span', 'intel-history-presets-label',
          'Operations:'));
        const active = this._sessionOperation || '';
        [{ id: '', label: 'All' }, ...classes.map((id) => ({ id, label: id }))]
          .forEach((entry) => {
            const chip = safeEl('button', 'intel-session-filter', entry.label);
            chip.type = 'button';
            chip.setAttribute('data-session-operation', entry.id);
            if (entry.id === active) {
              chip.classList.add('is-active');
              chip.setAttribute('aria-pressed', 'true');
            } else {
              chip.setAttribute('aria-pressed', 'false');
            }
            chip.addEventListener('click', () => this._runSessionTimeline(entry.id));
            filters.appendChild(chip);
          });
        card.appendChild(filters);
      }

      const sessions = Array.isArray(payload.sessions) ? payload.sessions : [];
      const summary = safeEl('p', 'intel-history-caveat',
        sessions.length === 0
          ? (this._sessionOperation
            ? `No recorded session includes ${this._sessionOperation} activity.`
            : 'No sessions recorded yet on this machine.')
          : `${payload.returned} of ${payload.total} recorded sessions shown.`);
      card.appendChild(summary);

      const list = safeEl('div', 'intel-session-list');
      sessions.forEach((session) => list.appendChild(this._sessionRow(session)));
      card.appendChild(list);

      if (payload.caveat) {
        card.appendChild(safeEl('p', 'intel-history-caveat', payload.caveat));
      }
      return card;
    }

    _sessionRow(session) {
      const row = safeEl('article', 'intel-session-row');
      row.setAttribute('data-session-id', String(session.session_id));

      const head = safeEl('div', 'intel-session-head');
      /* Title the sitting by when its activity was observed, not by when the
         recorder opened the row: catching up on an older Journal stamps the
         row at "now", which read as a session starting after it ended. */
      head.appendChild(safeEl('span', 'intel-session-title',
        this._historyTimeLabel(session.first_event_at || session.started_at)));
      if (session.is_most_recent) {
        head.appendChild(safeEl('span', 'status-badge status-badge--local-only',
          'Most recent'));
      }
      /* The recorder writes an end only on a clean exit, so an open session is
         reported as an unknown end rather than a tidy finish. */
      head.appendChild(safeEl('span', 'status-badge status-badge--off',
        session.end_recorded ? 'Ended' : 'End not recorded'));
      row.appendChild(head);

      const facts = safeEl('div', 'intel-session-facts');
      const add = (label, value) => {
        const item = safeEl('span', 'log-inline-field');
        item.append(
          safeEl('span', 'log-inline-label', label),
          safeEl('span', 'log-inline-value', value),
        );
        facts.appendChild(item);
      };
      add('Events', String(session.event_count ?? 0));
      add('Systems', String(session.systems_visited ?? 0));
      add('Stations', String(session.stations_docked ?? 0));
      add('Duration', this._sessionDurationLabel(session.observed_duration_seconds));
      add('Last event', this._historyTimeLabel(session.last_event_at));
      // Kept as its own labelled fact so the two clocks are never conflated.
      add('Recorded', this._historyTimeLabel(session.started_at));
      if (session.commander_name) add('Commander', session.commander_name);
      if (session.ship_type) add('Ship', session.ship_type);
      add('Journal', session.journal_filename || 'Unknown');
      row.appendChild(facts);

      const operations = Array.isArray(session.operations) ? session.operations : [];
      if (operations.length > 0) {
        const chips = safeEl('div', 'intel-session-operations');
        operations.forEach((entry) => {
          chips.appendChild(safeEl('span', 'intel-history-preset',
            `${entry.operation} ×${entry.recorded}`));
        });
        row.appendChild(chips);
      }

      /* Resume hook: carry this sitting into the search terminal, which is the
         surface that can actually replay its events. */
      const open = safeEl('button', 'ocv-btn intel-session-open',
        'Open this session in event search');
      open.type = 'button';
      open.addEventListener('click', () => this._openSessionInSearch(session));
      row.append(open, this._connectionsButton('session', String(session.session_id)));
      return row;
    }

    _sessionDurationLabel(seconds) {
      if (seconds === null || seconds === undefined) return 'Unknown';
      const total = Number(seconds);
      if (!Number.isFinite(total) || total < 0) return 'Unknown';
      const hours = Math.floor(total / 3600);
      const minutes = Math.round((total % 3600) / 60);
      if (hours > 0) return `${hours}h ${minutes}m`;
      if (minutes > 0) return `${minutes}m`;
      return 'Under a minute';
    }

    async _runSessionTimeline(operation) {
      const base = this.apiBase;
      if (!base) return;
      this._sessionOperation = operation || '';
      const params = new URLSearchParams({ limit: '25' });
      if (this._sessionOperation) params.set('operation', this._sessionOperation);
      try {
        this._lastSessions = await this.fetchJson(
          `${base}${SESSIONS_PATH}?${params.toString()}`,
        );
      } catch (err) {
        console.warn('Session timeline unavailable:', err);
        this._lastSessions = null;
      }
      this.render();
    }

    async _openSessionInSearch(session) {
      this._sessionScope = session;
      await this._runJournalSearch('', '');
      /* Re-query after the re-render: the card captured before it is detached. */
      document.getElementById('intel-event-history')
        ?.scrollIntoView?.({ block: 'start' });
    }

    _buildEventHistoryCard() {
      const card = safeEl('article', 'support-card intel-history-card');
      card.id = 'intel-event-history';
      card.appendChild(this._cardHeading('Event History', this._lastJournalSearch?.truth_class));

      const form = safeEl('form', 'intel-history-filter');
      form.setAttribute('aria-label', 'Recorded journal event search');
      const typeInput = safeEl('input', 'intel-history-input');
      typeInput.type = 'text';
      typeInput.name = 'event_type';
      typeInput.placeholder = 'Event type (e.g. FSDJump)';
      typeInput.setAttribute('aria-label', 'Event type filter');
      const containsInput = safeEl('input', 'intel-history-input');
      containsInput.type = 'text';
      containsInput.name = 'contains';
      containsInput.placeholder = 'Contains text';
      containsInput.setAttribute('aria-label', 'Event text filter');
      /* The card is rebuilt whenever results change, so the Commander's filter
         lives on the controller: a re-render must never quietly clear what
         they typed while their results stay filtered by it. */
      typeInput.value = this._journalFilter?.eventType || '';
      containsInput.value = this._journalFilter?.contains || '';
      const submit = safeEl('button', 'ocv-btn intel-history-search-btn', 'Search recorded events');
      submit.type = 'submit';
      form.append(typeInput, containsInput, submit);
      form.addEventListener('submit', (event) => {
        event.preventDefault();
        this._runJournalSearch(typeInput.value.trim(), containsInput.value.trim());
      });
      card.appendChild(form);

      /* PB13-02: recorded event-type presets. Data-driven from the
         flight recorder's distinct recorded rows — never an invented or
         asserted catalog of game events. One click filters the search. */
      const catalog = Array.isArray(this._lastEventTypes?.event_types)
        ? this._lastEventTypes.event_types : [];
      if (catalog.length > 0) {
        const presets = safeEl('div', 'intel-history-presets');
        presets.setAttribute('role', 'group');
        presets.setAttribute('aria-label', 'Recorded event types');
        presets.appendChild(safeEl('span', 'intel-history-presets-label',
          'Recorded types:'));
        catalog.forEach((row) => {
          const chip = safeEl('button', 'intel-history-preset',
            `${row.event_type} ×${row.recorded}`);
          chip.type = 'button';
          chip.setAttribute('data-event-type', row.event_type);
          chip.addEventListener('click', () => {
            typeInput.value = row.event_type;
            this._runJournalSearch(row.event_type, containsInput.value.trim());
          });
          presets.appendChild(chip);
        });
        card.appendChild(presets);
        if (this._lastEventTypes.caveat) {
          presets.title = this._lastEventTypes.caveat;
        }
      }

      /* An active session scope has to be visible and reversible: a filtered
         result set that looks unfiltered is the same lie as a stale one. */
      if (this._sessionScope) {
        const scope = safeEl('div', 'intel-session-filters');
        scope.id = 'intel-session-scope';
        scope.setAttribute('data-session-id', String(this._sessionScope.session_id));
        scope.appendChild(safeEl('span', 'intel-history-presets-label',
          `Scoped to session ${this._historyTimeLabel(this._sessionScope.started_at)}:`));
        const clear = safeEl('button', 'intel-session-filter', 'Clear session scope');
        clear.type = 'button';
        clear.addEventListener('click', () => {
          this._sessionScope = null;
          this._runJournalSearch(typeInput.value.trim(), containsInput.value.trim());
        });
        scope.appendChild(clear);
        card.appendChild(scope);
      }

      const results = safeEl('div', 'intel-history-results');
      results.id = 'intel-event-history-results';
      this._renderJournalResults(results, this._lastJournalSearch);
      card.appendChild(results);
      return card;
    }

    async _runJournalSearch(eventType, contains) {
      const base = this.apiBase;
      const results = document.getElementById('intel-event-history-results');
      if (!results) return;
      if (!base) {
        results.replaceChildren(safeEl('p', 'intel-history-caveat',
          'Bridge not ready — recorded event search is unavailable.'));
        return;
      }
      this._journalFilter = {
        eventType: eventType || '',
        contains: contains || '',
      };
      const params = new URLSearchParams({ limit: '50' });
      if (eventType) params.set('event_type', eventType);
      if (contains) params.set('contains', contains);
      if (this._sessionScope) {
        params.set('session_id', String(this._sessionScope.session_id));
      }
      try {
        const payload = await this.fetchJson(`${base}${JOURNAL_SEARCH_PATH}?${params.toString()}`);
        this._lastJournalSearch = payload;
        this.render();
        return;
      } catch (err) {
        results.replaceChildren(safeEl('p', 'intel-history-caveat',
          `Recorded event search unavailable: ${err?.message || 'request failed'}`));
      }
    }

    _renderJournalResults(container, payload) {
      container.replaceChildren();
      if (!payload) {
        container.appendChild(safeEl('p', 'intel-history-caveat',
          'Recorded events not loaded. The local flight recorder may not have '
          + 'recorded any sessions yet — that is not proof nothing happened.'));
        return;
      }
      container.appendChild(safeEl('p', 'intel-history-meta',
        `${payload.returned ?? 0} of ${payload.total_matched ?? 0} matched · Commander-observed`));
      const events = Array.isArray(payload.events) ? payload.events : [];
      if (events.length === 0) {
        container.appendChild(safeEl('p', 'intel-history-caveat',
          'No recorded events match these filters. Absence here is not proof '
          + 'it never happened.'));
        return;
      }
      const list = safeEl('ul', 'intel-history-list');
      events.forEach((event) => {
        const item = safeEl('li', 'intel-history-row');
        const line = safeEl('div', 'intel-history-row-line');
        line.append(
          safeEl('span', 'intel-history-row-type', this._historyEventLabel(event.event_type)),
          safeEl('span', 'intel-history-row-time', this._historyTimeLabel(event.timestamp)),
        );
        item.appendChild(line);
        const raw = safeEl('details', 'intel-history-raw');
        raw.appendChild(safeEl('summary', 'intel-history-raw-summary', 'Proof'));
        raw.appendChild(safeEl('pre', 'intel-history-raw-json', event.raw_json || ''));
        item.appendChild(raw);
        list.appendChild(item);
      });
      container.appendChild(list);
      if (payload.caveat) {
        container.appendChild(safeEl('p', 'intel-history-caveat', payload.caveat));
      }
    }

    _buildVisitedSystemsCard() {
      const card = safeEl('article', 'support-card intel-history-card');
      card.id = 'intel-visited-systems';
      card.appendChild(this._cardHeading('Observed Systems', this._lastVisitedSystems?.truth_class));
      const payload = this._lastVisitedSystems;
      if (!payload || !Array.isArray(payload.systems)) {
        card.appendChild(safeEl('p', 'intel-history-caveat',
          'No observed-system catalog loaded. The local flight recorder may '
          + 'not have recorded any sessions yet.'));
        return card;
      }
      if (payload.systems.length === 0) {
        card.appendChild(safeEl('p', 'intel-history-caveat',
          'No system visits recorded yet. Absence here is not proof of non-visit.'));
        return card;
      }
      const list = safeEl('ul', 'intel-history-list');
      payload.systems.forEach((row) => {
        const item = safeEl('li', 'intel-history-row intel-history-row--catalog');
        item.append(
          safeEl('span', 'intel-history-row-type', row.star_system || 'Unknown'),
          /* First seen was computed by the backend and never rendered: a visit
             history that only shows the latest arrival is a "last seen" list. */
          safeEl('span', 'intel-history-row-detail',
            `${row.observed_events ?? 'Unknown'} observed · first `
            + `${this._historyTimeLabel(row.first_seen)} · last `
            + `${this._historyTimeLabel(row.last_seen)}`),
        );

        const sources = Array.isArray(row.source_events) ? row.source_events : [];
        if (sources.length > 0) {
          item.appendChild(safeEl('span', 'intel-history-row-sources',
            sources.map((entry) => `${entry.event_type} ×${entry.recorded}`).join(' · ')));
        }

        /* Docked stations make this a history of a place. An empty list means
           visited but never docked — said plainly, not left blank. */
        const stations = Array.isArray(row.docked_stations) ? row.docked_stations : [];
        item.appendChild(safeEl('span', 'intel-history-row-stations',
          stations.length === 0
            ? 'No dockings recorded here'
            : `Docked: ${stations
              .map((entry) => `${entry.station_name} ×${entry.docked_count}`)
              .join(' · ')}`));
        item.appendChild(this._connectionsButton('system', row.star_system || ''));
        item.appendChild(this._systemNoteEditor(row));
        list.appendChild(item);
      });
      card.appendChild(list);
      if (payload.caveat) card.appendChild(safeEl('p', 'intel-history-caveat', payload.caveat));
      return card;
    }

    /* LNA-006 knowledge graph. Every edge carries the type and key needed to
       resolve the next entity, so this is a walk rather than a second listing
       of catalogs the Commander has already seen. */
    _connectionsButton(entityType, key) {
      const button = safeEl('button', 'ocv-btn intel-connections-btn', 'Connections');
      button.type = 'button';
      button.setAttribute('data-connections-for', `${entityType}:${key}`);
      button.addEventListener('click', () => this._openConnections(entityType, key));
      return button;
    }

    async _openConnections(entityType, key) {
      const base = this.apiBase;
      const panel = document.getElementById('intel-connections-panel');
      if (!panel) return;
      panel.replaceChildren(safeEl('p', 'intel-history-caveat', 'Resolving…'));
      if (!base) {
        panel.replaceChildren(safeEl('p', 'intel-history-caveat',
          'Bridge not ready — connections are unavailable.'));
        return;
      }
      const params = new URLSearchParams({ type: entityType, key });
      try {
        const payload = await this.fetchJson(
          `${base}${KNOWLEDGE_ENTITY_PATH}?${params.toString()}`,
        );
        this._renderConnections(panel, payload);
      } catch (err) {
        panel.replaceChildren(safeEl('p', 'intel-history-caveat',
          `Connections unavailable: ${err?.message || 'request failed'}`));
      }
    }

    _renderConnections(panel, payload) {
      panel.replaceChildren();
      const entity = payload?.entity || {};
      panel.appendChild(safeEl('h4', 'intel-connections-title',
        `${entity.display_name || entity.key || 'Unknown'} · ${entity.type || ''}`));

      if (payload.found === false) {
        panel.appendChild(safeEl('p', 'intel-history-caveat',
          'Nothing recorded here on this machine. That is not proof it never '
          + 'happened.'));
        return;
      }

      const edges = Array.isArray(payload.edges) ? payload.edges : [];
      if (edges.length === 0) {
        panel.appendChild(safeEl('p', 'intel-history-caveat',
          'No connections recorded for this entity yet.'));
      } else {
        const grouped = new Map();
        edges.forEach((edge) => {
          if (!grouped.has(edge.relation)) grouped.set(edge.relation, []);
          grouped.get(edge.relation).push(edge);
        });
        grouped.forEach((group, relation) => {
          const row = safeEl('div', 'intel-connections-group');
          row.appendChild(safeEl('span', 'intel-history-presets-label',
            String(relation).replace(/_/g, ' ')));
          group.forEach((edge) => {
            /* Snapshot edges are remembered observations, not recorded
               events, so they are labelled and not walkable as entities. */
            if (edge.freshness === 'remembered') {
              row.appendChild(safeEl('span', 'intel-history-preset',
                `${edge.display_name} · remembered`));
              return;
            }
            const hop = safeEl('button', 'intel-session-filter', edge.display_name);
            hop.type = 'button';
            hop.setAttribute('data-edge-type', edge.type);
            hop.setAttribute('data-edge-key', edge.key);
            hop.addEventListener('click', () => this._openConnections(edge.type, edge.key));
            row.appendChild(hop);
          });
          panel.appendChild(row);
        });
      }

      const notes = Array.isArray(payload.notes) ? payload.notes : [];
      notes.forEach((entry) => {
        panel.appendChild(safeEl('p', 'intel-connections-note',
          `Your note: ${entry.note}`));
      });

      const chain = Array.isArray(payload.source_chain) ? payload.source_chain : [];
      if (chain.length > 0) {
        const proof = safeEl('details', 'intel-connections-proof');
        proof.appendChild(safeEl('summary', null,
          `Recorded proof (${chain.length})`));
        const list = safeEl('ul', 'intel-history-list');
        chain.forEach((row) => {
          list.appendChild(safeEl('li', 'intel-history-row',
            `${this._historyEventLabel(row.event_type)} · `
            + `${this._historyTimeLabel(row.timestamp)} · session ${row.session_id}`));
        });
        proof.appendChild(list);
        panel.appendChild(proof);
      }

      if (payload.caveat) {
        panel.appendChild(safeEl('p', 'intel-history-caveat', payload.caveat));
      }
    }

    /* LNA-004 notes. Authored text, not observed telemetry — it is labelled as
       the Commander's own so it can never be mistaken for a recorded fact, and
       it lives outside Commander Memory so a rebuild cannot erase it. */
    _systemNoteEditor(row) {
      const wrap = safeEl('div', 'intel-system-note');
      wrap.setAttribute('data-system-note', row.star_system || '');

      const label = safeEl('label', 'intel-system-note-label',
        row.note ? 'Your note' : 'Add your note');
      const inputId = `intel-system-note-${encodeURIComponent(row.star_system || '')}`;
      label.setAttribute('for', inputId);

      const input = safeEl('textarea', 'intel-system-note-input');
      input.id = inputId;
      input.rows = 2;
      input.maxLength = 4000;
      input.value = row.note || '';
      input.placeholder = 'Written by you — never treated as a recorded fact.';

      const save = safeEl('button', 'ocv-btn intel-system-note-save', 'Save note');
      save.type = 'button';
      const statusText = safeEl('span', 'intel-system-note-status',
        row.note_updated_at
          ? `Saved ${this._historyTimeLabel(row.note_updated_at)}`
          : '');
      save.addEventListener('click', () => {
        this._saveSystemNote(row.star_system, input.value, statusText);
      });

      wrap.append(label, input, save, statusText);
      return wrap;
    }

    async _saveSystemNote(starSystem, note, statusEl) {
      const base = this.apiBase;
      if (!base || !starSystem) return;
      const trimmed = String(note || '').trim();
      if (statusEl) statusEl.textContent = 'Saving…';
      try {
        const response = await fetch(
          `${base}${SYSTEM_NOTES_PATH}/${encodeURIComponent(starSystem)}`,
          {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ note: trimmed }),
          },
        );
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        const saved = await response.json();
        if (statusEl) {
          statusEl.textContent = saved.deleted ? 'Note removed' : 'Note saved';
        }
        /* Re-read so the row reflects stored truth rather than what was typed:
           the backend bounds and trims the text, and clearing the box deletes. */
        this._lastVisitedSystems = await this.fetchJson(
          `${base}${HISTORY_SYSTEMS_PATH}?limit=25`,
        ).catch(() => this._lastVisitedSystems);
      } catch (err) {
        console.error('[Intel] System note save failed:', err);
        if (statusEl) statusEl.textContent = 'Not saved — the note was not stored.';
      }
    }

    _buildVisitedStationsCard() {
      const card = safeEl('article', 'support-card intel-history-card');
      card.id = 'intel-visited-stations';
      card.appendChild(this._cardHeading('Observed Stations', this._lastVisitedStations?.truth_class));
      const payload = this._lastVisitedStations;
      if (!payload || !Array.isArray(payload.stations)) {
        card.appendChild(safeEl('p', 'intel-history-caveat',
          'No observed-station catalog loaded. The local flight recorder may '
          + 'not have recorded any sessions yet.'));
        return card;
      }
      if (payload.stations.length === 0) {
        card.appendChild(safeEl('p', 'intel-history-caveat',
          'No dockings recorded yet. Absence here is not proof of non-visit.'));
        return card;
      }
      const list = safeEl('ul', 'intel-history-list');
      payload.stations.forEach((row) => {
        const item = safeEl('li', 'intel-history-row intel-history-row--catalog');
        item.append(
          safeEl('span', 'intel-history-row-type', row.station_name || 'Unknown'),
          safeEl('span', 'intel-history-row-detail',
            `${row.star_system || 'Unknown system'} · ${row.docked_count ?? 'Unknown'} dockings `
            + `· last ${this._historyTimeLabel(row.last_docked)}`),
        );
        list.appendChild(item);
      });
      card.appendChild(list);
      if (payload.caveat) card.appendChild(safeEl('p', 'intel-history-caveat', payload.caveat));
      return card;
    }
  }

  /* PB10-R5 inbound handoff, module scope.
     Registered once per module load rather than per controller instance: the
     instance that owns the rendered Intel DOM is not reliably the instance an
     instance-bound listener would reach, and a handoff normally arrives while
     Intel is already mounted so render() never re-runs. The live Commander
     journey caught both failure modes after the render-time hook alone looked
     correct in unit tests.

     The intent is taken from the event, because the shell applies the arrival
     banner and CLEARS the intent before this listener runs. */
  /* Create the bus if this module loads before shell.js. Same idempotent
     pattern shell.js uses, so whichever loads first wins and the other reuses
     it. Without this the listener silently never registers. */
  window.OmniEvents = window.OmniEvents || new EventTarget();

  /* GKI-07: a changed Chronicle or a different commander invalidates every
     Atlas record card read so far, and so does any way back into Intel: the
     Commander may have changed an expedition elsewhere (adding a stop is not a
     Chronicle event). Registered before the transfer listener below, so a
     handoff's own re-render already reads afresh. */
  if (!window.__omniIntelChronicleListener) {
    window.__omniIntelChronicleListener = true;
    const forgetRecords = () => { Object.keys(recordCache).forEach((key) => { delete recordCache[key]; }); };
    window.OmniEvents.addEventListener('event', (event) => {
      const message = event?.detail || {};
      if (CHRONICLE_EVENTS.includes(message.event_type || message.event)) forgetRecords();
    });
    window.OmniEvents.addEventListener('route-transfer-started', (event) => {
      if (event?.detail?.intent?.targetRoute === '/intel') forgetRecords();
    });
    window.OmniEvents.addEventListener('route-changed', (event) => {
      if (event?.detail?.route === '/intel') forgetRecords();
    });
  }

  if (!window.__omniIntelTransferListener) {
    window.__omniIntelTransferListener = true;
    window.OmniEvents.addEventListener('route-transfer-started', (event) => {
      const intent = event?.detail?.intent;
      if (intent?.targetRoute !== '/intel') return;

      /* Apply immediately, then retry on a macrotask so a route that is still
         mounting also gets the switch.

         Deliberately NOT requestAnimationFrame: rAF does not fire while the
         document is hidden, so a handoff triggered with the OmniCOVAS window
         minimised or backgrounded would silently never apply. The live
         Commander journey surfaced this — the window was not compositing and
         the rAF callback never ran. `setTimeout` fires regardless. */
      const apply = () => {
        const root = getRoot();
        if (!root) return false;
        if (!applyIntelTransferIntent(root, intent, setDomainOnRoot)) return false;
        /* Intel already mounted: no render follows, so render the arrival
           banner and return link here, as the render path does. Otherwise the
           intent stayed pending and surfaced on some later unrelated render. */
        window.Shell?.applyRouteTransferArrival?.('/intel', root);
        return true;
      };

      if (!apply()) {
        window.setTimeout(apply, 0);
      }
    });
  }

  function init() {
    new IntelController();
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }

  globalThis.__intelExports = {
    IntelController,
    /* Test hook: `pendingTransferDomain` is module state, so tests must be
       able to reset it between cases the way the Dashboard exposes
       __resetSurface. Not used by production code. */
    __resetTransferState() { pendingTransferDomain = null; },
  };
})();
