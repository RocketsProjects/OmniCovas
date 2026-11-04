/**
 * Phase 3 Week 13 — Activity Log Controller
 *
 * Full-featured activity log with:
 *  - Filtering by category
 *  - Free-text search
 *  - Pagination (50 rows per page)
 *  - Export to JSON
 *  - Clear with confirmation
 */

const LOG_VIEWS = Object.freeze([
  { id: 'events', label: 'Events', sectionId: 'log-section-events' },
  { id: 'sources', label: 'Sources', sectionId: 'log-section-sources' },
  { id: 'known-data', label: 'Known Data', sectionId: 'log-section-known-data' },
  { id: 'proof', label: 'Proof', sectionId: 'log-section-proof' },
  { id: 'diagnostics', label: 'Diagnostics', sectionId: 'log-section-diagnostics' }
]);

const SECONDARY_FILTERS = Object.freeze([
  { value: 'recent', label: 'Recent' },
  { value: 'source', label: 'Source events' },
  { value: 'blocked', label: 'Blocked requests' },
  { value: 'gate', label: 'Confirmation gate' },
  { value: 'operations', label: 'Operations' },
  { value: 'engineering', label: 'Engineering' },
  { value: 'memory', label: 'Commander Memory' },
  { value: 'startup', label: 'Startup outcomes' },
  { value: 'phase9-bgs', label: 'Phase 9 BGS' },
  { value: 'phase9-powerplay', label: 'Phase 9 Powerplay' },
  { value: 'phase9-campaign', label: 'Phase 9 Campaign' },
  { value: 'phase9-navigation', label: 'Phase 9 Navigation' },
  { value: 'phase9-squadron', label: 'Phase 9 Squadron' },
  { value: 'phase9-source-attempts', label: 'Phase 9 Source attempts' },
  { value: 'phase9-ai-drafts', label: 'Phase 9 AI drafts' },
  { value: 'handoffs', label: 'Route handoffs' },
  { value: 'errors', label: 'Errors / warnings' },
  { value: 'raw', label: 'Raw/proof only' }
]);

const SENSITIVE_TEXT_EVENTS = Object.freeze(new Set([
  'RECEIVETEXT',
  'SENDTEXT'
]));

const SENSITIVE_IDENTITY_EVENTS = Object.freeze([
  'LOADGAME',
  'NEWCOMMANDER',
  'CLEARSAVEDGAME',
  'FRIENDS',
  'WING',
  'SQUADRON',
  'PVP',
  'CREW'
]);

const SENSITIVE_PAYLOAD_KEYS = Object.freeze(new Set([
  'message',
  'message_localised',
  'text',
  'from',
  'to',
  'sender',
  'recipient',
  'commander',
  'commandername',
  'commander_name',
  'cmdr',
  'fid',
  'frontierid',
  'frontier_id',
  'account',
  'accountid',
  'account_id'
]));

const IDENTITY_PAYLOAD_KEYS = Object.freeze(new Set([
  'name',
  'localisedname',
  'localised_name',
  'shipname',
  'ship_name',
  'squadronname',
  'squadron_name'
]));

const PHASE_9_ALLOWED_PAYLOAD_KEYS = Object.freeze(new Set([
  'ai_provider_name',
  'blocked_reason',
  'bookmark_id',
  'campaign_id',
  'candidate_sources',
  'changed_fields',
  'circuit_id',
  'confidence_label',
  'exported',
  'fallback_wording_shown',
  'fact_id',
  'field_count',
  'is_fact',
  'is_fact_source',
  'kb_excerpt_count',
  'kb_reference_count',
  'linked_campaign_id',
  'linked_count',
  'linked_intel_fact_count',
  'linked_intel_fact_id',
  'linked_navigation_circuit_count',
  'needs_review_count',
  'note_id',
  'order_index',
  'previous_state',
  'projected_fields',
  'redacted',
  'redaction_state',
  'rejection_reason',
  'requested_fact',
  'source_chain',
  'source_count',
  'source_label',
  'source_type',
  'state',
  'stop_count',
  'stop_id',
  'tag',
  'title_length',
  'workflow_type'
]));

const PHASE_9_ALLOWED_SOURCE_CHAIN_KEYS = Object.freeze([
  'source',
  'source_type',
  'source_event',
  'truth_class',
  'freshness',
  'workflow_type',
  'blocked_reason',
  'kind',
  'fact_id',
  'kb_file',
  'entry_id',
  'needs_review'
]);

const ENTITY_DIMENSIONS = Object.freeze({
  system: Object.freeze(['system', 'system_name', 'star_system', 'starsystem']),
  station: Object.freeze(['station', 'station_name']),
  commodity: Object.freeze(['commodity', 'commodity_name', 'commodity_localised']),
  module: Object.freeze(['module', 'module_name', 'module_type']),
  ship: Object.freeze(['ship', 'ship_type', 'ship_model']),
  mission: Object.freeze(['mission', 'mission_id', 'mission_name']),
  route: Object.freeze(['route', 'route_id', 'destination', 'target_system', 'circuit_id']),
  event: Object.freeze(['event_type', 'event', 'source_event']),
  session: Object.freeze(['session', 'session_id']),
  source: Object.freeze(['source', 'source_id', 'source_type']),
  file: Object.freeze(['file', 'filename', 'source_file', 'journal_filename']),
});

const ENTITY_DIMENSION_KEYS = Object.freeze(Object.keys(ENTITY_DIMENSIONS));
const ENTITY_VALUE_LIMIT = 64;

function normalizeText(value) {
  return String(value || '').trim().toLowerCase();
}

function normalizeSummaryIdentity(value) {
  return normalizeText(value).replace(/[^a-z0-9]+/g, ' ').trim();
}

function normalizeEventType(entry) {
  return String(entry?.event_type || entry?.event || '').trim().toUpperCase();
}

function rawEventType(entry) {
  return String(entry?.event_type || entry?.event || '').trim();
}

let activeActivityLogController = null;
let pendingActivityLogIntent = null;

class ActivityLogController {
  constructor() {
    this.allEntries = [];
    this.filteredEntries = [];
    this.currentPage = 0;
    this.pageSize = 50;
    this.activeView = 'events';
    this.sortMode = 'newest';
    this._loadedOnce = false;
    activeActivityLogController = this;
    this._primitivesPromise = Promise.all([
      import('../components/command-primitives.js').catch(e => {
        console.error('[ActivityLog] Failed to load command primitives:', e);
        return null;
      }),
      import('../components/source-proof.js').catch(e => {
        console.error('[ActivityLog] Failed to load source proof:', e);
        return null;
      }),
      import('../utils/display-names.js').catch(e => {
        console.error('[ActivityLog] Failed to load display names:', e);
        return null;
      })
    ]).then(([cp, sp, displayNames]) => {
      this._primitives = cp;
      this._sourceProof = sp;
      this._displayNames = displayNames;
      return cp;
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

  /** Route a protected local action through the one shared Commander gate. */
  async confirmProtectedAction(options) {
    const gate = window.OmniConfirmationGate;
    if (!gate?.confirmLocalAction) {
      console.error('[ActivityLog] Shared Confirmation Gate is unavailable.');
      return false;
    }
    return gate.confirmLocalAction(options);
  }

  /** Show a non-blocking result through the same shared gate surface. */
  notify(message, kind = 'info') {
    if (window.OmniConfirmationGate?.announce) {
      window.OmniConfirmationGate.announce(message, { kind });
    } else {
      console.info(`[ActivityLog] ${message}`);
    }
  }

  async init() {
    this.rebuildFilters();
    this.bindEvents();
    if (!this.apiBase) {
      this._showWaiting();
      window.OmniEvents?.addEventListener('bridge-connected', () => this._loadAndRender(), { once: true });
      return;
    }
    await this._loadAndRender();
  }

  rebuildFilters() {
    this.rebuildViewControls();
    this.rebuildSecondaryFilters();
  }

  rebuildViewControls() {
    const viewNav = document.querySelector('.log-section-nav');
    if (!viewNav) return;

    viewNav.replaceChildren();
    viewNav.classList.add('route-subnav');
    viewNav.setAttribute('role', 'tablist');
    viewNav.setAttribute('aria-label', 'Activity Log category views');

    LOG_VIEWS.forEach((view, index) => {
      const button = document.createElement('button');
      button.type = 'button';
      button.className = 'log-section-link log-view-tab';
      button.dataset.logView = view.id;
      button.setAttribute('role', 'tab');
      button.setAttribute('aria-controls', view.sectionId);
      button.textContent = view.label;
      if (index === 0 && !this.activeView) {
        this.activeView = view.id;
      }
      viewNav.appendChild(button);
    });

    this.updateViewControls();
  }

  rebuildSecondaryFilters() {
    const filterGroup = document.querySelector('.log-filter-group');
    if (!filterGroup) return;

    filterGroup.replaceChildren();
    const groups = [
      {
        label: 'Scope',
        values: ['recent', 'source', 'blocked', 'gate', 'operations', 'engineering', 'memory', 'startup'],
      },
      {
        label: 'Phase 9',
        values: [
          'phase9-bgs',
          'phase9-powerplay',
          'phase9-campaign',
          'phase9-navigation',
          'phase9-squadron',
          'phase9-source-attempts',
          'phase9-ai-drafts',
        ],
      },
      { label: 'Other', values: ['handoffs', 'errors', 'raw'] },
    ];
    const byValue = new Map(SECONDARY_FILTERS.map((filter) => [filter.value, filter]));
    const assigned = new Set(groups.slice(0, 2).flatMap((group) => group.values));
    const explicitOther = new Set(groups[2].values);
    groups[2].values = SECONDARY_FILTERS
      .map((filter) => filter.value)
      .filter((value) => explicitOther.has(value) || !assigned.has(value));

    const addFilter = (target, f) => {
      const id = `log-filter-secondary-${f.value}`;
      const label = document.createElement('label');
      label.className = 'log-filter-label';
      label.setAttribute('for', id);
      const input = document.createElement('input');
      input.type = 'checkbox';
      input.className = 'log-filter';
      input.id = id;
      input.name = id;
      input.value = f.value;
      label.appendChild(input);
      label.appendChild(document.createTextNode(' ' + f.label));
      target.appendChild(label);
    };

    groups.forEach((group) => {
      if (group.values.length === 0) return;
      const groupWrap = document.createElement('fieldset');
      groupWrap.className = 'log-filter-subgroup';
      const legend = document.createElement('legend');
      legend.textContent = group.label;
      groupWrap.appendChild(legend);
      group.values.forEach((value) => {
        const filter = byValue.get(value);
        if (filter) addFilter(groupWrap, filter);
      });
      filterGroup.appendChild(groupWrap);
    });
  }

  _showWaiting() {
    this.clearViewPanelContents();
    const activeMount = this.getViewPanelMount(this.getActiveView());
    if (activeMount && activeMount.id !== 'log-body') {
      activeMount.appendChild(this.createPanelEmpty('Waiting for OmniCOVAS bridge…'));
      this.updateViewControls();
      return;
    }

    const tbody = document.getElementById('log-body');
    if (!tbody) return;
    const tr = document.createElement('tr');
    const td = document.createElement('td');
    td.colSpan = 5;
    td.className = 'log-waiting';
    td.textContent = 'Waiting for OmniCOVAS bridge…';
    tr.appendChild(td);
    tbody.replaceChildren(tr);
  }

  getActiveView() {
    const view = LOG_VIEWS.find(v => v.id === this.activeView);
    return view ? view.id : 'events';
  }

  activateView(viewId) {
    if (!LOG_VIEWS.some(view => view.id === viewId)) return;
    this.activeView = viewId;
    this.currentPage = 0;
    this.updateViewControls();
    this._computeFilteredEntries();
    this.renderPage();
  }

  updateViewControls() {
    const activeView = this.getActiveView();
    document.querySelectorAll('.log-view-tab').forEach((button) => {
      const isActive = button.dataset.logView === activeView;
      button.classList.toggle('is-active', isActive);
      button.setAttribute('aria-selected', isActive ? 'true' : 'false');
      button.setAttribute('tabindex', isActive ? '0' : '-1');
    });

    LOG_VIEWS.forEach((view) => {
      const section = document.getElementById(view.sectionId);
      if (!section) return;
      const isActive = view.id === activeView;
      section.hidden = !isActive;
      section.dataset.logViewActive = isActive ? 'true' : 'false';
    });
  }

  focusAdjacentView(currentButton, direction) {
    const buttons = Array.from(document.querySelectorAll('.log-view-tab'));
    const index = buttons.indexOf(currentButton);
    if (index === -1 || buttons.length === 0) return;
    const nextIndex = (index + direction + buttons.length) % buttons.length;
    const next = buttons[nextIndex];
    next.focus();
    this.activateView(next.dataset.logView);
  }

  async _loadAndRender() {
    this.renderRouteHero();
    await this.loadActivityLog();
    this.renderRouteHero();
    await this.renderPage();
    await this.applyRouteTransferArrival();
  }

  async renderRouteHero() {
    const Primitives = await this._primitivesPromise;
    if (!Primitives) return;

    const container = document.getElementById('view-activity-log');
    if (!container) return;

    container.querySelector('.route-hero')?.remove();
    container.querySelector('.ocv-page-header')?.remove();
    const latest = this.allEntries[0] ? this.formatEventLabel(this.allEntries[0]) : 'None';

    const hero = Primitives.createRouteHero({
      title: 'Activity Log',
      kicker: 'Local event record',
      statusText: this.allEntries.length > 0 ? 'Local events available' : (this.apiBase ? 'No events loaded' : 'Bridge not ready'),
      statusVariant: this.allEntries.length > 0 ? 'available' : (this.apiBase ? 'off' : 'not-loaded'),
      primaryValues: [
        { label: 'Events shown', value: this.filteredEntries.length },
        { label: 'Latest', value: latest }
      ]
    });

    container.prepend(hero);
  }

  async loadActivityLog() {
    const url = this.apiUrl('/activity-log');
    if (!url) return;
    try {
      const res = await fetch(url);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      this.allEntries = data.entries || [];
      const startupEntry = this.createStartupOutcomeEntry(window.Shell?.startupOutcome);
      if (startupEntry) this.allEntries.push(startupEntry);
      this.filteredEntries = [...this.allEntries];
      this._loadedOnce = true;
    } catch (err) {
      console.error("Failed to load activity log:", err);
      this.allEntries = [];
      this.filteredEntries = [];
      this._loadedOnce = true;
    }
  }

  bindEvents() {
    document.querySelectorAll('.log-view-tab').forEach((button) => {
      button.addEventListener('click', () => {
        this.activateView(button.dataset.logView);
      });
      button.addEventListener('keydown', (event) => {
        if (event.key === 'ArrowRight') {
          event.preventDefault();
          this.focusAdjacentView(button, 1);
        }
        if (event.key === 'ArrowLeft') {
          event.preventDefault();
          this.focusAdjacentView(button, -1);
        }
      });
    });

    // Search
    document.getElementById("log-search")?.addEventListener("input", (e) => {
      this.filterAndRender(e.target.value);
    });

    // Filters
    document.querySelectorAll(".log-filter").forEach((checkbox) => {
      checkbox.addEventListener("change", () => {
        this.applyFilters();
      });
    });

    document.getElementById("log-category-filter")?.addEventListener("change", () => {
      this.applyFilters();
    });

    document.getElementById('log-entity-filter')?.addEventListener('change', () => {
      this.applyFilters();
    });

    document.getElementById('log-sort')?.addEventListener('change', (event) => {
      this.sortMode = event.target.value;
      this.applyFilters();
    });

    window.addEventListener('omnicovas:startup-outcome', (event) => {
      const withoutStartup = this.allEntries.filter((entry) => normalizeEventType(entry) !== 'STARTUP_OUTCOME');
      const startupEntry = this.createStartupOutcomeEntry(event.detail);
      this.allEntries = startupEntry ? [...withoutStartup, startupEntry] : withoutStartup;
      this._computeFilteredEntries();
      this.renderPage();
    });

    const moreFilters = document.getElementById('log-more-filters');
    const moreFiltersSummary = moreFilters?.querySelector('[data-section-id="more-filters"]');
    moreFilters?.addEventListener('toggle', () => {
      const open = moreFilters.open;
      moreFiltersSummary?.classList.toggle('is-active', open);
      moreFiltersSummary?.setAttribute('aria-expanded', open ? 'true' : 'false');
      if (moreFiltersSummary) moreFiltersSummary.dataset.active = open ? 'true' : 'false';
    });

    // Actions
    document.getElementById("log-export-btn")?.addEventListener("click", () => {
      this.exportLog();
    });

    document.getElementById("log-clear-btn")?.addEventListener("click", () => {
      this.showClearConfirm();
    });

    // Pagination
    document.getElementById("log-prev-btn")?.addEventListener("click", () => {
      if (this.currentPage > 0) {
        this.currentPage--;
        this.renderPage();
      }
    });

    document.getElementById("log-next-btn")?.addEventListener("click", () => {
      const maxPage = Math.ceil(this.filteredEntries.length / this.pageSize) - 1;
      if (this.currentPage < maxPage) {
        this.currentPage++;
        this.renderPage();
      }
    });
  }

  _computeFilteredEntries() {
    const searchEl = document.getElementById("log-search");
    const text = (searchEl?.value || "").toLowerCase();
    const activeView = this.getActiveView();
    const selectedCategory = document.getElementById("log-category-filter")?.value || 'all';
    const selectedEntity = document.getElementById('log-entity-filter')?.value || 'all';

    const selectedCategories = new Set();
    document.querySelectorAll(".log-filter:checked").forEach((cb) => {
      selectedCategories.add(cb.value);
    });

    this.filteredEntries = this.allEntries.filter((entry) => {
      if (text) {
        const searchable = this.getSearchableText(entry, selectedEntity);
        if (!searchable.includes(text)) {
           return false;
        }
      }
      const categories = this.getEventCategories(entry);
      if (!categories.includes(activeView)) {
        return false;
      }
      if (selectedCategory !== 'all' && !categories.includes(selectedCategory)) {
        return false;
      }
      if (selectedCategories.size > 0) {
        let match = false;
        for (const cat of categories) {
           if (selectedCategories.has(cat)) {
              match = true;
              break;
           }
        }
        if (!match) return false;
      }
      return true;
    });

    this.filteredEntries = this.sortEntries(this.filteredEntries, document.getElementById('log-sort')?.value || this.sortMode);

    this.currentPage = 0;
  }

  filterAndRender(_searchText) {
    this._computeFilteredEntries();
    this.renderPage();
  }

  applyFilters() {
    this._computeFilteredEntries();
    this.renderPage();
  }

  getHumanSummary(entry) {
    const type = (entry.event_type || '').toUpperCase();
    if (type === 'STARTUP_OUTCOME') return 'Local startup lifecycle outcome for this app session';
    if (type.startsWith('COMMANDER_MEMORY_')) {
      if (type.includes('PROPOSAL_')) return 'Commander Memory confirmation decision recorded';
      if (type.includes('EXPORT_')) return 'Commander Memory export lifecycle record';
      return entry.summary || 'Commander Memory local action recorded';
    }
    if (this.isPhase9Entry(entry)) {
      const lowerType = rawEventType(entry).toLowerCase();
      if (lowerType.startsWith('phase_9.bgs.')) {
        return 'Local BGS evidence record';
      }
      if (lowerType.startsWith('phase_9.powerplay.')) {
        return 'Local Powerplay evidence record';
      }
      if (lowerType.startsWith('phase_9.campaign.ai_draft')) {
        return 'Commander-requested AI draft audit record; not a fact';
      }
      if (lowerType.startsWith('phase_9.campaign.')) {
        return 'Local campaign workflow record';
      }
      if (lowerType.startsWith('phase_9.navigation.')) {
        return 'Local navigation workflow record';
      }
      if (lowerType.startsWith('phase_9.squadron.')) {
        return 'Local-only squadron coordination record';
      }
      if (lowerType.startsWith('phase_9.source_attempt')) {
        return 'Source capability decision record';
      }
      return 'Phase 9 audit record';
    }
    if (SENSITIVE_TEXT_EVENTS.has(type)) return 'Text event recorded; private message redacted';
    if (SENSITIVE_IDENTITY_EVENTS.some(marker => type.includes(marker))) {
      return 'Identity or social event recorded; private fields redacted';
    }
    if (type === 'LOCAL_CONFLICT_CONTEXT_UPDATED') return 'Conflict context updated';
    if (type === 'ENGINEERING.SOURCE_ATTEMPT.BLOCKED') return 'Engineering source attempt blocked';
    if (type.startsWith('ENGINEERING.')) {
      if (entry.summary) return entry.summary;
      return 'Engineering planning record updated';
    }
    if (type.includes('BLOCKED')) return 'External request blocked';
    if (type.includes('CONFIRMATION') || type.includes('PROPOSAL')) return 'Confirmation decision recorded';
    if (entry.summary && entry.summary !== '—') return entry.summary;

    if (type.includes('TRANSFER') || type.includes('HANDOFF')) return 'Route handoff initiated';
    if (type.includes('ERROR') || type.includes('WARN') || type.includes('CRITICAL')) return 'Warning / Error recorded';
    if (type.startsWith('SOURCE_')) return 'Source data updated';

    return 'Event recorded';
  }

  getDistinctHumanSummary(entry) {
    const summary = this.getHumanSummary(entry);
    const label = this.formatEventLabel(entry);
    return normalizeSummaryIdentity(summary) === normalizeSummaryIdentity(label)
      ? ''
      : summary;
  }

  getSearchableText(entry, dimension = 'all') {
    if (dimension !== 'all' && ENTITY_DIMENSION_KEYS.includes(dimension)) {
      return this.getEntityValues(entry, dimension).join(' ').toLowerCase();
    }
    const payload = entry?.payload && typeof entry.payload === 'object' ? entry.payload : {};
    const safePayload = this.isPhase9Entry(entry) ? this.getPhase9DisplayPayload(entry) : payload;
    const payloadKeys = Object.keys(safePayload);
    const parts = [
      entry?.event_type,
      this.formatEventLabel(entry),
      this.getHumanSummary(entry),
      entry?.source,
      entry?.category,
      entry?.matrix_status,
      entry?.classification,
      entry?.home_status,
      ...payloadKeys,
      ...ENTITY_DIMENSION_KEYS.flatMap((key) => this.getEntityValues(entry, key)),
    ];

    if (!this.isPrivacySensitiveEntry(entry)) {
      parts.push(entry?.summary);
      parts.push(...Object.values(safePayload).filter(value => typeof value !== 'object').map(value => String(value)));
    }

    return parts.filter(Boolean).join(' ').toLowerCase();
  }

  getEntityValues(entry, dimension) {
    const keys = new Set(ENTITY_DIMENSIONS[dimension] || []);
    if (keys.size === 0) return [];
    const values = [];
    const seen = new Set();
    const add = (value) => {
      if (values.length >= ENTITY_VALUE_LIMIT || value === null || value === undefined) return;
      if (!['string', 'number'].includes(typeof value)) return;
      const text = String(value).trim();
      const normalized = text.toLowerCase();
      if (!text || text.length > 160 || seen.has(normalized)) return;
      seen.add(normalized);
      values.push(text);
    };
    const walk = (value, depth = 0) => {
      if (!value || depth > 3 || values.length >= ENTITY_VALUE_LIMIT) return;
      if (Array.isArray(value)) {
        value.slice(0, 20).forEach((item) => walk(item, depth + 1));
        return;
      }
      if (typeof value !== 'object') return;
      Object.entries(value).slice(0, 80).forEach(([rawKey, item]) => {
        const key = this.normalizePayloadKey(rawKey);
        if (keys.has(key)) add(item);
        if (item && typeof item === 'object') walk(item, depth + 1);
      });
    };

    if (dimension === 'event') {
      add(entry?.event_type ?? entry?.event);
      add(this.formatEventLabel(entry));
    }
    if (dimension === 'source') add(entry?.source);
    if (!this.isPrivacySensitiveEntry(entry)) {
      walk(entry?.payload);
      walk(entry?.linked_entity_refs);
      walk(entry?.source_chain);
    }
    return values;
  }

  sortEntries(entries, mode = 'newest') {
    const timestamp = (entry) => Date.parse(entry?.timestamp || '') || 0;
    const source = (entry) => normalizeText(entry?.source || 'activity_log');
    const event = (entry) => normalizeText(entry?.event_type || entry?.event);
    return entries.map((entry, index) => ({ entry, index })).sort((a, b) => {
      if (mode === 'oldest') return timestamp(a.entry) - timestamp(b.entry) || a.index - b.index;
      if (mode === 'source') {
        return source(a.entry).localeCompare(source(b.entry))
          || timestamp(b.entry) - timestamp(a.entry)
          || event(a.entry).localeCompare(event(b.entry))
          || a.index - b.index;
      }
      if (mode === 'event') {
        return event(a.entry).localeCompare(event(b.entry))
          || timestamp(b.entry) - timestamp(a.entry)
          || source(a.entry).localeCompare(source(b.entry))
          || a.index - b.index;
      }
      return timestamp(b.entry) - timestamp(a.entry) || a.index - b.index;
    }).map(({ entry }) => entry);
  }

  createStartupOutcomeEntry(outcome) {
    if (!outcome || typeof outcome !== 'object' || !outcome.stage) return null;
    return {
      event_type: 'STARTUP_OUTCOME',
      timestamp: outcome.timestamp || new Date().toISOString(),
      summary: `Startup finished as ${String(outcome.stage).replace(/_/g, ' ')}`,
      source: 'local_startup_lifecycle',
      category: 'telemetry',
      payload: {
        stage: String(outcome.stage),
        bridge: String(outcome.bridge || 'unknown'),
        local_sources: String(outcome.local_sources || 'unknown'),
        session_state: String(outcome.session_state || 'unknown'),
        persistence: 'session_only',
        redacted: true,
      },
    };
  }

  getEventCategories(entry) {
    const categories = [];
    const type = (entry.event_type || '').toUpperCase();
    const lowerType = rawEventType(entry).toLowerCase();
    const source = (entry.source || '').toLowerCase();

    categories.push('events');
    categories.push('proof');
    categories.push('recent');
    categories.push('raw');
    categories.push(this.resolveCategory(entry));

    if (type.startsWith('SOURCE_') || type.startsWith('EXTERNAL_REQUEST_') || source === 'local_telemetry' || source === 'local_event_history') categories.push('source');
    if (this.isSourceEntry(entry)) categories.push('sources');
    if (this.isKnownDataEntry(entry)) categories.push('known-data');
    if (this.isDiagnosticEntry(entry)) categories.push('diagnostics');
    if (type.includes('BLOCKED') || (entry.payload && entry.payload.blocked === true) || source === 'external_disabled') categories.push('blocked');
    if (type.includes('CONFIRMATION') || type.includes('PROPOSAL') || type.includes('GATE')) categories.push('gate');
    if (type.includes('COMBAT') || type.includes('TRADE') || type.includes('MINING') || type.includes('SQUADRON') || type.includes('EXPLORATION') || type.includes('DOCKED') || type.includes('FSD')) categories.push('operations');
    if (type.startsWith('ENGINEERING.') || entry.category === 'engineering') categories.push('engineering');
    if (type.startsWith('COMMANDER_MEMORY_') || source.includes('commander_memory')) categories.push('memory', 'source', 'known-data');
    if (type === 'STARTUP_OUTCOME') categories.push('startup', 'diagnostics');
    if (lowerType.startsWith('phase_9.bgs.')) categories.push('phase9-bgs', 'source', 'known-data');
    if (lowerType.startsWith('phase_9.powerplay.')) categories.push('phase9-powerplay', 'source', 'known-data');
    if (lowerType.startsWith('phase_9.campaign.')) categories.push('phase9-campaign', 'operations');
    if (lowerType.startsWith('phase_9.navigation.')) categories.push('phase9-navigation', 'operations');
    if (lowerType.startsWith('phase_9.squadron.')) categories.push('phase9-squadron', 'operations');
    if (lowerType === 'phase_9.source_attempt_blocked' || lowerType.startsWith('phase_9.source_attempt_') || lowerType.startsWith('phase_9.source_attempt.')) categories.push('phase9-source-attempts', 'source', 'blocked', 'diagnostics');
    if (lowerType.startsWith('phase_9.campaign.ai_draft')) categories.push('phase9-ai-drafts', 'gate');
    if (type.includes('TRANSFER') || type.includes('HANDOFF') || (entry.payload && entry.payload.route_intent)) categories.push('handoffs');
    if (type.includes('ERROR') || type.includes('WARN') || type.includes('CRITICAL')) categories.push('errors');

    return categories;
  }

  isSourceEntry(entry) {
    const type = normalizeEventType(entry);
    const source = normalizeText(entry?.source);
    return (
      type.startsWith('SOURCE_') ||
      type.startsWith('EXTERNAL_REQUEST_') ||
      source.includes('journal') ||
      source.includes('status') ||
      source.includes('local_') ||
      source.endsWith('.json') ||
      source.includes('external') ||
      source.includes('engineering') ||
      Boolean(entry?.source_chain) ||
      Boolean(entry?.payload?.source_id || entry?.payload?.source || entry?.payload?.provider)
    );
  }

  isKnownDataEntry(entry) {
    const type = normalizeEventType(entry);
    const source = normalizeText(entry?.source);
    const text = `${type} ${source} ${normalizeText(entry?.summary)}`;
    return (
      source.endsWith('.json') ||
      source.includes('journal') ||
      source.includes('local_telemetry') ||
      source.includes('local_event_history') ||
      /STATUS|STATE|SNAPSHOT|CARGO|MARKET|SHIPYARD|OUTFITTING|MODULE|MISSION|MATERIAL|POWERPLAY|RANK|LOADOUT|LOCATION/.test(text)
    );
  }

  isDiagnosticEntry(entry) {
    const type = normalizeEventType(entry);
    const text = `${type} ${normalizeText(entry?.summary)} ${normalizeText(entry?.classification)} ${normalizeText(entry?.matrix_status)} ${normalizeText(entry?.home_status)} ${normalizeText(entry?.payload?.classification)} ${normalizeText(entry?.payload?.matrix_status)} ${normalizeText(entry?.payload?.home_status)}`;
    return /DIAGNOSTIC|ERROR|WARN|CRITICAL|BLOCKED|CONFLICT|AMBIGUOUS|DEFERRED|RESERVED|UNSUPPORTED|NO_VERIFIED_SOURCE/.test(text);
  }

  // Retained for backward compatibility with older tests if they spy on it
  resolveCategory(entry) {
    const validCategories = new Set(["critical", "extended", "ai", "telemetry", "source", "engineering"]);
    if (entry && entry.category && validCategories.has(entry.category)) {
      return entry.category;
    }
    return this.getEventCategory(entry ? entry.event_type : "");
  }

  // Retained for backward compatibility with older tests
  getEventCategory(eventType) {
    if (!eventType) return "telemetry";

    const type = eventType.toUpperCase();
    if (
      type.includes("TIER_3") ||
      type.includes("CONFIRMATION") ||
      type.includes("PROPOSAL")
    )
      return "ai";
    if (type.includes("CRITICAL") || type.includes("DESTROYED")) return "critical";
    if (type.includes("DOCKED") || type.includes("WANTED") || type.includes("FSD"))
      return "extended";
    if (type.startsWith("SOURCE_") || type.startsWith("EXTERNAL_REQUEST_"))
      return "source";
    if (type.startsWith("ENGINEERING.")) return "engineering";
    if (type.startsWith("PHASE_9.")) return "source";
    return "telemetry";
  }

  async renderPage() {
    await this._primitivesPromise; // Ensure modules are loaded
    this.updateViewControls();
    this.renderViewPanels();
    this.updatePagination();
  }

  renderViewPanels() {
    const activeView = this.getActiveView();
    this.clearViewPanelContents();
    if (activeView === 'events') this.renderEventsPanel();
    if (activeView === 'sources') this.renderSourcesPanel();
    if (activeView === 'known-data') this.renderKnownDataPanel();
    if (activeView === 'proof') this.renderProofPanel();
    if (activeView === 'diagnostics') this.renderDiagnosticsPanel();
  }

  getViewPanelMount(viewId) {
    const mounts = {
      events: 'log-entries',
      sources: 'log-sources-view',
      'known-data': 'log-body',
      proof: 'log-proof-view',
      diagnostics: 'log-diagnostics-view',
    };
    return document.getElementById(mounts[viewId] || '');
  }

  clearViewPanelContents() {
    LOG_VIEWS.forEach((view) => {
      this.getViewPanelMount(view.id)?.replaceChildren();
    });
  }

  getPageEntries(entries = this.filteredEntries) {
    const start = this.currentPage * this.pageSize;
    return entries.slice(start, start + this.pageSize);
  }

  renderKnownDataPanel() {
    const tbody = document.getElementById('log-body');
    if (!tbody) return;

    if (this.filteredEntries.length === 0) {
      const tr = document.createElement('tr');
      const td = document.createElement('td');
      td.colSpan = 5;
      if (this._primitives) {
        td.appendChild(this._primitives.createEmptyState({
          status: this.apiBase ? 'No matching known-data records' : 'Bridge not ready',
          reason: this.apiBase
            ? 'Try adjusting your filters or search text.'
            : 'Waiting for OmniCOVAS bridge connection.',
        }));
      } else {
        td.className = 'log-waiting';
        td.textContent = this.apiBase
          ? 'No matching known-data records'
          : 'Waiting for OmniCOVAS bridge…';
      }
      tr.appendChild(td);
      tbody.appendChild(tr);
      return;
    }

    this.getPageEntries().forEach((entry) => {
      tbody.appendChild(this.createLogRow(entry));
    });
  }

  renderEventsPanel() {
    const timeline = document.getElementById('log-entries');
    if (!timeline) return;
    timeline.replaceChildren();

    if (this.filteredEntries.length === 0) {
      timeline.appendChild(this.createPanelEmpty('No event rows match the current Activity Log view.'));
      return;
    }

    this.getPageEntries().forEach((entry) => {
      const item = document.createElement('article');
      item.className = `log-entry ${this.resolveCategory(entry)}`;
      item.dataset.logEventType = entry.event_type || 'unknown';

      const time = document.createElement('span');
      time.className = 'log-time';
      time.textContent = this.formatTimestamp(entry.timestamp || '');

      const type = document.createElement('span');
      type.className = 'log-type';
      type.textContent = this.formatEventLabel(entry);

      item.append(time, type);
      const distinctSummary = this.getDistinctHumanSummary(entry);
      if (distinctSummary) {
        const msg = document.createElement('span');
        msg.className = 'log-msg';
        msg.textContent = distinctSummary;
        item.appendChild(msg);
      }
      timeline.appendChild(item);
    });
  }

  renderSourcesPanel() {
    const panel = document.getElementById('log-sources-view');
    if (!panel) return;
    panel.replaceChildren();

    if (this.filteredEntries.length === 0) {
      panel.appendChild(this.createPanelEmpty('No source or provenance rows match the current filters.'));
      return;
    }

    const list = document.createElement('ul');
    list.className = 'log-view-list';
    this.getPageEntries().forEach((entry) => {
      const item = document.createElement('li');
      item.className = 'log-view-list-item';
      const fields = [
        this.createInlineLabel('Source', entry.source || 'activity_log'),
        this.createInlineLabel('Event', this.formatEventLabel(entry)),
      ];
      const distinctSummary = this.getDistinctHumanSummary(entry);
      if (distinctSummary) {
        fields.push(this.createInlineLabel('Summary', distinctSummary));
      }
      item.append(...fields);
      list.appendChild(item);
    });
    panel.appendChild(list);
  }

  renderProofPanel() {
    const panel = document.getElementById('log-proof-view');
    if (!panel) return;
    panel.replaceChildren();

    if (this.filteredEntries.length === 0) {
      panel.appendChild(this.createPanelEmpty('No proof rows match the current filters.'));
      return;
    }

    this.getPageEntries().forEach((entry) => {
      panel.appendChild(this.createProofCard(entry));
    });
  }

  renderDiagnosticsPanel() {
    const panel = document.getElementById('log-diagnostics-view');
    if (!panel) return;
    panel.replaceChildren();

    const stats = document.createElement('dl');
    stats.className = 'log-diagnostics-stats';
    const diagnosticStats = this.computeDiagnosticStats(this.allEntries);
    [
      ['Loaded entries', this.allEntries.length],
      ['Visible in view', this.filteredEntries.length],
      ['Deferred/reserved rows', diagnosticStats.deferredReserved],
      ['Conflict/ambiguous rows', diagnosticStats.conflictAmbiguous],
      ['Blocked/error rows', diagnosticStats.diagnostic]
    ].forEach(([label, value]) => {
      const wrap = document.createElement('div');
      wrap.className = 'log-diagnostics-stat';
      const dt = document.createElement('dt');
      dt.textContent = label;
      const dd = document.createElement('dd');
      dd.textContent = String(value);
      wrap.append(dt, dd);
      stats.appendChild(wrap);
    });
    panel.appendChild(stats);

    const diagnosticEntries = this.filteredEntries.filter(entry => this.isDiagnosticEntry(entry));
    if (diagnosticEntries.length === 0) {
      panel.appendChild(this.createPanelEmpty('No diagnostic, deferred/reserved, conflict, or blocked rows match the current filters.'));
      return;
    }

    const list = document.createElement('ul');
    list.className = 'log-view-list';
    this.getPageEntries(diagnosticEntries).forEach((entry) => {
      const item = document.createElement('li');
      item.className = 'log-view-list-item';
      const fields = [
        this.createInlineLabel('Status', this.describeMatrixStatus(entry)),
        this.createInlineLabel('Event', this.formatEventLabel(entry)),
      ];
      const distinctSummary = this.getDistinctHumanSummary(entry);
      if (distinctSummary) {
        fields.push(this.createInlineLabel('Summary', distinctSummary));
      }
      item.append(...fields);
      list.appendChild(item);
    });
    panel.appendChild(list);
  }

  computeDiagnosticStats(entries) {
    const counts = {
      deferredReserved: 0,
      conflictAmbiguous: 0,
      diagnostic: 0,
    };
    entries.forEach((entry) => {
      const status = this.getMatrixStatus(entry);
      if (status === 'deferred_reserved') counts.deferredReserved += 1;
      if (status === 'conflict_ambiguous') counts.conflictAmbiguous += 1;
      if (this.isDiagnosticEntry(entry)) counts.diagnostic += 1;
    });
    return counts;
  }

  async applyRouteTransferArrival() {
    const container = document.getElementById('view-activity-log');
    if (!container) return;
    const liveIntent = window.Shell?.getRouteTransferIntent?.('/activity-log') || null;
    const intent = liveIntent || pendingActivityLogIntent;
    if (intent) await this.applyRouteTransferFilters(intent);
    const arrival = liveIntent
      ? window.Shell?.applyRouteTransferArrival?.('/activity-log', container)
      : null;
    if (intent) this.markFirstRouteTransferMatch(container);
    pendingActivityLogIntent = null;
    return arrival;
  }

  markFirstRouteTransferMatch(container = document.getElementById('view-activity-log')) {
    container?.querySelectorAll('[data-route-handoff-match]').forEach((node) => {
      node.removeAttribute('data-route-handoff-match');
    });
    const firstMatch = container?.querySelector('[data-log-event-type]');
    if (firstMatch) firstMatch.setAttribute('data-route-handoff-match', 'true');
    return firstMatch || null;
  }

  async applyRouteTransferFilters(intent) {
    const rawEntity = String(intent?.targetEntityId || '').trim();
    if (!rawEntity) return;
    let dimension = 'all';
    let query = rawEntity.replace(/-/g, ' ');
    const colon = rawEntity.indexOf(':');
    if (colon > 0 && ENTITY_DIMENSION_KEYS.includes(rawEntity.slice(0, colon))) {
      dimension = rawEntity.slice(0, colon);
      query = rawEntity.slice(colon + 1);
    } else if (rawEntity === 'commander-memory') {
      dimension = 'event';
      query = 'commander memory';
    } else if (rawEntity === 'startup-outcome') {
      dimension = 'event';
      query = 'startup outcome';
    }

    const search = document.getElementById('log-search');
    const entity = document.getElementById('log-entity-filter');
    if (search) search.value = query;
    if (entity) entity.value = dimension;
    document.querySelectorAll('.log-filter:checked').forEach((input) => { input.checked = false; });
    this.activeView = 'proof';
    this._computeFilteredEntries();
    await this.renderPage();
  }

  createPanelEmpty(message) {
    const p = document.createElement('p');
    p.className = 'log-section-hint';
    p.textContent = message;
    return p;
  }

  createInlineLabel(labelText, valueText) {
    const wrap = document.createElement('span');
    wrap.className = 'log-inline-field';
    const label = document.createElement('span');
    label.className = 'log-inline-label';
    label.textContent = labelText;
    const value = document.createElement('span');
    value.className = 'log-inline-value';
    value.textContent = valueText === null || valueText === undefined ? 'Unknown' : String(valueText);
    wrap.append(label, value);
    return wrap;
  }

  createProofCard(entry) {
    const card = document.createElement('article');
    card.className = 'log-proof-card';
    card.dataset.logEventType = entry.event_type || 'unknown';

    const heading = document.createElement('h3');
    heading.className = 'log-proof-card-title';
    heading.textContent = this.formatEventLabel(entry);
    card.appendChild(heading);

    const distinctSummary = this.getDistinctHumanSummary(entry);
    if (distinctSummary) {
      const summary = document.createElement('p');
      summary.className = 'log-proof-card-summary';
      summary.textContent = distinctSummary;
      card.appendChild(summary);
    }

    card.appendChild(this.createProofDetails(entry));
    return card;
  }

  createProofDetails(entry) {
    const details = document.createElement('details');
    details.className = 'log-entry-details';

    const summaryEl = document.createElement('summary');
    summaryEl.textContent = 'Proof';
    details.appendChild(summaryEl);

    const list = document.createElement('dl');
    list.className = 'log-entry-proof-list';
    this.appendProofField(list, 'Event type', entry.event_type || 'Unknown event');
    this.appendProofField(list, 'Event label', this.formatEventLabel(entry));
    this.appendProofField(list, 'Source', entry.source || 'activity_log');
    this.appendProofField(list, 'Timestamp', entry.timestamp || 'Unknown');
    this.appendProofField(list, 'Home status', this.describeMatrixStatus(entry));
    details.appendChild(list);

    const keyInventory = this.createPayloadKeyInventory(entry);
    details.appendChild(keyInventory);

    const sourceChainDetails = this.createSourceChainDetails(entry);
    if (sourceChainDetails) {
      details.appendChild(sourceChainDetails);
    }

    const entityDetails = this.createEntityIndexDetails(entry);
    if (entityDetails) details.appendChild(entityDetails);

    return details;
  }

  createEntityIndexDetails(entry) {
    const dimensions = ENTITY_DIMENSION_KEYS
      .map((dimension) => [dimension, this.getEntityValues(entry, dimension)])
      .filter(([, values]) => values.length > 0);
    if (dimensions.length === 0) return null;
    const details = document.createElement('details');
    details.className = 'log-entity-index-details';
    const summary = document.createElement('summary');
    summary.textContent = 'Indexed proof fields';
    details.appendChild(summary);
    const list = document.createElement('dl');
    list.className = 'log-entry-proof-list';
    dimensions.forEach(([dimension, values]) => {
      this.appendProofField(list, dimension, values.join(', '));
    });
    details.appendChild(list);
    return details;
  }

  appendProofField(list, labelText, valueText) {
    const dt = document.createElement('dt');
    dt.textContent = labelText;
    const dd = document.createElement('dd');
    dd.textContent = valueText === null || valueText === undefined ? 'Unknown' : String(valueText);
    list.append(dt, dd);
  }

  createPayloadKeyInventory(entry) {
    const wrap = document.createElement('section');
    wrap.className = 'log-entry-key-inventory';
    const heading = document.createElement('h4');
    heading.textContent = 'Payload key inventory';
    wrap.appendChild(heading);

    const payload = entry?.payload && typeof entry.payload === 'object' ? entry.payload : null;
    const displayPayload = payload && this.isPhase9Entry(entry) ? this.getPhase9DisplayPayload(entry) : payload;
    const payloadKeys = payload
      ? Object.keys(displayPayload)
      : (Array.isArray(entry?.payload_keys) ? entry.payload_keys.map(key => String(key)) : []);

    if (payloadKeys.length === 0) {
      const empty = document.createElement('p');
      empty.className = 'log-section-hint';
      empty.textContent = 'No payload keys supplied by this activity record.';
      wrap.appendChild(empty);
      return wrap;
    }

    const list = document.createElement('dl');
    list.className = 'log-entry-payload-keys';
    payloadKeys.sort((a, b) => a.localeCompare(b)).forEach((key) => {
      const dt = document.createElement('dt');
      dt.textContent = key;
      const dd = document.createElement('dd');
      dd.textContent = displayPayload ? this.safePayloadValue(entry, key, displayPayload[key]) : 'present';
      list.append(dt, dd);
    });
    wrap.appendChild(list);

    if (this.isPrivacySensitiveEntry(entry)) {
      const note = document.createElement('p');
      note.className = 'log-redaction-note';
      note.textContent = 'Private text and identity fields are redacted by default.';
      wrap.appendChild(note);
    }

    return wrap;
  }

  createSourceChainDetails(entry) {
    const chain = this.getSourceChainForDisplay(entry);
    if (chain.length === 0) return null;

    const details = document.createElement('details');
    details.className = 'log-source-chain-details';

    const summary = document.createElement('summary');
    summary.textContent = 'Source chain / why';
    details.appendChild(summary);

    const list = document.createElement('ol');
    list.className = 'log-source-chain-list';
    chain.forEach((sourceItem) => {
      const item = document.createElement('li');
      const fields = document.createElement('dl');
      fields.className = 'log-entry-proof-list';
      PHASE_9_ALLOWED_SOURCE_CHAIN_KEYS.forEach((key) => {
        if (!Object.prototype.hasOwnProperty.call(sourceItem, key)) return;
        this.appendProofField(fields, key, sourceItem[key]);
      });
      item.appendChild(fields);
      list.appendChild(item);
    });
    details.appendChild(list);
    return details;
  }

  safePayloadValue(entry, key, value) {
    if (this.shouldRedactPayloadKey(entry, key)) return '[redacted by default]';
    if (value === null || value === undefined) return 'not supplied';
    if (Array.isArray(value)) return `array (${value.length} items)`;
    if (typeof value === 'object') return `object (${Object.keys(value).length} keys)`;
    const text = String(value);
    return text.length > 80 ? `${text.slice(0, 77)}...` : text;
  }

  shouldRedactPayloadKey(entry, key) {
    const normalizedKey = this.normalizePayloadKey(key);
    if (SENSITIVE_PAYLOAD_KEYS.has(normalizedKey)) return true;
    return this.isPrivacySensitiveEntry(entry) && IDENTITY_PAYLOAD_KEYS.has(normalizedKey);
  }

  isPrivacySensitiveEntry(entry) {
    const type = normalizeEventType(entry);
    if (SENSITIVE_TEXT_EVENTS.has(type)) return true;
    if (SENSITIVE_IDENTITY_EVENTS.some(marker => type.includes(marker))) return true;
    const payload = entry?.payload && typeof entry.payload === 'object' ? entry.payload : {};
    return Object.keys(payload).some(key => SENSITIVE_PAYLOAD_KEYS.has(this.normalizePayloadKey(key)));
  }

  normalizePayloadKey(key) {
    return normalizeText(key).replace(/[^a-z0-9_]/g, '');
  }

  isPhase9Entry(entry) {
    return rawEventType(entry).toLowerCase().startsWith('phase_9.');
  }

  formatEventLabel(entry) {
    const eventType = rawEventType(entry);
    if (!eventType) return 'Unknown event';
    if (this._displayNames?.formatActivityEventType) {
      return this._displayNames.formatActivityEventType(eventType);
    }
    return eventType;
  }

  getPhase9DisplayPayload(entry) {
    const payload = entry?.payload && typeof entry.payload === 'object' ? entry.payload : {};
    const safePayload = {};
    Object.keys(payload).forEach((key) => {
      const normalized = this.normalizePayloadKey(key);
      if (PHASE_9_ALLOWED_PAYLOAD_KEYS.has(normalized)) {
        safePayload[key] = payload[key];
      }
    });
    return safePayload;
  }

  getSourceChainForDisplay(entry) {
    const payload = entry?.payload && typeof entry.payload === 'object' ? entry.payload : {};
    const sourceChain = Array.isArray(entry?.source_chain)
      ? entry.source_chain
      : Array.isArray(payload.source_chain)
      ? payload.source_chain
      : [];
    return sourceChain
      .filter(item => item && typeof item === 'object' && !Array.isArray(item))
      .map((item) => {
        const safeItem = {};
        PHASE_9_ALLOWED_SOURCE_CHAIN_KEYS.forEach((key) => {
          if (Object.prototype.hasOwnProperty.call(item, key)) {
            safeItem[key] = item[key];
          }
        });
        return safeItem;
      })
      .filter(item => Object.keys(item).length > 0);
  }

  getMatrixStatus(entry) {
    const payload = entry?.payload && typeof entry.payload === 'object' ? entry.payload : {};
    const text = [
      entry?.classification,
      entry?.matrix_status,
      entry?.home_status,
      entry?.status,
      entry?.summary,
      payload.classification,
      payload.matrix_status,
      payload.home_status,
      payload.status
    ].filter(Boolean).join(' ').toLowerCase();

    if (text.includes('conflict') || text.includes('ambiguous')) return 'conflict_ambiguous';
    if (text.includes('deferred') || text.includes('reserved') || text.includes('future')) return 'deferred_reserved';
    if (text.includes('raw') || text.includes('proof')) return 'raw_proof';
    return 'activity_log_home';
  }

  describeMatrixStatus(entry) {
    const status = this.getMatrixStatus(entry);
    if (status === 'conflict_ambiguous') return 'Conflict/ambiguous - review before route implementation';
    if (status === 'deferred_reserved') return 'Deferred/reserved - proof visible here';
    if (status === 'raw_proof') return 'Raw/proof Activity Log home';
    return 'Activity Log fallback home';
  }

  createLogRow(entry) {
    const row = document.createElement("tr");

    const timestamp = entry.timestamp || "";
    const source = entry.source || "system";
    const aiTier = entry.ai_tier || "—";
    const category = this.resolveCategory(entry); // Old category for class name compatibility

    const summary = this.getDistinctHumanSummary(entry);

    const timestampCell = document.createElement("td");
    timestampCell.className = "log-timestamp";
    timestampCell.textContent = this.formatTimestamp(timestamp);

    const eventCell = document.createElement("td");
    eventCell.className = `log-event-type ${category}`;
    const eventLabel = document.createElement('span');
    eventLabel.className = 'log-event-label';
    eventLabel.textContent = this.formatEventLabel(entry);
    eventCell.appendChild(eventLabel);

    const sourceCell = document.createElement("td");
    sourceCell.className = "log-source";
    if (this._sourceProof) {
       const sourceKey = source.toLowerCase().replace(/-/g, '_');
       if (['available', 'blocked', 'disabled', 'stale', 'no_verified_source', 'future', 'manual'].includes(sourceKey)) {
         try {
           const badge = this._sourceProof.createOmniStateBadge(sourceKey);
           sourceCell.appendChild(badge);
         } catch {
           sourceCell.textContent = source;
         }
       } else if (!['ai', 'ai_provider', 'system', 'unknown'].includes(sourceKey)) {
         try {
           let chipKey = sourceKey;
           if (chipKey === 'journal') chipKey = 'local_event_history';
           if (chipKey === 'status.json' || chipKey === 'system') chipKey = 'local_telemetry';
           if (chipKey === 'external_disabled') chipKey = 'external_disabled';
           const chip = this._sourceProof.createSourceChip(chipKey);
           sourceCell.appendChild(chip);
         } catch {
           sourceCell.textContent = source;
         }
       } else {
         sourceCell.textContent = source;
       }
    } else {
       sourceCell.textContent = source;
    }

    const summaryCell = document.createElement("td");
    summaryCell.className = "log-summary";
    if (summary) {
      const summaryText = document.createElement('span');
      summaryText.className = 'log-summary-text';
      summaryText.textContent = summary;
      summaryCell.appendChild(summaryText);
    }

    if (entry.payload && entry.payload.route_intent) {
       const link = document.createElement('a');
       link.href = `#${entry.payload.route_intent}`;
       link.className = 'ocv-route-handoff-link';
       link.textContent = `View in ${entry.payload.route_intent.replace('/', '')}`;
       link.onclick = (e) => {
         e.preventDefault();
         if (window.Shell && window.Shell.navigate) {
           window.Shell.navigate(entry.payload.route_intent);
         }
       };
       summaryCell.appendChild(link);
       summaryCell.appendChild(document.createElement('br'));
    }

    const chips = this.createPhase9Chips(entry);
    if (chips) summaryCell.appendChild(chips);

    /* PB09-08: Phase 9 owner-route back-links using allowlisted payload IDs only */
    if (this.isPhase9Entry(entry)) {
      const displayPayload = this.getPhase9DisplayPayload(entry);
      let ownerLink = null;
      if (displayPayload.campaign_id) {
        ownerLink = this._createOwnerRouteLink(
          'View in Operations', '/operations', String(displayPayload.campaign_id),
          'Viewing campaign from Activity Log.',
        );
      } else if (displayPayload.circuit_id) {
        ownerLink = this._createOwnerRouteLink(
          'View in Navigation', '/navigation', String(displayPayload.circuit_id),
          'Viewing circuit from Activity Log.',
        );
      } else if (displayPayload.note_id) {
        ownerLink = this._createOwnerRouteLink(
          'View in Squadrons', '/squadrons', String(displayPayload.note_id),
          'Viewing note from Activity Log.',
        );
      }
      if (ownerLink) summaryCell.appendChild(ownerLink);
    }

    summaryCell.appendChild(this.createProofDetails(entry));

    const tierCell = document.createElement("td");
    tierCell.textContent = aiTier;

    row.append(timestampCell, eventCell, sourceCell, summaryCell, tierCell);

    return row;
  }

  /* PB09-08: creates a button that navigates to an owner route using RouteTransferIntent.
     entityId must be a pre-filtered allowlisted ID (never raw text). */
  _createOwnerRouteLink(label, targetRoute, entityId, reason) {
    const btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'log-phase9-owner-link';
    btn.textContent = label;
    btn.addEventListener('click', () => {
      if (typeof window.Shell?.startRouteTransfer !== 'function') {
        window.location.hash = `#${targetRoute}`;
        return;
      }
      window.Shell.startRouteTransfer({
        originRoute: '/activity-log',
        originPackage: 'Activity Log',
        originSectionId: 'log-body',
        targetRoute,
        targetSectionId: '',
        targetEntityId: entityId,
        targetLabel: label,
        reason,
        returnLabel: 'Return to Activity Log',
        returnTarget: { route: '/activity-log' },
      });
    });
    return btn;
  }

  createPhase9Chips(entry) {
    if (!this.isPhase9Entry(entry)) return null;
    const payload = this.getPhase9DisplayPayload(entry);
    const chips = [];
    const type = rawEventType(entry).toLowerCase();

    if (type.startsWith('phase_9.campaign.ai_draft') || payload.is_fact === false) {
      chips.push(['is_fact', 'false']);
    }
    if (type.startsWith('phase_9.squadron.') || payload.visibility === 'local_only') {
      chips.push(['visibility', 'local_only']);
    }
    if (payload.source_label) {
      chips.push(['source', payload.source_label]);
    } else if (payload.source_type) {
      chips.push(['source', payload.source_type]);
    } else if (this.getSourceChainForDisplay(entry).length > 0) {
      chips.push(['source', 'source_chain']);
    }

    if (chips.length === 0) return null;
    const wrap = document.createElement('div');
    wrap.className = 'log-phase9-chips';
    chips.forEach(([label, value]) => {
      const chip = document.createElement('span');
      chip.className = 'log-phase9-chip';
      chip.textContent = `${label}=${value}`;
      wrap.appendChild(chip);
    });
    return wrap;
  }

  formatTimestamp(ts) {
    if (!ts) return "";
    try {
      const date = new Date(ts);
      return date.toLocaleString([], {
        year: "numeric",
        month: "2-digit",
        day: "2-digit",
        hour: "2-digit",
        minute: "2-digit",
        second: "2-digit",
      });
    } catch {
      return ts;
    }
  }

  updatePagination() {
    const maxPage = Math.max(
      1,
      Math.ceil(this.filteredEntries.length / this.pageSize)
    );
    const pageInfo = document.getElementById("log-page-info");
    if (pageInfo) {
      pageInfo.textContent = `Page ${this.currentPage + 1} of ${maxPage}`;
    }

    const prevBtn = document.getElementById("log-prev-btn");
    const nextBtn = document.getElementById("log-next-btn");

    if (prevBtn) prevBtn.disabled = this.currentPage === 0;
    if (nextBtn) nextBtn.disabled = this.currentPage >= maxPage - 1;
  }

  /**
   * Export the current filtered view to a local JSON file.
   *
   * Law 8 / Master §11.5: an export of commander data is a protected action,
   * so it is authorized and recorded by the backend before any file is built.
   *
   * Law 5 (truthful proof): the browser cannot prove a download reached disk,
   * so this reports two honest stages to the backend — the export was
   * requested/authorized, and then either the download was *initiated* or it
   * failed. Nothing here ever claims a completed export.
   *
   * One frozen snapshot of the filtered view drives the confirmation text,
   * the audit metadata, and the generated payload, so the commander cannot be
   * shown one count and given another.
   */
  async exportLog() {
    const snapshot = this.filteredEntries.slice();
    const entryCount = snapshot.length;

    const proposeUrl = this.apiUrl('/activity-log/export/propose');
    const authorizeUrl = this.apiUrl('/activity-log/export/authorize');
    const resultUrl = this.apiUrl('/activity-log/export/result');
    if (!proposeUrl || !authorizeUrl || !resultUrl) {
      this.notify('Cannot export: the local backend bridge is not connected.', 'error');
      return;
    }

    // Stage 1 — propose. The commander answers in the shared Confirmation
    // Gate; this client cannot authorize anything on its own.
    let confirmationId = null;
    try {
      const res = await fetch(proposeUrl, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ entry_count: entryCount, scope: 'filtered_view' }),
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      confirmationId = (await res.json())?.confirmation_id ?? null;
      if (!confirmationId) throw new Error('backend returned no confirmation_id');
    } catch (err) {
      console.error('Activity Log export could not be proposed:', err);
      this.notify('Could not request confirmation for the export. Nothing was exported.', 'error');
      return;
    }

    this.notify('Export awaiting your confirmation in the Confirmation Gate.', 'info');

    // Stage 2 — wait for the commander decision, then consume it once.
    let exportId = null;
    try {
      exportId = await this._awaitExportAuthorization(authorizeUrl, confirmationId, entryCount);
    } catch (err) {
      console.error('Activity Log export was not authorized:', err);
      this.notify(err?.commanderMessage || 'The export was not authorized. No file was written.', 'error');
      return;
    }
    if (!exportId) return;

    // Stage 2 — build and hand the file to the browser, then report honestly.
    let filename = null;
    try {
      const json = JSON.stringify(
        {
          total: snapshot.length,
          entries: snapshot,
          exported_at: new Date().toISOString(),
        },
        null,
        2
      );

      const blob = new Blob([json], { type: "application/json" });
      const blobUrl = URL.createObjectURL(blob);
      filename = `omnicovas-activity-log-${new Date().toISOString().slice(0, 10)}.json`;
      const a = document.createElement("a");
      a.href = blobUrl;
      a.download = filename;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(blobUrl);
    } catch (err) {
      console.error('Activity Log export failed before a file was written:', err);
      await this._reportExportResult(resultUrl, exportId, 'failed');
      this.notify('Failed to prepare the export. No file was written.', 'error');
      await this._loadAndRender();
      return;
    }

    // The download is away. Whether that fact reached the audit log is a
    // separate question, and the commander is told which one actually holds.
    const recorded = await this._reportExportResult(resultUrl, exportId, 'download_initiated');
    if (recorded.ok) {
      this.notify(`Activity Log export started — download initiated as ${filename}`, 'success');
    } else {
      this.notify(
        `Download initiated as ${filename}, but OmniCOVAS could not record the audit result.`,
        'warning',
      );
    }
    // Surface the new export proof events in this same view.
    await this._loadAndRender();
  }

  /**
   * Poll for the commander decision on an export proposal.
   *
   * Returns an export id only when the backend consumed a genuine confirmed
   * decision. A decline, an expiry, or an unknown confirmation throws with a
   * commander-facing message; nothing here can authorize on its own.
   */
  async _awaitExportAuthorization(authorizeUrl, confirmationId, entryCount) {
    const intervalMs = 1000;
    const maxAttempts = 300; // bounded wait; matches the proposal TTL
    // The shared gate owns the confirmation surface and its timers. Without it
    // there is nowhere for the commander to decide, so waiting is pointless.
    const gate = window.OmniConfirmationGate;
    if (!gate?.delay) {
      const unavailable = new Error('shared Confirmation Gate unavailable');
      unavailable.commanderMessage =
        'The Confirmation Gate is unavailable, so the export cannot be confirmed.';
      throw unavailable;
    }

    for (let attempt = 0; attempt < maxAttempts; attempt += 1) {
      const res = await fetch(authorizeUrl, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ confirmation_id: confirmationId, entry_count: entryCount }),
      });

      if (res.ok) {
        const data = await res.json();
        if (data?.authorized && data?.export_id) return data.export_id;
        // Still pending: the commander has not answered yet.
        await gate.delay(intervalMs);
        continue;
      }

      const error = new Error(`HTTP ${res.status}`);
      let detail = '';
      try {
        detail = (await res.json())?.detail || '';
      } catch { /* non-JSON error body */ }
      error.commanderMessage = /declin/i.test(detail)
        ? 'Export declined. Nothing was exported.'
        : /expired/i.test(detail)
          ? 'The export confirmation expired. Nothing was exported.'
          : 'The export was not authorized. No file was written.';
      throw error;
    }

    const timeout = new Error('confirmation wait exceeded');
    timeout.commanderMessage = 'The export confirmation timed out. Nothing was exported.';
    throw timeout;
  }

  /**
   * Report a staged export outcome.
   *
   * Returns {ok} describing whether the audit result was actually recorded, so
   * the caller never shows a plain success message for an unrecorded outcome.
   * Retries once on a network error or a 5xx, since the backend keeps the
   * ticket alive until a proof entry is appended.
   */
  async _reportExportResult(resultUrl, exportId, outcome) {
    for (let attempt = 0; attempt < 2; attempt += 1) {
      try {
        const res = await fetch(resultUrl, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ export_id: exportId, outcome }),
        });
        if (res.ok) return { ok: true, status: res.status };
        // 4xx is terminal: the ticket is gone or the request is malformed.
        if (res.status < 500) {
          console.error(`Export outcome was rejected: HTTP ${res.status}`);
          return { ok: false, status: res.status };
        }
        console.error(`Export outcome could not be recorded: HTTP ${res.status}`);
      } catch (err) {
        console.error('Failed to record the export outcome:', err);
      }
    }
    return { ok: false, status: null };
  }

  async showClearConfirm() {
    const gate = window.OmniConfirmationGate;
    if (!gate?.confirmLocalAction) {
      console.error('[ActivityLog] Shared Confirmation Gate is unavailable.');
      return;
    }
    const confirmed = await gate.confirmLocalAction({
      title: 'Clear Activity Log display?',
      message: 'This clears only the current display. Stored history is not deleted.',
      confirmLabel: 'Clear display',
      danger: true,
    });
    if (confirmed) await this.clearLog();
  }

  async clearLog() {
    try {
      // In Phase 3, there's no /activity-log/clear endpoint
      this.allEntries = [];
      this.filteredEntries = [];
      this.currentPage = 0;

      this.renderPage();
      window.OmniConfirmationGate?.announce?.(
        'Activity Log display cleared. Stored history was not deleted.',
        { kind: 'success' },
      );
    } catch (err) {
      console.error("Failed to clear log:", err);
      window.OmniConfirmationGate?.announce?.(
        'Failed to clear Activity Log display. See console for details.',
        { kind: 'error' },
      );
    }
  }
}

/* Module-scope handoff listener. The shell can apply the visible arrival banner
 * and clear its intent before an already-mounted Activity Log controller gets a
 * render turn. Capture the intent from the event itself and apply the filter on
 * the next microtask; unlike requestAnimationFrame this also runs while the
 * window is hidden or minimised. If the first fetch is still pending, the
 * intent stays queued for `_loadAndRender` instead.
 *
 * An already-mounted controller holds entries from its last fetch, and proof
 * rows written after that fetch (e.g. a Memory export completed on Privacy
 * moments ago) do not exist in that snapshot. Arrival promises current proof,
 * so this path must re-fetch before it filters. */
window.OmniEvents = window.OmniEvents || new EventTarget();
if (!window.__omniActivityLogTransferListener) {
  window.__omniActivityLogTransferListener = true;
  window.OmniEvents.addEventListener('route-transfer-started', (event) => {
    const intent = event?.detail?.intent;
    if (intent?.targetRoute !== '/activity-log') return;
    pendingActivityLogIntent = intent;
    queueMicrotask(async () => {
      const controller = activeActivityLogController;
      if (!controller || controller._loadedOnce !== true || pendingActivityLogIntent !== intent) return;
      await controller.loadActivityLog();
      if (activeActivityLogController !== controller || pendingActivityLogIntent !== intent) return;
      await controller.renderRouteHero();
      await controller.applyRouteTransferFilters(intent);
      controller.markFirstRouteTransferMatch();
      pendingActivityLogIntent = null;
    }, 0);
  });
}

globalThis.__activityLogExports = {
  ActivityLogController,
  __setActiveControllerForTest(controller) { activeActivityLogController = controller; },
  __resetTransferState() { pendingActivityLogIntent = null; },
};

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", () => {
    new ActivityLogController();
  });
} else {
  new ActivityLogController();
}
