/**
 * Phase 7.5 PB07.5-05 Navigation route.
 *
 * Purpose-led movement console.
 * Uses PB07.5 command primitives via cached dynamic import.
 * ADR 0003: safe DOM rendering throughout.
 */
(function () {
  'use strict';

  /* Cached dynamic imports at module scope. */
  const primitivesPromise = import('../components/command-primitives.js').catch(err => {
    console.error('[navigation] Failed to load command primitives:', err);
    return null;
  });
  /* PB07.6-03: source/proof/state primitives — synchronously read by
   * render after the module-level cache below is populated by .then().
   * Tests must await this promise (or the navigation.js import) before
   * relying on the source chip / OmniStateBadge appearing in the DOM. */
  let cachedSourceProof = null;
  const sourceProofPromise = import('../components/source-proof.js').then((mod) => {
    cachedSourceProof = mod;
    return mod;
  }).catch(err => {
    console.error('[navigation] Failed to load source-proof primitives:', err);
    return null;
  });
  let cachedLocalContextVM = null;
  const localContextPromise = import('../view-models/local-context.js').then((mod) => {
    cachedLocalContextVM = mod;
    return mod;
  }).catch(err => {
    console.error('[navigation] Failed to load local context VM:', err);
    return null;
  });
  let cachedCommanderVM = null;
  const commanderVMPromise = import('../view-models/commander-context.js').then((mod) => {
    cachedCommanderVM = mod;
    return mod;
  }).catch(err => {
    console.error('[navigation] Failed to load commander VM:', err);
    return null;
  });
  let cachedLocalSurfaces = null;
  const localSurfacesPromise = import('../components/local-context-surfaces.js').then((mod) => {
    cachedLocalSurfaces = mod;
    return mod;
  }).catch(err => {
    console.error('[navigation] Failed to load local context surfaces:', err);
    return null;
  });

  class NavigationController {
    constructor(rootOverride = null) {
      this._primitives = null;
      this._sourceProof = null;
      this._bookmarkTagFilter = null;
      this._loaded = false;
      this._recoveryWired = false;
      this._activeMode = 'current';
      this._root = rootOverride || document.getElementById('navigation-root');
      this.init();
    }

    init() {
      if (!this._root) return;
      this._renderWaiting();
      this._wireRecovery();
      if (window.Shell && window.Shell.httpBase) {
        this.fetchAndRender();
      }
    }

    /* NAV-01 recovery wiring. A Navigation fetch can run during app startup
     * before the backend nav routes are serving; without recovery the route
     * stays stuck on a hard "unreachable" state until a full reload. Re-fetch
     * when the bridge (re)connects and when the Navigation route is
     * (re)activated, so the surface recovers on its own or by navigating away
     * and back — no full reload required. Registered once per controller. */
    _wireRecovery() {
      if (this._recoveryWired) return;
      this._recoveryWired = true;
      if (window.OmniEvents && typeof window.OmniEvents.addEventListener === 'function') {
        window.OmniEvents.addEventListener('bridge-connected', () => {
          if (!this._loaded) this.fetchAndRender();
        });
      }
      if (typeof window.addEventListener === 'function') {
        window.addEventListener('hashchange', () => {
          if (!this._loaded && window.location && window.location.hash === '#/navigation') {
            this.fetchAndRender();
          }
        });
      }
    }

    async fetchAndRender() {
      if (!window.Shell || !window.Shell.httpBase) return;
      const base = window.Shell.httpBase;

      /* NAV-01: guard every fetch so a single endpoint failure cannot reject
       * the whole batch and collapse the surface into a permanent error. */
      const [snapshotResp, libraryResp, localContextResp, circuitsResp] = await Promise.all([
        window.fetch(base + '/navigation/snapshot').catch(() => null),
        window.fetch(base + '/navigation/library/snapshot').catch(() => null),
        window.fetch(base + '/intel/local-context/snapshot').catch(() => null),
        window.fetch(base + '/navigation/phase9/circuits').catch(() => null),
      ]);

      /* The route snapshot is the only critical surface. A network failure
       * (null) is a recoverable bridge-not-ready condition; a non-OK response
       * is a backend condition. Both render an honest unavailable state and
       * leave recovery armed (bridge-connected / route activation re-fetch),
       * so a later readiness or route re-entry recovers without a reload. */
      if (!snapshotResp) {
        this._loaded = false;
        this.renderUnavailable('Navigation bridge unreachable.', 'Not Loaded');
        return;
      }
      if (!snapshotResp.ok) {
        this._loaded = false;
        this.renderUnavailable('Navigation data unavailable.', 'Not Loaded');
        return;
      }

      try {
        const snapshot = await snapshotResp.json();
        /* A single secondary-endpoint failure must not brick the route.
           PB-PHASE10-SUPER-03 #6: when the local bookmark library cannot be read
           (e.g. a stale local DB), mark it unavailable so the card degrades
           honestly instead of showing empty controls that imply working
           bookmark management. */
        const library = (libraryResp && libraryResp.ok)
          ? await libraryResp.json()
          : { bookmarks: [], saved_routes: [], unavailable: true };
        const localRaw = (localContextResp && localContextResp.ok) ? await localContextResp.json() : null;
        const circuitsRaw = (circuitsResp && circuitsResp.ok) ? await circuitsResp.json() : { circuits: [] };

        const displayLibrary = library;

        await Promise.all([localContextPromise, localSurfacesPromise, commanderVMPromise]);
        const localContext = cachedLocalContextVM?.deriveLocalContext(localRaw) || null;

        const primitives = await this._getPrimitives();
        if (!primitives) {
          this.renderUnavailable('Command primitives unavailable.', 'Error');
          return;
        }

        this.render(primitives, snapshot, displayLibrary, localContext, circuitsRaw);
        this._loaded = true;
      } catch (_err) {
        this._loaded = false;
        this.renderUnavailable('Navigation bridge unreachable.', 'Not Loaded');
      }
    }

    async _getPrimitives() {
      if (this._primitives) return this._primitives;
      this._primitives = await primitivesPromise;
      return this._primitives;
    }

    async _getSourceProof() {
      if (this._sourceProof) return this._sourceProof;
      this._sourceProof = await sourceProofPromise;
      return this._sourceProof;
    }

    async render(primitives, snapshot, library = { bookmarks: [], saved_routes: [] }, localContext = null, circuitsData = { circuits: [] }) {
      if (!this._root) return;
      const { createRouteHero } = primitives;
      const activeRoute = snapshot.active_route || {};
      /* Sync read of the module-level cache. If the source-proof module
       * has not loaded yet, primary rendering still works; the chip and
       * state badge re-appear on the next render after load completes. */
      const sourceProof = cachedSourceProof;

      const container = document.createElement('div');
      container.className = 'navigation-route';

      const isLoaded = this._hasActiveRoute(activeRoute);

      container.appendChild(createRouteHero({
        kicker: 'Route / Movement',
        title: 'Navigation',
        statusText: isLoaded ? 'Route loaded' : 'No route plotted',
        statusVariant: isLoaded ? 'available' : 'not-loaded',
        primaryValues: this._extractPrimaryValues(activeRoute),
      }));

      /* PB-UIV3-HARMONY §4·4: planner-mode strip gives Navigation a planner
         identity (Current · Plan · Bookmarks · History). Selecting a mode now
         SWITCHES the visible workspace panel (not an anchor scroll), so the
         selector meaningfully changes what the route shows. Plan / History are
         honest reserved planner workspaces; Bookmarks is secondary. */
      container.appendChild(this._createPlannerModeNav());

      const grid = document.createElement('div');
      grid.className = 'navigation-grid';

      /* CURRENT — the planner's primary workspace. Current Route leads as a
         hero (strong no-route planner shell when empty); Local Context and
         Route Activation support it. */
      const currentPanel = this._createModePanel('current');
      currentPanel.appendChild(this._createActiveRouteCard(primitives, activeRoute, sourceProof));
      currentPanel.appendChild(this._createLocalContextCard(primitives, localContext, snapshot));
      currentPanel.appendChild(this._createGateProposalCard(primitives, activeRoute));
      grid.appendChild(currentPanel);

      /* PLAN — reserved route/journey planner workspace + Spansh link-out. */
      const planPanel = this._createModePanel('plan');
      planPanel.appendChild(this._createPlanReservedCard(primitives));
      const linkOut = this._createSpanshLinkOut(primitives, snapshot.spansh_url || null);
      if (linkOut) planPanel.appendChild(linkOut);
      grid.appendChild(planPanel);

      /* BOOKMARKS — secondary library workspace. Campaign circuits live here
         (off the default-visible surface) so the route no longer leads with the
         raw collapsed circuits panel the Commander flagged. */
      const bookmarksPanel = this._createModePanel('bookmarks');
      bookmarksPanel.appendChild(this._createLibraryCard(primitives, library, activeRoute));
      bookmarksPanel.appendChild(this._createCampaignCircuitsPanel(circuitsData.circuits || []));
      grid.appendChild(bookmarksPanel);

      /* HISTORY — reserved local route-history workspace. */
      const historyPanel = this._createModePanel('history');
      historyPanel.appendChild(this._createHistoryReservedCard(primitives));
      grid.appendChild(historyPanel);

      container.appendChild(grid);
      this._root.replaceChildren(container);
      this._setPlannerMode(this._activeMode || 'current');
      this._applyRouteTransferArrival();
    }

    _createModePanel(mode) {
      const panel = document.createElement('div');
      panel.className = `navigation-mode-panel navigation-mode-panel--${mode}`;
      panel.setAttribute('data-nav-mode', mode);
      panel.setAttribute('role', 'tabpanel');
      return panel;
    }

    /* Switch the visible planner workspace: show the selected mode panel, hide
       the others, move the active indicator. A real workspace swap so planner
       selection changes what Navigation shows. */
    _setPlannerMode(mode) {
      this._activeMode = mode;
      if (!this._root) return;
      this._root.querySelectorAll('.navigation-mode-panel').forEach((panel) => {
        const match = panel.getAttribute('data-nav-mode') === mode;
        panel.hidden = !match;
        panel.classList.toggle('is-active', match);
      });
      this._root.querySelectorAll('.navigation-planner-mode').forEach((tab) => {
        if (tab.getAttribute('data-planner-mode') === mode) tab.setAttribute('aria-current', 'true');
        else tab.removeAttribute('aria-current');
      });
    }

    /* Reserved Plan workspace — honest and compact. No fake plotting, no
       autopilot, no game-action language. */
    _createPlanReservedCard(primitives) {
      const { createCommandCard, createEmptyState } = primitives;
      const card = createCommandCard({ title: 'Route Planning Modes' });
      card.id = 'navigation-plan-modes';
      const body = document.createElement('div');
      body.className = 'navigation-reserved-body';
      body.appendChild(createEmptyState({
        status: 'Reserved — Phase 15',
        reason: 'Multi-leg route proposal and journey planning are reserved for a future update. Local route context is available now under Current.',
      }));
      const note = document.createElement('p');
      note.className = 'navigation-reserved-note';
      note.textContent = 'Neutron, carrier, and long-range planners are dataset-gated and not yet enabled. OmniCOVAS never controls the game.';
      body.appendChild(note);
      card.appendChild(body);
      return card;
    }

    /* Reserved History workspace — honest and compact. */
    _createHistoryReservedCard(primitives) {
      const { createCommandCard, createEmptyState } = primitives;
      const card = createCommandCard({ title: 'Route History' });
      card.id = 'navigation-history';
      const body = document.createElement('div');
      body.className = 'navigation-reserved-body';
      body.appendChild(createEmptyState({
        status: 'Reserved — Phase 15',
        reason: 'Local route history and journey replay are reserved for a future planner update.',
      }));
      card.appendChild(body);
      return card;
    }

    _createPlannerModeNav() {
      const nav = document.createElement('nav');
      nav.className = 'navigation-planner-modes';
      nav.setAttribute('role', 'tablist');
      nav.setAttribute('aria-label', 'Navigation planner modes');
      const MODES = [
        { id: 'current', label: 'Current' },
        { id: 'plan', label: 'Plan', reserved: true },
        { id: 'bookmarks', label: 'Bookmarks' },
        { id: 'history', label: 'History', reserved: true },
      ];
      const active = this._activeMode || 'current';
      MODES.forEach((mode) => {
        const tab = document.createElement('button');
        tab.type = 'button';
        tab.className = 'navigation-planner-mode';
        tab.textContent = mode.label;
        tab.setAttribute('role', 'tab');
        tab.setAttribute('data-planner-mode', mode.id);
        if (mode.id === active) tab.setAttribute('aria-current', 'true');
        if (mode.reserved) {
          /* Plan / History switch to honest reserved workspaces — clickable so
             selection changes the workspace, with a Reserved badge so they read
             as future modes, never dead buttons. */
          const badge = document.createElement('span');
          badge.className = 'navigation-planner-mode-badge';
          badge.textContent = 'Reserved';
          tab.appendChild(badge);
        }
        tab.addEventListener('click', () => this._setPlannerMode(mode.id));
        nav.appendChild(tab);
      });
      return nav;
    }

    _hasActiveRoute(activeRoute) {
      const destination = typeof activeRoute?.destination === 'string'
        ? activeRoute.destination.trim()
        : '';
      if (!destination || destination === '0') return false;
      if (activeRoute?.route_state) return activeRoute.route_state === 'active';
      return true;
    }

    _extractPrimaryValues(activeRoute) {
      const values = [];
      /* Repair R7: never render numeric fallbacks like "0" for missing
         destinations or hops. The hero must stay empty / honest when
         the route is unknown. */
      if (!this._hasActiveRoute(activeRoute)) return values;
      if (typeof activeRoute.destination === 'string' && activeRoute.destination.trim()) {
        values.push({ label: 'Destination', value: activeRoute.destination.trim() });
      }
      const totalHops = Number.isFinite(activeRoute.total_hops)
        ? Number(activeRoute.total_hops) : null;
      if (totalHops && totalHops > 0) {
        values.push({ label: 'Total hops', value: String(totalHops) });
      }
      if (typeof activeRoute.origin === 'string' && activeRoute.origin.trim()) {
        values.push({ label: 'Origin', value: activeRoute.origin.trim() });
      }
      return values;
    }

    _createLocalContextCard(primitives, localContext, snapshot = null) {
      const { createCommandCard, createDetailDrawer } = primitives;
      const sessionState = window.Shell?.eliteSessionState || null;
      /* Top Navigation fact row (Current system / Station) identity
         resolution.

         The /navigation/snapshot scalars (current_system, current_station)
         have been observed to arrive reversed in live sessions — the
         station name in current_system and the system name in
         current_station. The journal-derived local context is the only
         trustworthy source of truth for these names, so:

           1. Prefer localContext (stationBrief.stationName,
              systemBrief.systemName) outright.
           2. When the snapshot scalars contradict the trusted local
              identity, treat them as swap-victims and route the
              disagreeing value to the OTHER row instead of dropping it.
              "Do not use station as system" and "do not leave Station
              blank when station is known" — both apply here.
           3. Only when no local identity exists at all do we fall back to
              the raw snapshot scalars verbatim. */
      const localStation = localContext?.stationBrief?.stationName || null;
      const localSystem  = localContext?.systemBrief?.systemName
        || localContext?.stationBrief?.systemName
        || null;
      const snapSystemRaw = snapshot?.current_system || null;
      const snapStationRaw = snapshot?.current_station || null;

      /* A scalar that matches the OPPOSITE local identity is polluted —
         drop it from its declared role. */
      const sysMatchesLocalStation = Boolean(snapSystemRaw && localStation && snapSystemRaw === localStation);
      const staMatchesLocalSystem  = Boolean(snapStationRaw && localSystem && snapStationRaw === localSystem);
      /* A scalar that disagrees with the trusted local identity is also
         polluted — but it may carry the correct value for the OTHER row. */
      const sysDisagreesWithLocalSystem  = Boolean(localSystem && snapSystemRaw && snapSystemRaw !== localSystem);
      const staDisagreesWithLocalStation = Boolean(localStation && snapStationRaw && snapStationRaw !== localStation);

      const trustedSnapSystem = (sysMatchesLocalStation || sysDisagreesWithLocalSystem)
        ? null
        : snapSystemRaw;
      const trustedSnapStation = (staMatchesLocalSystem || staDisagreesWithLocalStation)
        ? null
        : snapStationRaw;

      /* Swap-victim recovery: a current_system value rejected above because
         it disagreed with localSystem may actually be the station name a
         past polluted state wrote into the wrong scalar. Same logic in
         reverse for current_station rejected for matching localSystem. */
      const stationFromSwappedSystem = sysDisagreesWithLocalSystem && !sysMatchesLocalStation
        ? snapSystemRaw
        : null;
      const systemFromSwappedStation = staDisagreesWithLocalStation && !staMatchesLocalSystem
        ? snapStationRaw
        : null;

      const system = localSystem
        || trustedSnapSystem
        || systemFromSwappedStation
        || 'Unknown system';
      const station = localStation
        || trustedSnapStation
        || stationFromSwappedSystem
        || 'No station context';

      /* Docking-state row only: route a sanitized shipState through the
         unified location derivation so the flightLabel/value matches the
         rest of the UI. Identity is already decided above. */
      const fauxState = {
        current_system: localSystem || trustedSnapSystem || systemFromSwappedStation,
        current_station: localStation || trustedSnapStation || stationFromSwappedSystem,
        is_docked: null,
      };
      const loc = cachedCommanderVM?.deriveCommanderLocationState
        ? cachedCommanderVM.deriveCommanderLocationState(localContext, fauxState, snapshot, { sessionState })
        : null;
      const dockingRow = loc
        ? `${loc.flightLabel}: ${loc.flightValue}`
        : (localContext?.stationBrief?.dockedLabel || 'Docking state unknown');
      const card = createCommandCard({
        title: 'Local Context',
        primaryValue: `${system} / ${station}`,
      });
      card.id = 'navigation-local-context';

      const body = document.createElement('div');
      body.className = 'navigation-local-context-body';
      body.appendChild(this._createContextFact('Current system', system, 'system'));
      body.appendChild(this._createContextFact('Station', station, 'station'));
      body.appendChild(this._createFactRow(loc?.flightLabel || 'Docked / last-known state',
        loc ? loc.flightValue : dockingRow));

      const detail = document.createElement('div');
      detail.className = 'navigation-local-context-detail';
      detail.appendChild(this._createFactRow('System address', localContext?.systemBrief?.detailRows?.find?.((row) => row.label === 'System address')?.value || 'Unknown'));
      detail.appendChild(this._createFactRow('Scope', 'Current local context only; complete in-game nav list is not claimed.'));
      body.appendChild(createDetailDrawer({ summary: 'Local context detail', content: detail }));

      if (cachedLocalSurfaces && localContext?.systemBrief) {
        body.appendChild(cachedLocalSurfaces.createSystemBriefSurface(localContext.systemBrief));
      }

      card.appendChild(body);
      return card;
    }

    _createActiveRouteCard(primitives, activeRoute, sourceProof) {
      const { createCommandCard, createEmptyState, createDetailDrawer } = primitives;
      const card = createCommandCard({ title: 'Current Route' });
      card.id = 'navigation-current-route';

      if (!this._hasActiveRoute(activeRoute)) {
        const empty = createEmptyState({
          status: 'No route plotted',
          reason: activeRoute?.caveat || 'NavRoute.json is absent or empty. Elite removes or empties this file when no route exists; this is not an OmniCOVAS error.'
        });
        if (sourceProof && typeof sourceProof.createOmniStateBadge === 'function') {
          const badge = sourceProof.createOmniStateBadge('no_route_plotted');
          badge.classList.add('navigation-empty-state-badge');
          empty.insertBefore(badge, empty.firstChild);
        }
        card.appendChild(empty);

        /* VD-08 — no-route state must not be a dead end; give a clear next action. */
        const instruction = document.createElement('p');
        instruction.className = 'navigation-no-route-instruction';
        instruction.textContent = 'Plot a route in Elite Dangerous. OmniCOVAS will show it when NavRoute.json updates.';
        card.appendChild(instruction);

        /* PB-UIV3-HARMONY §4·4 — inviting planner shell. The empty state is not
           a dead column: it leads to saved destinations and the reserved
           planning modes so the no-route surface feels intentional. No fake
           plotting and no game-action language. */
        const prompt = document.createElement('div');
        prompt.className = 'navigation-planner-prompt';
        const promptTitle = document.createElement('p');
        promptTitle.className = 'navigation-planner-prompt-title';
        promptTitle.textContent = 'Plan your next move';
        prompt.appendChild(promptTitle);

        const promptActions = document.createElement('div');
        promptActions.className = 'navigation-planner-prompt-actions';

        const browseBtn = document.createElement('button');
        browseBtn.type = 'button';
        browseBtn.className = 'navigation-planner-prompt-btn';
        browseBtn.textContent = 'Browse saved destinations';
        browseBtn.addEventListener('click', () => this._setPlannerMode('bookmarks'));
        promptActions.appendChild(browseBtn);

        const planBtn = document.createElement('button');
        planBtn.type = 'button';
        planBtn.className = 'navigation-planner-prompt-btn';
        planBtn.textContent = 'Open route planning modes';
        planBtn.addEventListener('click', () => this._setPlannerMode('plan'));
        promptActions.appendChild(planBtn);

        prompt.appendChild(promptActions);
        card.appendChild(prompt);

        return card;
      }

      const body = document.createElement('div');
      body.className = 'navigation-active-body';

      /* Pilot view: destination, next hop, total hops. No source chips at this
       * level. Per v2 UI/UX Master Blueprint §9.4, source / freshness / truth
       * / fallback move to the proof drawer below so the default surface stays
       * focused on movement context. */

      body.appendChild(this._createFactRow('Destination', activeRoute.destination));
      /* Correction #10: Next hop is the most useful single fact a pilot
         needs while a route is plotted. */
      const nextHop = activeRoute.next_hop || (Array.isArray(activeRoute.hops) && activeRoute.hops.length > 1
        ? activeRoute.hops[1]?.star_system || null
        : null);
      if (nextHop) {
        body.appendChild(this._createFactRow('Next hop', nextHop));
      }
      /* Repair R7: only render Total hops when a real positive count exists.
         Never render "0" — that misled smoke testers into thinking the route
         was malformed. */
      const totalHops = Number.isFinite(activeRoute.total_hops)
        ? Number(activeRoute.total_hops) : null;
      if (totalHops && totalHops > 0) {
        body.appendChild(this._createFactRow('Total hops', String(totalHops)));
      }
      if (activeRoute.origin) {
        body.appendChild(this._createFactRow('Origin', activeRoute.origin));
      }

      if (activeRoute.hops && activeRoute.hops.length > 0) {
        body.appendChild(this._createHopList(activeRoute.hops));
      }

      /* Proof drawer: source chip + chip row + fallback + caveat all here. */
      const proof = document.createElement('div');
      proof.className = 'navigation-provenance-details';

      if (sourceProof && typeof sourceProof.mapSourceIdToChipLabel === 'function') {
        const chipKey = sourceProof.mapSourceIdToChipLabel(activeRoute.source_id, activeRoute.freshness_label);
        const chipRow = document.createElement('div');
        chipRow.className = 'navigation-source-chip-row';
        chipRow.appendChild(sourceProof.createSourceChip(chipKey));
        proof.appendChild(chipRow);
      }

      const chipRow = document.createElement('div');
      chipRow.className = 'navigation-chip-row';
      chipRow.appendChild(this._createChip('Source', activeRoute.source_id));
      chipRow.appendChild(this._createChip('Freshness', activeRoute.freshness_label));
      chipRow.appendChild(this._createChip('Truth', activeRoute.truth_class));
      proof.appendChild(chipRow);

      if (activeRoute.fallback) {
        const p = document.createElement('p');
        p.className = 'navigation-detail-line';
        p.textContent = `Fallback: ${activeRoute.fallback}`;
        proof.appendChild(p);
      }
      if (activeRoute.caveat) {
        const p = document.createElement('p');
        p.className = 'navigation-detail-line';
        p.textContent = activeRoute.caveat;
        proof.appendChild(p);
      }

      body.appendChild(createDetailDrawer({ summary: 'Source & proof', content: proof }));
      card.appendChild(body);
      return card;
    }

    _createFactRow(label, value) {
      const row = document.createElement('div');
      row.className = 'navigation-fact-row';
      const labelEl = document.createElement('span');
      labelEl.className = 'navigation-fact-label';
      labelEl.textContent = label;
      const valueEl = document.createElement('span');
      valueEl.className = value ? 'navigation-fact-value' : 'navigation-fact-value navigation-fact-value--fallback';
      valueEl.textContent = value || 'Unknown';
      row.append(labelEl, valueEl);
      return row;
    }

    _createContextFact(label, value, key) {
      const fact = document.createElement('div');
      fact.className = 'navigation-context-fact';
      if (key) fact.setAttribute('data-key', key);
      const labelEl = document.createElement('span');
      labelEl.className = 'navigation-context-fact-label';
      labelEl.textContent = label;
      const valueEl = document.createElement('span');
      valueEl.className = value
        ? 'navigation-context-fact-value'
        : 'navigation-context-fact-value navigation-context-fact-value--fallback';
      valueEl.textContent = value || 'Unknown';
      fact.append(labelEl, valueEl);
      return fact;
    }

    _createHopList(hops) {
      const list = document.createElement('ol');
      list.className = 'navigation-hop-list';
      hops.forEach(hop => {
        const item = document.createElement('li');
        item.className = 'navigation-hop-item';
        const sys = document.createElement('span');
        sys.className = 'navigation-hop-system';
        sys.textContent = hop.star_system;
        item.appendChild(sys);
        if (hop.star_class) {
          const cls = document.createElement('span');
          cls.className = 'navigation-hop-class';
          cls.textContent = hop.star_class;
          item.appendChild(cls);
        }
        list.appendChild(item);
      });
      return list;
    }

    _createSpanshLinkOut(primitives, spanshUrl) {
      if (!spanshUrl) return null;
      const { createCommandCard, createDetailDrawer } = primitives;
      const card = createCommandCard({ title: 'External Context' });
      card.id = 'navigation-external-context';

      const body = document.createElement('div');
      body.className = 'navigation-spansh-body';

      const link = document.createElement('a');
      link.className = 'navigation-spansh-link';
      link.setAttribute('href', spanshUrl);
      link.setAttribute('target', '_blank');
      link.setAttribute('rel', 'noopener noreferrer');
      link.textContent = 'Open route in Spansh ↗';
      body.appendChild(link);

      const details = document.createElement('p');
      details.className = 'navigation-spansh-attr';
      details.textContent = 'External Spansh route-plotter link. Opens in an external browser. OmniCOVAS does not call the Spansh API.';

      body.appendChild(createDetailDrawer({ summary: 'Why?', content: details }));
      card.appendChild(body);
      return card;
    }

    _createGateProposalCard(primitives, activeRoute) {
      const { createCommandCard, createDetailDrawer } = primitives;
      const card = createCommandCard({ title: 'Route Activation' });
      card.id = 'navigation-route-activation';

      const body = document.createElement('div');
      body.className = 'navigation-gate-body';

      const btn = document.createElement('button');
      btn.className = 'navigation-gate-btn';
      btn.type = 'button';
      if (this._hasActiveRoute(activeRoute)) {
        btn.textContent = 'Propose Route Activation';
        btn.addEventListener('click', () => this.proposeRouteActivation(activeRoute));
      } else {
        btn.textContent = 'Route plotting proposal - future/deferred';
        btn.disabled = true;
      }
      body.appendChild(btn);

      const details = document.createElement('p');
      details.className = 'navigation-gate-note';
      details.textContent = 'Route activation is review-only. No in-game action is performed.';

      body.appendChild(createDetailDrawer({ summary: 'Why?', content: details }));
      card.appendChild(body);
      return card;
    }

    proposeRouteActivation(activeRoute) {
      if (!window.OmniEvents) return;
      window.OmniEvents.dispatchEvent(
        new CustomEvent('navigation:gate-proposal', {
          detail: {
            action: 'plot_route',
            destination: this._hasActiveRoute(activeRoute) ? activeRoute.destination : null,
            total_hops: this._hasActiveRoute(activeRoute) && Number.isFinite(activeRoute.total_hops)
              ? activeRoute.total_hops
              : null,
            caveat: 'Review only — no in-game action is performed.',
          },
          bubbles: false,
        }),
      );
    }

    _createLibraryCard(primitives, library, activeRoute) {
      const { createCommandCard } = primitives;
      const card = createCommandCard({ title: 'Route Library & Bookmarks' });
      card.id = 'navigation-route-library';
      const body = document.createElement('div');
      body.className = 'navigation-library-body';

      /* PB-PHASE10-SUPER-03 #6: honest degraded state when the local bookmark
         library cannot be read (e.g. a stale local DB). No empty controls, no
         raw tag-filter strings. */
      if (library && library.unavailable) {
        const note = document.createElement('p');
        note.className = 'navigation-fallback';
        note.textContent = 'Local bookmark library is unavailable right now.';
        const detail = document.createElement('p');
        detail.className = 'navigation-library-note';
        detail.textContent = 'Bookmarks could not be read from local storage this session.';
        body.append(note, detail);
        card.appendChild(body);
        return card;
      }

      const controls = document.createElement('div');
      controls.className = 'navigation-library-controls';

      if (this._hasActiveRoute(activeRoute)) {
        const saveBookmarkBtn = document.createElement('button');
        saveBookmarkBtn.className = 'navigation-library-btn';
        saveBookmarkBtn.type = 'button';
        saveBookmarkBtn.textContent = 'Bookmark Destination';
        saveBookmarkBtn.onclick = () => this.saveBookmark(activeRoute);
        controls.appendChild(saveBookmarkBtn);

        if (activeRoute.origin && activeRoute.total_hops > 0) {
          const saveRouteBtn = document.createElement('button');
          saveRouteBtn.className = 'navigation-library-btn';
          saveRouteBtn.type = 'button';
          saveRouteBtn.textContent = 'Save Current Route';
          saveRouteBtn.onclick = () => this.saveRoute(activeRoute);
          controls.appendChild(saveRouteBtn);
        }
      }
      body.appendChild(controls);

      if (library.bookmarks.length > 0) {
        body.appendChild(this._createBookmarkList(library.bookmarks));
      }

      if (library.saved_routes.length > 0) {
        body.appendChild(this._createSavedRouteList(library.saved_routes));
      }

      if (library.bookmarks.length === 0 && library.saved_routes.length === 0) {
        const empty = document.createElement('p');
        empty.className = 'navigation-fallback';
        empty.textContent = 'No local bookmarks or saved routes.';
        body.appendChild(empty);
      }

      /* PB-PHASE10-SUPER-03 #6: honest scope note — local bookmarks only; full
         route planning is deferred and OmniCOVAS never controls the game. */
      const scopeNote = document.createElement('p');
      scopeNote.className = 'navigation-library-note';
      scopeNote.textContent = 'Local bookmarks only. Route planning is a future feature; OmniCOVAS never sends routes to the game.';
      body.appendChild(scopeNote);

      card.appendChild(body);
      return card;
    }

    _createBookmarkList(bookmarks) {
      const wrapper = document.createElement('div');
      wrapper.className = 'navigation-library-section';
      const title = document.createElement('h4');
      title.className = 'navigation-library-subtitle';
      title.textContent = 'Bookmarks';
      wrapper.appendChild(title);

      const list = document.createElement('div');
      list.className = 'navigation-library-list';

      bookmarks.forEach((bm) => {
        const item = document.createElement('div');
        item.className = 'navigation-library-item';
        const info = document.createElement('div');
        info.className = 'navigation-library-item-info';
        const label = document.createElement('span');
        label.className = 'navigation-library-item-label';
        label.textContent = bm.label;
        const target = document.createElement('span');
        target.className = 'navigation-library-item-target';
        target.textContent = bm.target_name;
        info.append(label, target);
        item.appendChild(info);

        const deleteBtn = document.createElement('button');
        deleteBtn.className = 'navigation-library-delete-btn';
        deleteBtn.type = 'button';
        deleteBtn.textContent = '×';
        deleteBtn.title = 'Delete Bookmark';
        deleteBtn.onclick = () => this.deleteBookmark(bm.id);
        item.appendChild(deleteBtn);
        list.appendChild(item);
      });

      wrapper.appendChild(list);
      return wrapper;
    }

    _createSavedRouteList(routes) {
      const wrapper = document.createElement('div');
      wrapper.className = 'navigation-library-section';
      const title = document.createElement('h4');
      title.className = 'navigation-library-subtitle';
      title.textContent = 'Saved Routes';
      wrapper.appendChild(title);

      const list = document.createElement('div');
      list.className = 'navigation-library-list';

      routes.forEach((route) => {
        const item = document.createElement('div');
        item.className = 'navigation-library-item';
        const info = document.createElement('div');
        info.className = 'navigation-library-item-info';
        const label = document.createElement('span');
        label.className = 'navigation-library-item-label';
        label.textContent = route.label;
        const path = document.createElement('span');
        path.className = 'navigation-library-item-target';
        path.textContent = `${route.origin} → ${route.destination} (${route.hop_count} hops)`;
        info.append(label, path);
        item.appendChild(info);

        const deleteBtn = document.createElement('button');
        deleteBtn.className = 'navigation-library-delete-btn';
        deleteBtn.type = 'button';
        deleteBtn.textContent = '×';
        deleteBtn.title = 'Delete Saved Route';
        deleteBtn.onclick = () => this.deleteSavedRoute(route.id);
        item.appendChild(deleteBtn);
        list.appendChild(item);
      });

      wrapper.appendChild(list);
      return wrapper;
    }

    async saveBookmark(activeRoute) {
      if (!window.Shell || !window.Shell.httpBase) return;
      const label = window.prompt('Bookmark Label:', activeRoute.destination);
      if (!label) return;

      try {
        await window.fetch(window.Shell.httpBase + '/navigation/bookmarks', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            label: label,
            entity_type: 'system',
            target_name: activeRoute.destination,
            source_id: activeRoute.source_id,
          }),
        });
        this.fetchAndRender();
      } catch (err) {
        console.error('Failed to save bookmark:', err);
      }
    }

    async saveRoute(activeRoute) {
      if (!window.Shell || !window.Shell.httpBase) return;
      const label = window.prompt('Route Label:', `${activeRoute.origin} to ${activeRoute.destination}`);
      if (!label) return;

      try {
        await window.fetch(window.Shell.httpBase + '/navigation/saved-routes', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            label: label,
            origin: activeRoute.origin,
            destination: activeRoute.destination,
            hop_count: activeRoute.total_hops,
            source_id: activeRoute.source_id,
          }),
        });
        this.fetchAndRender();
      } catch (err) {
        console.error('Failed to save route:', err);
      }
    }

    async deleteBookmark(id) {
      if (!window.Shell || !window.Shell.httpBase) return;
      if (!window.confirm('Delete this bookmark?')) return;

      try {
        await window.fetch(window.Shell.httpBase + `/navigation/bookmarks/${id}`, {
          method: 'DELETE',
        });
        this.fetchAndRender();
      } catch (err) {
        console.error('Failed to delete bookmark:', err);
      }
    }

    async deleteSavedRoute(id) {
      if (!window.Shell || !window.Shell.httpBase) return;
      if (!window.confirm('Delete this saved route?')) return;

      try {
        await window.fetch(window.Shell.httpBase + `/navigation/saved-routes/${id}`, {
          method: 'DELETE',
        });
        this.fetchAndRender();
      } catch (err) {
        console.error('Failed to delete saved route:', err);
      }
    }

    _createChip(label, value) {
      const chip = document.createElement('span');
      chip.className = 'navigation-chip';
      chip.textContent = label + ': ' + (value || 'unknown');
      return chip;
    }

    _renderWaiting() {
      if (!this._root) return;
      const msg = document.createElement('p');
      msg.className = 'navigation-waiting';
      msg.textContent = 'Waiting for OmniCOVAS bridge.';
      const fallback = document.createElement('p');
      fallback.className = 'navigation-fallback';
      fallback.textContent = 'Fallback: Not Loaded';
      this._root.replaceChildren(msg, fallback);
    }

    renderUnavailable(message, fallbackText) {
      if (!this._root) return;

      this._renderWaiting();

      this._getPrimitives().then(primitives => {
        if (!primitives || !this._root.isConnected) return;
        const { createRouteHero, createEmptyState } = primitives;

        /* Only replace if still in waiting state. */
        if (this._root.querySelector('.navigation-waiting')) {
          const container = document.createElement('div');
          container.className = 'navigation-route';

          container.appendChild(createRouteHero({
            kicker: 'Route / Movement',
            title: 'Navigation',
            statusText: fallbackText || 'Not Loaded',
            statusVariant: 'not-loaded',
          }));

          container.appendChild(createEmptyState({
            status: 'Unavailable',
            reason: message,
          }));

          this._root.replaceChildren(container);
          this._applyRouteTransferArrival();
        }
      });
    }

    _applyRouteTransferArrival() {
      window.Shell?.applyRouteTransferArrival?.('/navigation', this._root);
    }

    /* Phase 9 PB09-04 — Campaign Circuits panel.
     *
     * Collapsed by default using <details>/<summary>.
     * Commander-entered values (circuit titles, system names) rendered
     * with textContent only — ADR 0003 compliant.
     * CampaignCircuit is NOT the active in-game route; the existing
     * hero / route / no-route display above is unchanged.
     */
    _createCampaignCircuitsPanel(circuitList) {
      const details = document.createElement('details');
      details.className = 'navigation-campaign-circuits';

      const summary = document.createElement('summary');
      summary.className = 'navigation-campaign-circuits-summary';
      const summaryTitle = document.createElement('span');
      summaryTitle.className = 'navigation-campaign-circuits-title';
      summaryTitle.textContent = 'Campaign circuits';
      const summaryCount = document.createElement('span');
      summaryCount.className = 'navigation-campaign-circuits-count';
      summaryCount.textContent = circuitList.length > 0
        ? String(circuitList.length) + ' saved'
        : 'None saved';
      summary.appendChild(summaryTitle);
      summary.appendChild(summaryCount);
      details.appendChild(summary);

      const body = document.createElement('div');
      body.className = 'navigation-campaign-circuits-body';

      if (circuitList.length === 0) {
        const empty = document.createElement('p');
        empty.className = 'navigation-campaign-circuits-empty';
        empty.textContent = 'No campaign circuits saved.';
        body.appendChild(empty);
      } else {
        circuitList.forEach((circuit) => {
          body.appendChild(this._createCircuitRow(circuit));
        });
      }

      details.appendChild(body);
      return details;
    }

    _createCircuitRow(circuit) {
      const row = document.createElement('div');
      row.className = 'navigation-circuit-row';

      const header = document.createElement('div');
      header.className = 'navigation-circuit-header';

      const title = document.createElement('span');
      title.className = 'navigation-circuit-title';
      title.textContent = circuit.title || '';
      header.appendChild(title);

      const typeChip = document.createElement('span');
      typeChip.className = 'navigation-chip navigation-chip--type';
      typeChip.textContent = circuit.workflow_type || '';
      header.appendChild(typeChip);

      const sourceChip = document.createElement('span');
      sourceChip.className = 'navigation-chip navigation-chip--source';
      sourceChip.textContent = circuit.source_label || '';
      header.appendChild(sourceChip);

      row.appendChild(header);

      const meta = document.createElement('div');
      meta.className = 'navigation-circuit-meta';

      const stopCount = document.createElement('span');
      stopCount.className = 'navigation-circuit-stop-count';
      const stops = Array.isArray(circuit.stops) ? circuit.stops : [];
      stopCount.textContent = String(stops.length) + ' stop' + (stops.length !== 1 ? 's' : '');
      meta.appendChild(stopCount);

      if (circuit.linked_campaign_id) {
        const campaignLink = document.createElement('button');
        campaignLink.type = 'button';
        campaignLink.id = 'nav-circuit-camp-link-' + circuit.circuit_id;
        campaignLink.className = 'navigation-circuit-campaign-link';
        campaignLink.textContent = 'View Campaign';
        /* PB09-08: use RouteTransferIntent to carry circuit_id back to Operations */
        campaignLink.onclick = () => {
          if (typeof window.Shell?.startRouteTransfer !== 'function') {
            window.location.hash = '#/operations';
            return;
          }
          const wsHint = `operations-phase9-${circuit.workflow_type || 'bgs'}-workspace`;
          window.Shell.startRouteTransfer({
            originRoute: '/navigation',
            originPackage: 'Navigation',
            originSectionId: 'navigation-campaign-circuits',
            targetRoute: '/operations',
            targetSectionId: wsHint,
            targetEntityId: circuit.linked_campaign_id,
            targetLabel: 'Operations campaign workspace',
            reason: 'Viewing campaign from circuit.',
            returnLabel: 'Return to Navigation',
            returnTarget: { route: '/navigation' },
          });
        };
        meta.appendChild(campaignLink);
      }

      if (circuit.circuit_id) {
        /* PB09-08: View Proof link to Activity Log */
        const proofBtn = document.createElement('button');
        proofBtn.type = 'button';
        proofBtn.id = 'nav-circuit-proof-link-' + circuit.circuit_id;
        proofBtn.className = 'navigation-circuit-proof-link';
        proofBtn.textContent = 'View Proof';
        proofBtn.onclick = () => {
          if (typeof window.Shell?.startRouteTransfer !== 'function') {
            window.location.hash = '#/activity-log';
            return;
          }
          window.Shell.startRouteTransfer({
            originRoute: '/navigation',
            originPackage: 'Navigation',
            originSectionId: 'navigation-campaign-circuits',
            targetRoute: '/activity-log',
            targetSectionId: 'log-body',
            targetEntityId: circuit.circuit_id,
            targetLabel: 'Activity Log proof',
            reason: 'Viewing circuit proof.',
            returnLabel: 'Return to Navigation',
            returnTarget: { route: '/navigation' },
          });
        };
        meta.appendChild(proofBtn);
      }

      row.appendChild(meta);

      if (stops.length > 0) {
        const stopsDetails = document.createElement('details');
        stopsDetails.className = 'navigation-circuit-stops-details';

        const stopsSummary = document.createElement('summary');
        stopsSummary.className = 'navigation-circuit-stops-summary';
        stopsSummary.textContent = 'Show stops';
        stopsDetails.appendChild(stopsSummary);

        const stopsList = document.createElement('ol');
        stopsList.className = 'navigation-circuit-stops-list';

        stops.forEach((stop) => {
          const li = document.createElement('li');
          li.className = 'navigation-circuit-stop';

          const sysName = document.createElement('span');
          sysName.className = 'navigation-circuit-stop-system';
          sysName.textContent = stop.system_name || '';
          li.appendChild(sysName);

          const intelBtn = document.createElement('button');
          intelBtn.type = 'button';
          intelBtn.id = 'nav-circuit-stop-intel-' + stop.stop_id;
          intelBtn.className = 'navigation-circuit-stop-intel-btn';
          intelBtn.textContent = 'Open in Intel';
          intelBtn.onclick = () => {
            window.location.hash = '#/intel';
          };
          li.appendChild(intelBtn);

          stopsList.appendChild(li);
        });

        stopsDetails.appendChild(stopsList);
        row.appendChild(stopsDetails);
      }

      return row;
    }
  }

  globalThis.__navigationExports = { NavigationController };
  new NavigationController();
})();
